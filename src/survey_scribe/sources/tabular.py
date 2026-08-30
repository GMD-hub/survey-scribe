"""Deterministic CSV and lazy-openpyxl XLSX source adapters."""

from __future__ import annotations

import csv
import re
import time
import zipfile
from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from typing import Any, TypeAlias
from xml.etree import ElementTree

from survey_scribe.sources.base import (
    ResolvedSource,
    SourceBlock,
    SourceConversionError,
    SourceDependencyError,
    SourceDocument,
    SourceFormatError,
    SourceLimitError,
    SourceLimits,
    SourceProvenance,
    SourceSecurityError,
    SourceTable,
    SourceTimeoutError,
    inspect_zip_archive,
    render_table,
)

_CELL_REFERENCE = re.compile(r"^([A-Z]+)([1-9][0-9]*)$")
_SPREADSHEETML_NAMESPACE = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_CELL_TAG = f"{{{_SPREADSHEETML_NAMESPACE}}}c"
_DIMENSION_TAG = f"{{{_SPREADSHEETML_NAMESPACE}}}dimension"
_FORMULA_TAG = f"{{{_SPREADSHEETML_NAMESPACE}}}f"


WorkbookLoader: TypeAlias = Callable[..., Any]


class CsvAdapter:
    """Normalize UTF-8 CSV rows with physical one-based row provenance."""

    def convert(self, source: ResolvedSource, *, limits: SourceLimits) -> SourceDocument:
        deadline = time.monotonic() + limits.deadline_seconds
        try:
            rows: list[tuple[str, ...]] = []
            cell_count = 0
            with source.primary.open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.reader(stream, strict=True)
                for row in reader:
                    _check_deadline(deadline)
                    if any("\x00" in cell for cell in row):
                        raise SourceFormatError("CSV source contains binary NUL bytes")
                    cell_count += len(row)
                    if cell_count > limits.max_cells:
                        raise SourceLimitError("max_cells", "CSV exceeds the configured cell limit")
                    rows.append(tuple(row))
        except UnicodeDecodeError as error:
            raise SourceFormatError("CSV source must use UTF-8 encoding") from error
        except OSError as error:
            raise SourceConversionError("CSV source could not be read") from error
        except csv.Error as error:
            raise SourceFormatError("CSV source is malformed") from error

        table_rows = tuple(rows)
        blocks: tuple[SourceBlock, ...] = ()
        if table_rows:
            provenance = SourceProvenance(
                source_name=source.primary.name,
                row_start=1,
                row_end=len(table_rows),
            )
            table = SourceTable(id="table-000001", rows=table_rows, provenance=provenance)
            blocks = (
                SourceBlock(
                    id="block-000001",
                    order=0,
                    kind="table",
                    text=render_table(table_rows),
                    provenance=provenance,
                    table=table,
                ),
            )
        return SourceDocument(
            source_name=source.primary.name,
            media_type="text/csv",
            blocks=blocks,
        )


class XlsxAdapter:
    """Normalize XLSX cells without formulas, macros, links, or eager workbook loading."""

    def __init__(self, *, workbook_loader: WorkbookLoader | None = None) -> None:
        self._workbook_loader = workbook_loader

    def convert(self, source: ResolvedSource, *, limits: SourceLimits) -> SourceDocument:
        deadline = time.monotonic() + limits.deadline_seconds
        _inspect_xlsx(source.primary, limits, deadline)
        loader = self._workbook_loader or _load_openpyxl_workbook
        try:
            workbook = loader(
                source.primary,
                read_only=True,
                data_only=False,
                keep_links=False,
            )
        except SourceDependencyError:
            raise
        except Exception as error:
            raise SourceFormatError("XLSX workbook could not be opened safely") from error

        blocks: list[SourceBlock] = []
        cell_count = 0
        try:
            for sheet_name in workbook.sheetnames:
                _check_deadline(deadline)
                worksheet = workbook[sheet_name]
                rows: list[tuple[str, ...]] = []
                for source_row in worksheet.iter_rows():
                    _check_deadline(deadline)
                    rendered_row: list[str] = []
                    for cell in source_row:
                        cell_count += 1
                        if cell_count > limits.max_cells:
                            raise SourceLimitError(
                                "max_cells", "XLSX exceeds the configured cell limit"
                            )
                        if getattr(cell, "data_type", None) == "f":
                            raise SourceSecurityError("XLSX formula content is prohibited")
                        rendered_row.append(_render_cell(getattr(cell, "value", None)))
                    rows.append(tuple(rendered_row))
                if not rows:
                    continue
                table_rows = tuple(rows)
                provenance = SourceProvenance(
                    source_name=source.primary.name,
                    sheet=str(sheet_name),
                    row_start=1,
                    row_end=len(table_rows),
                )
                table = SourceTable(
                    id=f"table-{len(blocks) + 1:06d}",
                    rows=table_rows,
                    provenance=provenance,
                )
                blocks.append(
                    SourceBlock(
                        id=f"block-{len(blocks) + 1:06d}",
                        order=len(blocks),
                        kind="table",
                        text=render_table(table_rows),
                        provenance=provenance,
                        table=table,
                    )
                )
        finally:
            workbook.close()
        return SourceDocument(
            source_name=source.primary.name,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            blocks=tuple(blocks),
        )


def _load_openpyxl_workbook(filename: Path, **kwargs: object) -> Any:
    try:
        module = import_module("openpyxl")
    except ModuleNotFoundError as error:
        raise SourceDependencyError(
            "XLSX conversion requires the optional 'tabular' dependencies"
        ) from error
    return module.load_workbook(filename, **kwargs)


def _inspect_xlsx(path: Path, limits: SourceLimits, deadline: float) -> None:
    entries = inspect_zip_archive(path, limits)
    normalized_names = {entry.filename.replace("\\", "/").lower() for entry in entries}
    if any(
        name.endswith("vbaproject.bin")
        or name.startswith("xl/macrosheets/")
        or name.startswith("xl/dialogsheets/")
        for name in normalized_names
    ):
        raise SourceSecurityError("XLSX macro content is prohibited")
    if any(name.startswith("xl/externallinks/") for name in normalized_names):
        raise SourceSecurityError("XLSX external link content is prohibited")

    cell_count = 0
    try:
        with zipfile.ZipFile(path) as archive:
            for entry in entries:
                _check_deadline(deadline)
                normalized = entry.filename.replace("\\", "/").lower()
                if normalized.endswith(".rels"):
                    _reject_external_relationships(archive.read(entry), "XLSX")
                if not (normalized.startswith("xl/worksheets/") and normalized.endswith(".xml")):
                    continue
                declared_bound: tuple[int, int] | None = None
                dimension_seen = False
                observed_column = 0
                observed_row = 0
                depth = 0
                with archive.open(entry) as stream:
                    for event, element in ElementTree.iterparse(stream, events=("start", "end")):
                        _check_deadline(deadline)
                        if event == "start":
                            depth += 1
                            continue
                        if element.tag == _DIMENSION_TAG:
                            if depth != 2 or dimension_seen:
                                raise SourceFormatError(
                                    "XLSX worksheet dimension must be one unique direct child"
                                )
                            dimension_seen = True
                            declared_bound = _dimension_bound(element.attrib.get("ref"), limits)
                        elif element.tag == _FORMULA_TAG:
                            raise SourceSecurityError("XLSX formula content is prohibited")
                        elif element.tag == _CELL_TAG:
                            column, row = _cell_coordinates(element.attrib.get("r"))
                            observed_column = max(observed_column, column)
                            observed_row = max(observed_row, row)
                            cell_count += 1
                            if cell_count > limits.max_cells:
                                raise SourceLimitError(
                                    "max_cells", "XLSX exceeds the configured cell limit"
                                )
                        element.clear()
                        depth -= 1
                _check_observed_bound(
                    declared=declared_bound,
                    observed=(observed_column, observed_row),
                    limits=limits,
                )
    except (SourceLimitError, SourceSecurityError, SourceTimeoutError):
        raise
    except ElementTree.ParseError as error:
        raise SourceFormatError("XLSX package XML is malformed") from error
    except (OSError, zipfile.BadZipFile, RuntimeError) as error:
        raise SourceConversionError("XLSX package could not be inspected") from error


def _reject_external_relationships(payload: bytes, source_kind: str) -> None:
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as error:
        raise SourceFormatError(f"{source_kind} relationship XML is malformed") from error
    for relationship in root:
        mode = relationship.attrib.get("TargetMode", "").lower()
        target = relationship.attrib.get("Target", "")
        if mode == "external" or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE):
            raise SourceSecurityError(f"{source_kind} external relationship is prohibited")


def _dimension_bound(reference: str | None, limits: SourceLimits) -> tuple[int, int] | None:
    if not reference:
        return None
    end = reference.split(":")[-1].replace("$", "").upper()
    column, row = _cell_coordinates(end)
    if column * row > limits.max_cells:
        raise SourceLimitError("max_cells", "XLSX worksheet dimension exceeds the cell limit")
    return column, row


def _cell_coordinates(reference: str | None) -> tuple[int, int]:
    match = _CELL_REFERENCE.fullmatch((reference or "").replace("$", "").upper())
    if match is None:
        raise SourceFormatError("XLSX cell reference or dimension is malformed")
    column_letters, row_text = match.groups()
    column = 0
    for character in column_letters:
        column = column * 26 + ord(character) - ord("A") + 1
    row = int(row_text)
    if column > 16_384 or row > 1_048_576:
        raise SourceFormatError("XLSX cell reference exceeds Excel worksheet limits")
    return column, row


def _check_observed_bound(
    *,
    declared: tuple[int, int] | None,
    observed: tuple[int, int],
    limits: SourceLimits,
) -> None:
    column, row = observed
    if column * row > limits.max_cells:
        raise SourceLimitError("max_cells", "XLSX worksheet dimension exceeds the cell limit")
    if declared is not None and (column > declared[0] or row > declared[1]):
        raise SourceFormatError("XLSX worksheet dimension omits observed cells")


def _render_cell(value: object) -> str:
    if value is None:
        return ""
    if value is True:
        return "TRUE"
    if value is False:
        return "FALSE"
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return str(value)


def _check_deadline(deadline: float) -> None:
    if time.monotonic() > deadline:
        raise SourceTimeoutError("Source conversion exceeded the configured deadline")
