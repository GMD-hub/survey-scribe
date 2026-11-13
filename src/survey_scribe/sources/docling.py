"""Safe document adapters, including killable local Docling PDF conversion."""

from __future__ import annotations

import os
import re
import shutil
import signal
import socket
import threading
import time
import traceback
import zipfile
from collections.abc import Iterable, Iterator, Mapping
from contextlib import AbstractContextManager, ExitStack, contextmanager, nullcontext, suppress
from dataclasses import dataclass
from html.parser import HTMLParser
from importlib import import_module
from io import BytesIO
from multiprocessing import get_context
from multiprocessing.connection import wait
from pathlib import Path
from queue import Empty
from typing import Any, Literal, Protocol, cast, runtime_checkable
from xml.etree.ElementTree import Element

from defusedxml import ElementTree

from survey_scribe.sources.base import (
    ResolvedSource,
    SourceBlock,
    SourceConversionError,
    SourceCoverage,
    SourceDependencyError,
    SourceDiagnostic,
    SourceDocument,
    SourceError,
    SourceFormatError,
    SourceLimitError,
    SourceLimits,
    SourceProgress,
    SourceProvenance,
    SourceSecurityError,
    SourceTable,
    SourceTimeoutError,
    external_links_stripped_diagnostic,
    inspect_zip_archive,
    read_utf8_text,
    render_table,
)
from survey_scribe.sources.ocr import (
    OcrCacheError,
    resolve_ocr_cache,
    validated_ocr_model_snapshot,
)

_WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_RELATIONSHIP_NAMESPACE = "http://schemas.openxmlformats.org/package/2006/relationships"
_WORD_TRANSPARENT_CONTAINERS = frozenset(
    {
        "customXml",
        "del",
        "fldSimple",
        "ins",
        "moveFrom",
        "moveTo",
        "sdt",
        "sdtContent",
        "smartTag",
    }
)
_WORD_METADATA_ELEMENTS = frozenset(
    {
        "bookmarkEnd",
        "bookmarkStart",
        "commentRangeEnd",
        "commentRangeStart",
        "customXmlDelRangeEnd",
        "customXmlDelRangeStart",
        "customXmlInsRangeEnd",
        "customXmlInsRangeStart",
        "moveFromRangeEnd",
        "moveFromRangeStart",
        "moveToRangeEnd",
        "moveToRangeStart",
        "permEnd",
        "permStart",
        "proofErr",
        "sdtEndPr",
        "sdtPr",
        "sectPr",
    }
)


@dataclass(frozen=True, slots=True)
class PdfConversionBlock:
    """Serializable local Docling output returned through the worker boundary."""

    text: str
    page: int | None = None
    pages: tuple[int, ...] = ()
    table_rows: tuple[tuple[str, ...], ...] = ()
    section_path: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        pages = self.pages
        if self.page is not None and not pages:
            pages = (self.page,)
            object.__setattr__(self, "pages", pages)
        elif self.page is None and pages:
            object.__setattr__(self, "page", pages[0])
        if any(isinstance(page, bool) or page < 1 for page in pages):
            raise ValueError("PDF block pages must be positive integers")
        if tuple(sorted(set(pages))) != pages:
            raise ValueError("PDF block pages must be unique and ordered")
        if pages and self.page != pages[0]:
            raise ValueError("PDF block page must be its first provenance page")


@dataclass(frozen=True, slots=True)
class PdfConversion:
    """Serializable PDF conversion result with physical page count."""

    page_count: int
    blocks: tuple[PdfConversionBlock, ...]
    coverage: SourceCoverage | None = None
    diagnostics: tuple[SourceDiagnostic, ...] = ()


class PdfConverter(Protocol):
    """Injectable, pickle-safe PDF conversion callable."""

    def __call__(self, path: str, artifacts_path: str | None) -> PdfConversion:
        """Convert one PDF using local resources only."""
        ...


PageRange = tuple[int, int]


@runtime_checkable
class PdfPageRangeConverter(PdfConverter, Protocol):
    """A converter that reads a PDF range by range, so the adapter can report progress and
    keep finished pages when the deadline is reached."""

    def convert_pages(
        self,
        path: str,
        artifacts_path: str | None,
        ranges: tuple[PageRange, ...],
    ) -> Iterator[PdfConversion]:
        """Yield one conversion per inclusive one-based page range, in order.

        Each conversion's ``page_count`` is the whole document's. Its ``coverage``, when set,
        lists the range's converted pages in ``converted_units``; pages outside the range are
        ignored. Without ``coverage`` every page of the range counts as converted.
        """
        ...


@runtime_checkable
class PersistentPdfConverter(PdfConverter, Protocol):
    """A converter that loads its models once and reuses them across many documents.

    A long-lived worker enters :meth:`opened` for the document it processes; while the context
    is open every :meth:`__call__` (and ``convert_pages`` on a range converter) reuses the one
    built pipeline instead of reloading layout and table models per document.
    """

    def opened(self, artifacts_path: str | None) -> AbstractContextManager[None]:
        """Load the models once and reuse them for every call until the context exits."""
        ...


IsolationMode = Literal["process", "worker", "inprocess"]
"""How a Docling adapter isolates a conversion from the host.

``"process"`` spawns a fresh killable worker per document (the default, the established
behaviour). ``"worker"`` keeps one long-lived spawned worker per adapter instance, loading the
models once and streaming documents through it, and kills it on a deadline or on ``close()``.
``"inprocess"`` runs the conversion directly in the calling process with no child, for a
container that is itself the disposable sandbox.
"""

_ISOLATION_MODES: tuple[IsolationMode, ...] = ("process", "worker", "inprocess")


_OCR_MODES = ("always", "auto", "never")
_TABLE_MODES = ("accurate", "fast")
_PDF_ENV_PREFIX = "SURVEY_SCRIBE_PDF_"


def isolation_from_environment(environ: Mapping[str, str] | None = None) -> IsolationMode:
    """``SURVEY_SCRIBE_PDF_ISOLATION`` as an isolation mode; ``process`` when unset."""
    env = os.environ if environ is None else environ
    value = (env.get(_PDF_ENV_PREFIX + "ISOLATION") or "").strip().lower()
    if not value:
        return "process"
    if value not in _ISOLATION_MODES:
        raise ValueError(
            f"{_PDF_ENV_PREFIX}ISOLATION must be one of {_ISOLATION_MODES}, not {value!r}"
        )
    return cast("IsolationMode", value)


def block_network_from_environment(environ: Mapping[str, str] | None = None) -> bool:
    """``SURVEY_SCRIBE_PDF_BLOCK_NETWORK`` as a boolean; ``True`` when unset."""
    env = os.environ if environ is None else environ
    value = env.get(_PDF_ENV_PREFIX + "BLOCK_NETWORK")
    if value is None or not value.strip():
        return True
    lowered = value.strip().lower()
    if lowered in ("1", "true", "yes", "on"):
        return True
    if lowered in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"{_PDF_ENV_PREFIX}BLOCK_NETWORK must be a boolean, not {value!r}")


@dataclass(frozen=True, slots=True)
class PdfConversionOptions:
    """How the local Docling pipeline reads a PDF.

    The defaults are Survey Scribe's established behaviour: full-page English OCR of every page,
    flat section headings, body text only. Each field loosens one of those choices for a caller
    that knows its documents; nothing changes for one that does not.

    Attributes:
        ocr: ``"always"`` runs OCR over every page (the text layer is ignored); ``"auto"`` keeps
            the text layer and runs OCR only where a page has none; ``"never"`` reads the text
            layer alone, needs no OCR artifacts, and keeps any script the PDF carries verbatim.
        ocr_languages: EasyOCR language codes. OCR currently supports only English because the
            approved model snapshot contains only the English recognition model.
        heading_levels: infer heading depth (bookmarks, numbering, font style) instead of
            reporting every heading at level 1; ``section_path`` then carries the ancestors.
        max_heading_level: the deepest level the inference assigns.
        include_furniture: keep page headers and footers. The layout model files a section title
            printed at the top of a page as a page header, which the default read drops.
        table_mode: TableFormer ``"accurate"`` (slower) or ``"fast"``.
        pages_per_chunk: convert this many pages per Docling call, reporting progress and
            keeping finished pages after each one. ``None`` (the default) converts the document
            in one call, as before. Inferred heading levels are computed per chunk; the section
            path carries across.
        first_pages: convert only the first N pages (a smoke-test read); coverage lists the
            remaining pages as not converted.
        partial_on_deadline: when the deadline is reached, return the chunks already converted
            (coverage lists the rest as failed, with a ``PDF_DEADLINE_PARTIAL`` warning)
            instead of raising ``SourceTimeoutError``. Needs ``pages_per_chunk``: in one call
            nothing finishes before the deadline, so the timeout is still raised.
    """

    ocr: str = "always"
    ocr_languages: tuple[str, ...] = ("en",)
    heading_levels: bool = False
    max_heading_level: int = 6
    include_furniture: bool = False
    table_mode: str = "accurate"
    pages_per_chunk: int | None = None
    first_pages: int | None = None
    partial_on_deadline: bool = False

    def __post_init__(self) -> None:
        if self.ocr not in _OCR_MODES:
            raise ValueError(f"ocr must be one of {_OCR_MODES}, not {self.ocr!r}")
        if self.table_mode not in _TABLE_MODES:
            raise ValueError(f"table_mode must be one of {_TABLE_MODES}, not {self.table_mode!r}")
        if isinstance(self.ocr_languages, str):
            raise ValueError("ocr_languages must be a sequence of language codes, not a string")
        languages = tuple(str(code).strip() for code in self.ocr_languages)
        if not languages or any(not code for code in languages):
            raise ValueError("ocr_languages must name at least one language code")
        if self.ocr != "never" and languages != ("en",):
            raise ValueError(
                "OCR supports only ('en',); other languages require approved language-specific "
                "model artifacts. Use ocr='never' to read a non-English PDF text layer."
            )
        object.__setattr__(self, "ocr_languages", languages)
        if (
            isinstance(self.max_heading_level, bool)
            or not isinstance(self.max_heading_level, int)
            or not 1 <= self.max_heading_level <= 6
        ):
            raise ValueError("max_heading_level must be an integer from 1 to 6")
        for name in ("pages_per_chunk", "first_pages"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 1
            ):
                raise ValueError(f"{name} must be a positive integer or None")
        if not isinstance(self.partial_on_deadline, bool):
            raise ValueError("partial_on_deadline must be a boolean")

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> PdfConversionOptions:
        """Options from ``SURVEY_SCRIBE_PDF_*`` variables; an unset variable keeps the default.

        ``SURVEY_SCRIBE_PDF_OCR`` (always | auto | never), ``SURVEY_SCRIBE_PDF_OCR_LANGUAGES``
        (comma-separated), ``SURVEY_SCRIBE_PDF_HEADING_LEVELS`` and
        ``SURVEY_SCRIBE_PDF_INCLUDE_FURNITURE`` (1 | true | yes | on),
        ``SURVEY_SCRIBE_PDF_MAX_HEADING_LEVEL`` (1-6), ``SURVEY_SCRIBE_PDF_TABLE_MODE``
        (accurate | fast), ``SURVEY_SCRIBE_PDF_PAGES_PER_CHUNK`` (a positive integer, or 0 for
        one call), ``SURVEY_SCRIBE_PDF_FIRST_PAGES`` (a positive integer),
        ``SURVEY_SCRIBE_PDF_PARTIAL_ON_DEADLINE`` (a boolean).
        """
        env = os.environ if environ is None else environ

        def read(name: str) -> str | None:
            value = env.get(_PDF_ENV_PREFIX + name)
            return value.strip() if value is not None and value.strip() else None

        def flag(name: str, default: bool) -> bool:
            value = read(name)
            if value is None:
                return default
            lowered = value.lower()
            if lowered in ("1", "true", "yes", "on"):
                return True
            if lowered in ("0", "false", "no", "off"):
                return False
            raise ValueError(f"{_PDF_ENV_PREFIX}{name} must be a boolean, not {value!r}")

        defaults = cls()
        languages = read("OCR_LANGUAGES")
        level = read("MAX_HEADING_LEVEL")
        try:
            max_level = int(level) if level is not None else defaults.max_heading_level
        except ValueError:
            raise ValueError(f"{_PDF_ENV_PREFIX}MAX_HEADING_LEVEL must be an integer") from None

        def count(name: str, default: int | None) -> int | None:
            value = read(name)
            if value is None:
                return default
            try:
                return int(value)
            except ValueError:
                raise ValueError(f"{_PDF_ENV_PREFIX}{name} must be an integer") from None

        pages_per_chunk = count("PAGES_PER_CHUNK", defaults.pages_per_chunk)
        return cls(
            ocr=(read("OCR") or defaults.ocr).lower(),
            ocr_languages=(
                tuple(code for code in languages.split(","))
                if languages
                else defaults.ocr_languages
            ),
            heading_levels=flag("HEADING_LEVELS", defaults.heading_levels),
            max_heading_level=max_level,
            include_furniture=flag("INCLUDE_FURNITURE", defaults.include_furniture),
            table_mode=(read("TABLE_MODE") or defaults.table_mode).lower(),
            pages_per_chunk=None if pages_per_chunk == 0 else pages_per_chunk,
            first_pages=count("FIRST_PAGES", defaults.first_pages),
            partial_on_deadline=flag("PARTIAL_ON_DEADLINE", defaults.partial_on_deadline),
        )


def _push_heading(
    path: tuple[tuple[int, str], ...], level: int, text: str
) -> tuple[tuple[int, str], ...]:
    """The section path after a heading of ``level``: its ancestors kept, deeper headings dropped.

    Every heading at level 1 (the layout model's default) gives a path of one title, as before;
    with inferred levels a sub-heading sits under its parent instead of replacing it.
    """
    level = max(int(level), 1)
    while path and path[-1][0] >= level:
        path = path[:-1]
    return (*path, (level, text))


def _docling_blocks(document: Any, *, include_furniture: bool) -> list[PdfConversionBlock]:
    """A converted Docling document's items as ordered blocks, each with its section path.

    Format-neutral: a PDF's items carry pages, a workbook's carry sheets (Docling files each
    sheet as a page), a Word document's carry none.
    """
    return _docling_blocks_after(document, include_furniture=include_furniture)[0]


def _docling_blocks_after(
    document: Any,
    *,
    include_furniture: bool,
    headings: tuple[tuple[int, str], ...] = (),
) -> tuple[list[PdfConversionBlock], tuple[tuple[int, str], ...]]:
    """``_docling_blocks`` continuing from an earlier part's heading path; returns the last one."""
    blocks: list[PdfConversionBlock] = []
    configured_max_cells = os.environ.get("SURVEY_SCRIBE_PDF_MAX_CELLS")
    max_cells = int(configured_max_cells) if configured_max_cells is not None else None
    table_cells = 0
    current_section: tuple[str, ...] = tuple(title for _level, title in headings)
    if include_furniture:
        layers = import_module("docling_core.types.doc").ContentLayer
        items = document.iterate_items(included_content_layers={layers.BODY, layers.FURNITURE})
    else:
        items = document.iterate_items()
    for item, _depth in items:
        pages = _docling_pages(item)
        page = pages[0] if pages else None
        label = str(getattr(item, "label", "")).lower()
        if "table" in label:
            remaining_cells = None if max_cells is None else max(max_cells - table_cells, 0)
            rows = _docling_table_rows(
                item,
                document,
                max_cells=remaining_cells,
            )
            if rows:
                if max_cells is not None:
                    table_cells = _add_table_cells(table_cells, rows, max_cells)
                blocks.append(
                    PdfConversionBlock(
                        text=render_table(rows),
                        page=page,
                        pages=pages,
                        table_rows=rows,
                        section_path=current_section,
                    )
                )
            continue
        text = _normalize_text(str(getattr(item, "text", "")))
        marker = _normalize_text(str(getattr(item, "marker", "") or ""))
        if text and marker and "list" in label:
            # a numbered question is a list item to the layout model and its number is the
            # marker, not the text: keep it, a data column is often named by it (q8, s4q8)
            text = f"{marker} {text}"
        if text:
            if any(name in label for name in ("section", "title", "heading")):
                headings = _push_heading(headings, getattr(item, "level", 1) or 1, text)
                current_section = tuple(title for _level, title in headings)
            blocks.append(
                PdfConversionBlock(
                    text=text,
                    page=page,
                    pages=pages,
                    section_path=current_section,
                )
            )
    return blocks, headings


class DoclingConverter:
    """Lazy Docling converter configured for local PDFium and, by default, full-page OCR."""

    def __init__(self, options: PdfConversionOptions | None = None) -> None:
        self.options = options or PdfConversionOptions()
        self._active: Any | None = None

    def __call__(self, path: str, artifacts_path: str | None) -> PdfConversion:
        with self._session(artifacts_path) as converter:
            result = converter.convert(path)
        return self._conversion(result)[0]

    def convert_pages(
        self,
        path: str,
        artifacts_path: str | None,
        ranges: tuple[PageRange, ...],
    ) -> Iterator[PdfConversion]:
        """Convert range by range with one Docling converter; models load once."""
        with self._session(artifacts_path) as converter:
            headings: tuple[tuple[int, str], ...] = ()
            for page_range in ranges:
                result = converter.convert(path, page_range=page_range)
                conversion, headings = self._conversion(
                    result, headings=headings, page_range=page_range
                )
                yield conversion

    @contextmanager
    def _session(self, artifacts_path: str | None) -> Iterator[Any]:
        """Reuse the built converter while :meth:`opened` is active; build one otherwise."""
        if self._active is not None:
            yield self._active
            return
        with self._document_converter(artifacts_path) as converter:
            yield converter

    @contextmanager
    def opened(self, artifacts_path: str | None) -> Iterator[None]:
        """Build the Docling converter once and reuse it for every call while open."""
        if self._active is not None:
            yield
            return
        with self._document_converter(artifacts_path) as converter:
            self._active = converter
            try:
                yield
            finally:
                self._active = None

    @contextmanager
    def _document_converter(self, artifacts_path: str | None) -> Iterator[Any]:
        options = self.options
        if artifacts_path is None:
            raise SourceDependencyError(
                "PDF OCR artifacts are not configured; set DOCLING_ARTIFACTS_PATH"
            )
        if options.ocr == "never":
            # the layout and table models only: no OCR archive to validate
            try:
                artifact_root = Path(artifacts_path).resolve(strict=True)
            except OSError:
                raise SourceDependencyError(
                    "Configured Docling artifacts directory does not exist"
                ) from None
            if not artifact_root.is_dir():
                raise SourceDependencyError("Configured Docling artifacts path is not a directory")
        else:
            try:
                artifact_root = resolve_ocr_cache(Path(artifacts_path))
            except OcrCacheError as error:
                raise SourceDependencyError(str(error)) from None
        try:
            backend_module = import_module("docling.backend.pypdfium2_backend")
            base_module = import_module("docling.datamodel.base_models")
            pipeline_module = import_module("docling.datamodel.pipeline_options")
            converter_module = import_module("docling.document_converter")
        except ModuleNotFoundError as error:
            raise SourceDependencyError(
                "PDF conversion requires the optional 'pdf' dependencies"
            ) from error

        snapshot: AbstractContextManager[Path | None] = (
            validated_ocr_model_snapshot(artifact_root)
            if options.ocr != "never"
            else nullcontext(None)
        )
        with snapshot as model_root:
            pipeline_options = pipeline_module.PdfPipelineOptions()
            pipeline_options.do_ocr = options.ocr != "never"
            pipeline_options.do_table_structure = True
            pipeline_options.enable_remote_services = False
            pipeline_options.artifacts_path = artifact_root
            if pipeline_options.do_ocr:
                pipeline_options.ocr_options = pipeline_module.EasyOcrOptions(
                    lang=list(options.ocr_languages),
                    force_full_page_ocr=options.ocr == "always",
                    model_storage_directory=str(model_root),
                    download_enabled=False,
                )
            if options.table_mode != "accurate":
                mode = getattr(pipeline_module, "TableFormerMode", None)
                if mode is None:
                    raise SourceDependencyError("Installed Docling has no TableFormer mode option")
                pipeline_options.table_structure_options.mode = mode[options.table_mode.upper()]
            if options.heading_levels:
                hierarchy = getattr(pipeline_module, "HeadingHierarchyOptions", None)
                if hierarchy is None:
                    raise SourceDependencyError(
                        "Installed Docling has no heading-hierarchy stage; upgrade docling or "
                        "leave heading_levels off"
                    )
                pipeline_options.generate_parsed_pages = True
                pipeline_options.heading_hierarchy_options = hierarchy(
                    enabled=True, max_level=options.max_heading_level
                )
            format_option = converter_module.PdfFormatOption(
                pipeline_options=pipeline_options,
                backend=backend_module.PyPdfiumDocumentBackend,
            )
            converter = converter_module.DocumentConverter(
                format_options={base_module.InputFormat.PDF: format_option}
            )
            yield converter

    def _conversion(
        self,
        result: Any,
        *,
        headings: tuple[tuple[int, str], ...] = (),
        page_range: PageRange | None = None,
    ) -> tuple[PdfConversion, tuple[tuple[int, str], ...]]:
        document = result.document
        blocks, headings = _docling_blocks_after(
            document, include_furniture=self.options.include_furniture, headings=headings
        )
        page_count = _docling_page_count(result, document, blocks)
        failed_pages = _docling_failed_pages(result)
        if failed_pages and (page_count == 0 or failed_pages[-1] > page_count):
            raise SourceConversionError("PDF conversion returned invalid failed-page metadata")
        if _docling_conversion_incomplete(result) and not failed_pages:
            raise SourceConversionError("PDF conversion was incomplete without page coverage")
        coverage = None
        diagnostics: tuple[SourceDiagnostic, ...] = ()
        if page_count:
            failed = set(failed_pages)
            first, last = page_range or (1, page_count)
            converted = tuple(
                page for page in range(first, min(last, page_count) + 1) if page not in failed
            )
            converted_set = set(converted)
            coverage = SourceCoverage(
                unit="page",
                total_units=page_count,
                converted_units=converted,
                failed_units=tuple(
                    page for page in range(1, page_count + 1) if page not in converted_set
                ),
            )
            diagnostics = tuple(
                SourceDiagnostic(
                    code="PDF_PAGE_CONVERSION_FAILED",
                    message="PDF page conversion failed",
                    unit="page",
                    unit_index=page,
                )
                for page in failed_pages
            )
        conversion = PdfConversion(
            page_count=page_count,
            blocks=tuple(blocks),
            coverage=coverage,
            diagnostics=diagnostics,
        )
        return conversion, headings


class _PdfRunner(Protocol):
    """How a Docling adapter runs a conversion: in a fresh process, a reused worker, or here.

    ``run_single`` and ``run_ranges`` match the module ``_run_pdf_worker`` and
    ``_run_pdf_range_worker`` contracts so the adapter is isolation-mode agnostic. ``close``
    releases any long-lived worker.
    """

    def run_single(
        self,
        converter: PdfConverter,
        path: Path,
        *,
        artifacts_path: str | None,
        timeout: float,
        max_cells: int | None = None,
        kind: str = "PDF",
    ) -> PdfConversion:
        """Convert one document and return its serializable conversion."""
        ...

    def run_ranges(
        self,
        converter: PdfPageRangeConverter,
        path: Path,
        *,
        artifacts_path: str | None,
        ranges: tuple[PageRange, ...],
        timeout: float,
        max_cells: int | None,
        partial_on_deadline: bool,
        progress: SourceProgress | None,
    ) -> tuple[list[tuple[PageRange, PdfConversion]], bool]:
        """Convert ``ranges`` and return the finished ranges and whether time ran out."""
        ...

    def close(self) -> None:
        """Release any long-lived worker this runner owns."""
        ...


class _ProcessRunner:
    """Spawn one fresh killable worker per document (the established behaviour)."""

    def __init__(self, *, block_network: bool) -> None:
        self._block_network = block_network

    def run_single(
        self,
        converter: PdfConverter,
        path: Path,
        *,
        artifacts_path: str | None,
        timeout: float,
        max_cells: int | None = None,
        kind: str = "PDF",
    ) -> PdfConversion:
        return _run_pdf_worker(
            converter,
            path,
            artifacts_path=artifacts_path,
            timeout=timeout,
            max_cells=max_cells,
            kind=kind,
            block_network=self._block_network,
        )

    def run_ranges(
        self,
        converter: PdfPageRangeConverter,
        path: Path,
        *,
        artifacts_path: str | None,
        ranges: tuple[PageRange, ...],
        timeout: float,
        max_cells: int | None,
        partial_on_deadline: bool,
        progress: SourceProgress | None,
    ) -> tuple[list[tuple[PageRange, PdfConversion]], bool]:
        return _run_pdf_range_worker(
            converter,
            path,
            artifacts_path=artifacts_path,
            ranges=ranges,
            timeout=timeout,
            max_cells=max_cells,
            partial_on_deadline=partial_on_deadline,
            progress=progress,
            block_network=self._block_network,
        )

    def close(self) -> None:
        return None


class _InProcessRunner:
    """Run the conversion directly in the calling process, with no child and no socket patch.

    For a container that is itself the disposable sandbox: there is no worker to kill, so the
    deadline is cooperative (checked between page ranges) and otherwise the container deadline
    is the kill switch.
    """

    def run_single(
        self,
        converter: PdfConverter,
        path: Path,
        *,
        artifacts_path: str | None,
        timeout: float,
        max_cells: int | None = None,
        kind: str = "PDF",
    ) -> PdfConversion:
        del timeout, kind
        conversion = converter(str(path), artifacts_path)
        if max_cells is not None:
            _validate_pdf_table_cells(conversion, max_cells)
        return conversion

    def run_ranges(
        self,
        converter: PdfPageRangeConverter,
        path: Path,
        *,
        artifacts_path: str | None,
        ranges: tuple[PageRange, ...],
        timeout: float,
        max_cells: int | None,
        partial_on_deadline: bool,
        progress: SourceProgress | None,
    ) -> tuple[list[tuple[PageRange, PdfConversion]], bool]:
        stop = time.monotonic() + timeout
        total = sum(last - first + 1 for first, last in ranges)
        chunks: list[tuple[PageRange, PdfConversion]] = []
        cells = 0
        for conversion in converter.convert_pages(str(path), artifacts_path, ranges):
            if len(chunks) == len(ranges):
                raise SourceConversionError("PDF converter returned more ranges than requested")
            if max_cells is not None:
                for block in conversion.blocks:
                    if block.table_rows:
                        cells = _add_table_cells(cells, block.table_rows, max_cells)
            chunks.append((ranges[len(chunks)], conversion))
            if progress is not None:
                progress(sum(last - first + 1 for (first, last), _ in chunks), total)
            if len(chunks) < len(ranges) and time.monotonic() >= stop:
                if partial_on_deadline:
                    return chunks, True
                raise SourceTimeoutError("PDF conversion exceeded the configured deadline")
        if len(chunks) != len(ranges):
            raise SourceConversionError("PDF converter returned fewer ranges than requested")
        return chunks, False

    def close(self) -> None:
        return None


class _WorkerRunner:
    """Keep one long-lived spawned worker, loading models once and streaming documents through.

    Access is serialized: one worker converts one document at a time. The worker is killed and
    forgotten on a deadline (the next call starts a fresh one) and on ``close()``. A converter
    error leaves the worker alive and reusable.
    """

    def __init__(self, *, block_network: bool) -> None:
        self._block_network = block_network
        self._context = get_context("spawn")
        self._lock = threading.Lock()
        self._process: Any | None = None
        self._requests: Any | None = None
        self._responses: Any | None = None
        self._converter: PdfConverter | None = None

    def _ensure_started(self, converter: PdfConverter) -> None:
        if self._process is not None and self._process.is_alive() and self._converter is converter:
            return
        self._shutdown()
        self._converter = converter
        self._requests = self._context.Queue()
        self._responses = self._context.Queue(maxsize=1)
        process = self._context.Process(
            target=_persistent_pdf_worker,
            args=(converter, self._block_network, self._requests, self._responses),
        )
        process.daemon = True
        process.start()
        self._process = process

    def _kill(self) -> None:
        if self._process is not None:
            _bounded_process_cleanup(self._process)
        self._discard()

    def _discard(self) -> None:
        for queue in (self._requests, self._responses):
            if queue is not None:
                queue.close()
                queue.join_thread()
        self._process = None
        self._requests = None
        self._responses = None
        self._converter = None

    def _shutdown(self) -> None:
        if self._process is None:
            return
        if self._process.is_alive() and self._requests is not None:
            with suppress(ValueError, OSError):
                self._requests.put(None)
        _bounded_process_cleanup(self._process)
        self._discard()

    def run_single(
        self,
        converter: PdfConverter,
        path: Path,
        *,
        artifacts_path: str | None,
        timeout: float,
        max_cells: int | None = None,
        kind: str = "PDF",
    ) -> PdfConversion:
        with self._lock:
            self._ensure_started(converter)
            process = self._process
            responses = self._responses
            assert process is not None and responses is not None and self._requests is not None
            self._requests.put(("single", str(path), artifacts_path, max_cells, None))
            try:
                status, code, payload = _wait_for_worker_message(responses, process, timeout)
            except Empty:
                self._kill()
                raise SourceTimeoutError(
                    f"{kind} conversion exceeded the configured deadline"
                ) from None
            except ChildProcessError:
                note = _exit_note(process)
                self._kill()
                raise SourceConversionError(
                    f"{kind} conversion worker exited before returning a result{note}"
                ) from None
            if status == "ok" and isinstance(payload, PdfConversion):
                if max_cells is not None:
                    _validate_pdf_table_cells(payload, max_cells)
                return payload
            raise _worker_error(code, payload, kind)

    def run_ranges(
        self,
        converter: PdfPageRangeConverter,
        path: Path,
        *,
        artifacts_path: str | None,
        ranges: tuple[PageRange, ...],
        timeout: float,
        max_cells: int | None,
        partial_on_deadline: bool,
        progress: SourceProgress | None,
    ) -> tuple[list[tuple[PageRange, PdfConversion]], bool]:
        with self._lock:
            self._ensure_started(converter)
            process = self._process
            responses = self._responses
            assert process is not None and responses is not None and self._requests is not None
            stop = time.monotonic() + timeout
            total = sum(last - first + 1 for first, last in ranges)
            self._requests.put(("ranges", str(path), artifacts_path, max_cells, ranges))
            chunks: list[tuple[PageRange, PdfConversion]] = []
            cells = 0
            while True:
                try:
                    remaining = stop - time.monotonic()
                    if remaining <= 0:
                        raise Empty
                    status, code, payload = _wait_for_worker_message(responses, process, remaining)
                except Empty:
                    self._kill()
                    if partial_on_deadline and chunks:
                        return chunks, True
                    raise SourceTimeoutError(
                        "PDF conversion exceeded the configured deadline"
                    ) from None
                except ChildProcessError:
                    note = _exit_note(process)
                    self._kill()
                    raise SourceConversionError(
                        f"PDF conversion worker exited before returning a result{note}"
                    ) from None
                if (
                    status == "chunk"
                    and isinstance(payload, PdfConversion)
                    and len(chunks) < len(ranges)
                ):
                    try:
                        if max_cells is not None:
                            for block in payload.blocks:
                                if block.table_rows:
                                    cells = _add_table_cells(cells, block.table_rows, max_cells)
                        chunks.append((ranges[len(chunks)], payload))
                        if progress is not None:
                            progress(sum(last - first + 1 for (first, last), _ in chunks), total)
                    except BaseException:
                        # Pending responses must not reach the next document after an abort.
                        self._kill()
                        raise
                    continue
                if status == "done" and len(chunks) == len(ranges):
                    return chunks, False
                raise _worker_error(code, payload, "PDF")

    def close(self) -> None:
        with self._lock:
            self._shutdown()


def _make_pdf_runner(isolation: IsolationMode, *, block_network: bool) -> _PdfRunner:
    if isolation == "process":
        return _ProcessRunner(block_network=block_network)
    if isolation == "worker":
        return _WorkerRunner(block_network=block_network)
    if isolation == "inprocess":
        return _InProcessRunner()
    raise ValueError(f"isolation must be one of {_ISOLATION_MODES}, not {isolation!r}")


def _persistent_pdf_worker(
    converter: PdfConverter,
    block_network: bool,
    jobs: Any,
    responses: Any,
) -> None:
    """One long-lived worker: load the models once, then convert each requested document."""
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    with ExitStack() as stack:
        if block_network:
            stack.enter_context(_blocked_network())
        opened = False
        while True:
            try:
                job = jobs.get()
            except (EOFError, OSError):
                return
            if job is None:
                return
            _kind, path, artifacts_path, max_cells, ranges = job
            if artifacts_path is not None:
                os.environ["DOCLING_ARTIFACTS_PATH"] = artifacts_path
            if max_cells is not None:
                os.environ["SURVEY_SCRIBE_PDF_MAX_CELLS"] = str(max_cells)
            else:
                os.environ.pop("SURVEY_SCRIBE_PDF_MAX_CELLS", None)
            try:
                if not opened and isinstance(converter, PersistentPdfConverter):
                    stack.enter_context(converter.opened(artifacts_path))
                    opened = True
                if ranges is not None:
                    _pdf_range_worker(
                        cast("PdfPageRangeConverter", converter),
                        path,
                        artifacts_path,
                        max_cells,
                        responses,
                        ranges,
                    )
                    continue
                conversion = converter(path, artifacts_path)
                if max_cells is not None:
                    _validate_pdf_table_cells(conversion, max_cells)
                responses.put(("ok", "", conversion))
            except SourceError as error:
                responses.put(("error", error.code, _bounded_text(str(error))))
            except BaseException as error:  # noqa: BLE001 - the untrusted worker's last line
                responses.put(("error", SourceConversionError.code, _error_detail(error)))


class DoclingPdfAdapter:
    """Normalize a local PDF in a fresh killable, network-disabled process.

    One ``SourceLimits.deadline_seconds`` deadline covers the preflight inspection and the
    conversion together. When ``options.pages_per_chunk`` or ``options.first_pages`` is set and
    the converter reads page ranges (``DoclingConverter`` does), the PDF is converted range by
    range: ``progress(pages_done, pages_total)`` is called in this process after each range,
    and with ``options.partial_on_deadline`` the finished pages are returned when the deadline
    is reached. Otherwise the PDF is converted in one call and ``progress`` is called once.

    ``isolation`` chooses how the conversion runs: ``"process"`` (the default) spawns a fresh
    worker per document, ``"worker"`` reuses one long-lived worker that loads the models once,
    and ``"inprocess"`` runs it here with no child. ``block_network`` denies the worker's
    sockets in the ``"process"`` and ``"worker"`` modes; ``"inprocess"`` never patches the host
    process's sockets. Call ``close()`` to release a long-lived worker.
    """

    def __init__(
        self,
        *,
        converter: PdfConverter | None = None,
        artifacts_path: str | os.PathLike[str] | None = None,
        options: PdfConversionOptions | None = None,
        progress: SourceProgress | None = None,
        isolation: IsolationMode = "process",
        block_network: bool = True,
    ) -> None:
        if isolation not in _ISOLATION_MODES:
            raise ValueError(f"isolation must be one of {_ISOLATION_MODES}, not {isolation!r}")
        if not isinstance(block_network, bool):
            raise ValueError("block_network must be a boolean")
        self._converter = converter or DoclingConverter(options)
        self._options = options or PdfConversionOptions()
        self._progress = progress
        self._isolation = isolation
        self._runner = _make_pdf_runner(isolation, block_network=block_network)
        configured = (
            os.environ.get("DOCLING_ARTIFACTS_PATH") if artifacts_path is None else artifacts_path
        )
        self._artifacts_path = os.fspath(configured) if configured is not None else None

    def close(self) -> None:
        """Release the long-lived worker, if the ``"worker"`` isolation mode holds one."""
        self._runner.close()

    def convert(self, source: ResolvedSource, *, limits: SourceLimits) -> SourceDocument:
        return self._convert(source, limits=limits, progress=self._progress)

    def convert_with_progress(
        self,
        source: ResolvedSource,
        *,
        limits: SourceLimits,
        progress: SourceProgress,
    ) -> SourceDocument:
        """Normalize a PDF, calling ``progress(pages_done, pages_total)`` after each range."""
        return self._convert(source, limits=limits, progress=progress)

    def _convert(
        self,
        source: ResolvedSource,
        *,
        limits: SourceLimits,
        progress: SourceProgress | None,
    ) -> SourceDocument:
        deadline = time.monotonic() + limits.deadline_seconds
        page_count = _inspect_pdf(
            source.primary,
            limits,
            timeout=_remaining_deadline(deadline),
            in_process=self._isolation == "inprocess",
        )
        by_range = (
            self._options.pages_per_chunk is not None or self._options.first_pages is not None
        )
        if by_range and page_count and isinstance(self._converter, PdfPageRangeConverter):
            return self._convert_ranges(
                source,
                limits=limits,
                deadline=deadline,
                page_count=page_count,
                progress=progress,
            )
        conversion = self._runner.run_single(
            self._converter,
            source.primary,
            artifacts_path=self._artifacts_path,
            timeout=_remaining_deadline(deadline),
            max_cells=limits.max_cells,
        )
        if progress is not None and page_count:
            progress(page_count, page_count)
        effective_page_count = max(page_count, conversion.page_count)
        if effective_page_count > limits.max_pages:
            raise SourceLimitError("max_pages", "PDF exceeds the configured page limit")

        for converted in conversion.blocks:
            if converted.pages and converted.pages[-1] > limits.max_pages:
                raise SourceLimitError("max_pages", "PDF block exceeds the configured page limit")
            if converted.pages and converted.pages[-1] > effective_page_count:
                raise SourceConversionError("PDF block provenance exceeds the converted page count")
        blocks = _source_blocks(conversion.blocks, source.primary.name)
        coverage = conversion.coverage
        if coverage is not None:
            if coverage.unit != "page" or coverage.total_units != effective_page_count:
                raise SourceConversionError("PDF conversion coverage does not match its page count")
        elif effective_page_count:
            coverage = SourceCoverage(
                unit="page",
                total_units=effective_page_count,
                converted_units=tuple(range(1, effective_page_count + 1)),
            )
        else:
            coverage = SourceCoverage()
        return SourceDocument(
            source_name=source.primary.name,
            media_type="application/pdf",
            blocks=tuple(blocks),
            coverage=coverage,
            diagnostics=conversion.diagnostics,
        )

    def _convert_ranges(
        self,
        source: ResolvedSource,
        *,
        limits: SourceLimits,
        deadline: float,
        page_count: int,
        progress: SourceProgress | None,
    ) -> SourceDocument:
        options = self._options
        target = min(page_count, options.first_pages or page_count)
        chunks, timed_out = self._runner.run_ranges(
            cast("PdfPageRangeConverter", self._converter),
            source.primary,
            artifacts_path=self._artifacts_path,
            ranges=_page_ranges(target, options.pages_per_chunk),
            timeout=_remaining_deadline(deadline),
            max_cells=limits.max_cells,
            partial_on_deadline=options.partial_on_deadline,
            progress=progress,
        )
        effective_page_count = max([page_count, *(chunk.page_count for _range, chunk in chunks)])
        if effective_page_count > limits.max_pages:
            raise SourceLimitError("max_pages", "PDF exceeds the configured page limit")

        converted_blocks: list[PdfConversionBlock] = []
        diagnostics: list[SourceDiagnostic] = []
        converted: set[int] = set()
        attempted = 0
        for (first, last), chunk in chunks:
            for block in chunk.blocks:
                if block.pages and block.pages[-1] > limits.max_pages:
                    raise SourceLimitError(
                        "max_pages", "PDF block exceeds the configured page limit"
                    )
                if block.pages and block.pages[-1] > effective_page_count:
                    raise SourceConversionError(
                        "PDF block provenance exceeds the converted page count"
                    )
            if chunk.coverage is None:
                converted.update(range(first, last + 1))
            elif (
                chunk.coverage.unit != "page" or chunk.coverage.total_units != effective_page_count
            ):
                raise SourceConversionError("PDF conversion coverage does not match its page count")
            else:
                converted.update(
                    page for page in chunk.coverage.converted_units if first <= page <= last
                )
            attempted += last - first + 1
            converted_blocks.extend(chunk.blocks)
            diagnostics.extend(chunk.diagnostics)
        _validate_pdf_table_cells(
            PdfConversion(page_count=effective_page_count, blocks=tuple(converted_blocks)),
            limits.max_cells,
        )

        if timed_out:
            diagnostics.append(
                SourceDiagnostic(
                    code="PDF_DEADLINE_PARTIAL",
                    message=(
                        f"PDF conversion reached the deadline after {attempted} of {target} "
                        "pages; the remaining pages were not converted"
                    ),
                    severity="warning",
                )
            )
        if target < page_count:
            diagnostics.append(
                SourceDiagnostic(
                    code="PDF_FIRST_PAGES",
                    message=f"Only the first {target} of {page_count} PDF pages were requested",
                    severity="warning",
                )
            )
        failed = tuple(page for page in range(1, effective_page_count + 1) if page not in converted)
        reported = {
            diagnostic.unit_index
            for diagnostic in diagnostics
            if diagnostic.severity == "error" and diagnostic.unit == "page"
        }
        diagnostics.extend(
            SourceDiagnostic(
                code="PDF_PAGE_NOT_CONVERTED",
                message="PDF page was not converted",
                unit="page",
                unit_index=page,
            )
            for page in failed
            if page not in reported
        )
        return SourceDocument(
            source_name=source.primary.name,
            media_type="application/pdf",
            blocks=tuple(_source_blocks(converted_blocks, source.primary.name)),
            coverage=SourceCoverage(
                unit="page",
                total_units=effective_page_count,
                converted_units=tuple(sorted(converted)),
                failed_units=failed,
            ),
            diagnostics=tuple(diagnostics),
        )


def _page_ranges(page_count: int, pages_per_chunk: int | None) -> tuple[PageRange, ...]:
    step = pages_per_chunk or page_count
    return tuple(
        (first, min(first + step - 1, page_count)) for first in range(1, page_count + 1, step)
    )


_OFFICE_FORMATS = {
    # suffix: (Docling input format, media type, coverage unit of a Docling page)
    "doc": ("DOC", "application/msword", "document"),
    "xls": ("XLS", "application/vnd.ms-excel", "sheet"),
}
_OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


@dataclass(frozen=True, slots=True)
class DoclingOfficeConverter:
    """Docling's Word or Excel pipeline over a legacy binary Office file (``.doc``, ``.xls``).

    Docling converts the file to its Open XML form with LibreOffice, then parses it; no model
    runs. Pickle-safe, so it crosses the spawned worker boundary like the PDF converter.
    """

    suffix: str
    include_furniture: bool = False

    def __post_init__(self) -> None:
        if self.suffix not in _OFFICE_FORMATS:
            raise ValueError(f"suffix must be one of {tuple(_OFFICE_FORMATS)}, not {self.suffix!r}")

    def __call__(self, path: str, artifacts_path: str | None) -> PdfConversion:
        del artifacts_path  # Docling's Word and Excel pipelines use no models
        if not libreoffice_command():
            raise SourceDependencyError(
                f"Converting a .{self.suffix} file needs LibreOffice: install it and put "
                "`soffice` on PATH"
            )
        try:
            base_module = import_module("docling.datamodel.base_models")
            converter_module = import_module("docling.document_converter")
        except ModuleNotFoundError as error:
            raise SourceDependencyError(
                f".{self.suffix} conversion requires the optional 'pdf' dependencies"
            ) from error
        input_format = getattr(base_module.InputFormat, _OFFICE_FORMATS[self.suffix][0])
        converter = converter_module.DocumentConverter(allowed_formats=[input_format])
        result = converter.convert(path)
        if _docling_conversion_incomplete(result):
            raise SourceConversionError(f".{self.suffix} conversion was incomplete")
        document = result.document
        blocks = _docling_blocks(document, include_furniture=self.include_furniture)
        return PdfConversion(
            page_count=_docling_page_count(result, document, blocks),
            blocks=tuple(blocks),
        )


def libreoffice_command() -> str | None:
    """The LibreOffice executable Docling converts legacy Office files with: on PATH, as Docling
    looks it up (``libreoffice``, then ``soffice``)."""
    return shutil.which("libreoffice") or shutil.which("soffice")


class DoclingOfficeAdapter:
    """Normalize a legacy binary Office file (``.doc``, ``.xls``) through Docling, in a fresh
    killable, network-disabled process."""

    def __init__(
        self,
        suffix: str,
        *,
        converter: PdfConverter | None = None,
        options: PdfConversionOptions | None = None,
        isolation: IsolationMode = "process",
        block_network: bool = True,
    ) -> None:
        if isolation not in _ISOLATION_MODES:
            raise ValueError(f"isolation must be one of {_ISOLATION_MODES}, not {isolation!r}")
        if not isinstance(block_network, bool):
            raise ValueError("block_network must be a boolean")
        include_furniture = options.include_furniture if options is not None else False
        self._suffix = suffix
        self._converter = converter or DoclingOfficeConverter(suffix, include_furniture)
        self._runner = _make_pdf_runner(isolation, block_network=block_network)

    def close(self) -> None:
        """Release the long-lived worker, if the ``"worker"`` isolation mode holds one."""
        self._runner.close()

    def convert(self, source: ResolvedSource, *, limits: SourceLimits) -> SourceDocument:
        deadline = time.monotonic() + limits.deadline_seconds
        _inspect_ole(source.primary, self._suffix)
        conversion = self._runner.run_single(
            self._converter,
            source.primary,
            artifacts_path=None,
            timeout=_remaining_deadline(deadline),
            max_cells=limits.max_cells,
            kind=f".{self._suffix}",
        )
        _format, media_type, unit = _OFFICE_FORMATS[self._suffix]
        units = conversion.page_count if unit == "sheet" else 0
        return SourceDocument(
            source_name=source.primary.name,
            media_type=media_type,
            blocks=tuple(_source_blocks(conversion.blocks, source.primary.name)),
            coverage=(
                SourceCoverage(
                    unit="sheet",
                    total_units=units,
                    converted_units=tuple(range(1, units + 1)),
                )
                if units
                else SourceCoverage()
            ),
            diagnostics=conversion.diagnostics,
        )


def _inspect_ole(path: Path, suffix: str) -> None:
    try:
        with path.open("rb") as stream:
            signature = stream.read(len(_OLE_SIGNATURE))
    except OSError as error:
        raise SourceConversionError(f".{suffix} source could not be inspected") from error
    if signature != _OLE_SIGNATURE:
        raise SourceFormatError(f"{suffix.upper()} extension does not match file content")


def _source_blocks(
    converted_blocks: Iterable[PdfConversionBlock], source_name: str
) -> list[SourceBlock]:
    """Docling's converted blocks as source blocks, a table with its rows, empty blocks dropped."""
    blocks: list[SourceBlock] = []
    table_index = 0
    for converted in converted_blocks:
        provenance = SourceProvenance(
            source_name=source_name,
            page=converted.page,
            pages=converted.pages,
            section_path=converted.section_path,
        )
        table: SourceTable | None = None
        kind = "text"
        if converted.table_rows:
            table_index += 1
            table = SourceTable(
                id=f"table-{table_index:06d}",
                rows=converted.table_rows,
                provenance=provenance,
            )
            kind = "table"
        text = (
            render_table(converted.table_rows) if converted.table_rows else converted.text.strip()
        )
        if not text:
            continue
        blocks.append(
            SourceBlock(
                id=f"block-{len(blocks) + 1:06d}",
                order=len(blocks),
                kind=kind,
                text=text,
                provenance=provenance,
                table=table,
            )
        )
    return blocks


class DocxAdapter:
    """Parse DOCX XML as inert text after strict archive inspection."""

    def convert(self, source: ResolvedSource, *, limits: SourceLimits) -> SourceDocument:
        deadline = time.monotonic() + limits.deadline_seconds
        entries = inspect_zip_archive(source.primary, limits, deadline=deadline)
        _remaining_deadline(deadline)
        names = {entry.filename.replace("\\", "/").lower() for entry in entries}
        if any(name.endswith("vbaproject.bin") or "macrosheets/" in name for name in names):
            raise SourceSecurityError("DOCX macro content is prohibited")
        try:
            with zipfile.ZipFile(source.primary) as archive:
                _inspect_docx_content_types(archive, names, limits, deadline)
                stripped_links = _inspect_relationships(archive, names, limits, deadline)
                document_xml = _read_zip_part(
                    archive,
                    "word/document.xml",
                    limits=limits,
                    deadline=deadline,
                )
        except KeyError as error:
            raise SourceFormatError("DOCX is missing word/document.xml") from error
        except (OSError, zipfile.BadZipFile, RuntimeError) as error:
            raise SourceFormatError("DOCX archive could not be read") from error

        try:
            root = _parse_bounded_xml(
                document_xml,
                limits=limits,
                deadline=deadline,
                malformed_message="DOCX document XML is malformed",
            )
        except ElementTree.ParseError as error:
            raise SourceFormatError("DOCX document XML is malformed") from error
        body = root.find(f"{{{_WORD_NAMESPACE}}}body")
        if body is None:
            raise SourceFormatError("DOCX document body is missing")

        blocks: list[SourceBlock] = []
        table_index = 0
        table_cells = 0
        current_section: tuple[str, ...] = ()
        word_blocks, unsupported_containers = _word_body_blocks(body)
        for child in word_blocks:
            _remaining_deadline(deadline)
            if child.tag == f"{{{_WORD_NAMESPACE}}}p":
                text = _word_text(child)
                if text:
                    if _word_is_heading(child):
                        current_section = (text,)
                    blocks.append(
                        _text_block(
                            source.primary.name,
                            len(blocks),
                            text,
                            section_path=current_section,
                        )
                    )
            else:
                rows = _word_table_rows(child)
                if not rows:
                    continue
                table_cells = _add_table_cells(table_cells, rows, limits.max_cells)
                table_index += 1
                provenance = SourceProvenance(
                    source_name=source.primary.name,
                    section_path=current_section,
                    row_start=1,
                    row_end=len(rows),
                )
                table = SourceTable(id=f"table-{table_index:06d}", rows=rows, provenance=provenance)
                blocks.append(
                    SourceBlock(
                        id=f"block-{len(blocks) + 1:06d}",
                        order=len(blocks),
                        kind="table",
                        text=render_table(rows),
                        provenance=provenance,
                        table=table,
                    )
                )
        diagnostics = tuple(
            SourceDiagnostic(
                code="DOCX_CONTAINER_UNSUPPORTED",
                message="DOCX contains a nonempty unsupported document container",
                unit="document",
                unit_index=1,
            )
            for _ in range(unsupported_containers)
        )
        if stripped_links:
            diagnostics += (external_links_stripped_diagnostic(stripped_links, "DOCX"),)
        coverage = (
            SourceCoverage(total_units=1, converted_units=(), failed_units=(1,))
            if unsupported_containers
            else SourceCoverage()
        )
        return SourceDocument(
            source_name=source.primary.name,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            blocks=tuple(blocks),
            coverage=coverage,
            diagnostics=diagnostics,
        )


class HtmlAdapter:
    """Normalize visible HTML text and tables without loading active resources."""

    def convert(self, source: ResolvedSource, *, limits: SourceLimits) -> SourceDocument:
        deadline = time.monotonic() + limits.deadline_seconds
        parser = _SafeHtmlParser(max_cells=limits.max_cells)
        try:
            parser.feed(read_utf8_text(source.primary))
            parser.close()
        except (ElementTree.ParseError, ValueError) as error:
            raise SourceFormatError("HTML source could not be parsed") from error
        _remaining_deadline(deadline)
        blocks = _events_to_blocks(
            source.primary.name,
            parser.events,
            max_cells=limits.max_cells,
        )
        return SourceDocument(
            source_name=source.primary.name,
            media_type="text/html",
            blocks=blocks,
        )


class MarkdownAdapter:
    """Normalize UTF-8 Markdown while preserving preamble and complete tables."""

    def convert(self, source: ResolvedSource, *, limits: SourceLimits) -> SourceDocument:
        deadline = time.monotonic() + limits.deadline_seconds
        events = _markdown_events(read_utf8_text(source.primary), max_cells=limits.max_cells)
        _remaining_deadline(deadline)
        return SourceDocument(
            source_name=source.primary.name,
            media_type="text/markdown",
            blocks=_events_to_blocks(source.primary.name, events, max_cells=limits.max_cells),
        )


class TextAdapter:
    """Normalize local UTF-8 text without interpreting its instructions."""

    def convert(self, source: ResolvedSource, *, limits: SourceLimits) -> SourceDocument:
        deadline = time.monotonic() + limits.deadline_seconds
        text = read_utf8_text(source.primary)
        paragraphs = tuple(
            part.strip() for part in re.split(r"\r?\n\s*\r?\n", text) if part.strip()
        )
        _remaining_deadline(deadline)
        blocks: list[SourceBlock] = []
        current_section: tuple[str, ...] = ()
        for paragraph in paragraphs:
            if _plain_text_heading(paragraph):
                current_section = (paragraph.strip(),)
            blocks.append(
                _text_block(
                    source.primary.name,
                    len(blocks),
                    paragraph,
                    section_path=current_section,
                )
            )
        return SourceDocument(
            source_name=source.primary.name,
            media_type="text/plain",
            blocks=tuple(blocks),
        )


def _run_pdf_worker(
    converter: PdfConverter,
    path: Path,
    *,
    artifacts_path: str | None,
    timeout: float,
    max_cells: int | None = None,
    kind: str = "PDF",
    block_network: bool = True,
) -> PdfConversion:
    context = get_context("spawn")
    output = context.Queue(maxsize=1)
    process = context.Process(
        target=_pdf_worker,
        args=(converter, str(path), artifacts_path, max_cells, output, None, block_network),
    )
    try:
        process.start()
        try:
            status, code, payload = _wait_for_worker_message(output, process, timeout)
        except Empty:
            _bounded_process_cleanup(process)
            raise SourceTimeoutError(
                f"{kind} conversion exceeded the configured deadline"
            ) from None
        except ChildProcessError:
            _bounded_process_cleanup(process)
            raise SourceConversionError(
                f"{kind} conversion worker exited before returning a result{_exit_note(process)}"
            ) from None
        _bounded_process_cleanup(process)
        if status == "ok" and isinstance(payload, PdfConversion):
            if max_cells is not None:
                _validate_pdf_table_cells(payload, max_cells)
            return payload
        raise _worker_error(code, payload, kind)
    except (KeyboardInterrupt, SystemExit):
        _bounded_process_cleanup(process)
        raise
    finally:
        output.close()
        output.join_thread()


def _worker_error(code: object, payload: object, kind: str) -> SourceError:
    message = str(payload)
    if code == SourceDependencyError.code:
        return SourceDependencyError(message)
    if code == SourceSecurityError.code:
        return SourceSecurityError(message)
    if code == SourceLimitError.code:
        return SourceLimitError("max_cells", message)
    if code == SourceFormatError.code:
        return SourceFormatError(message)
    if code == SourceTimeoutError.code:
        return SourceTimeoutError(message)
    return SourceConversionError(
        f"{kind} conversion failed in the isolated worker", detail=message or None
    )


def _run_pdf_range_worker(
    converter: PdfPageRangeConverter,
    path: Path,
    *,
    artifacts_path: str | None,
    ranges: tuple[PageRange, ...],
    timeout: float,
    max_cells: int | None,
    partial_on_deadline: bool,
    progress: SourceProgress | None,
    block_network: bool = True,
) -> tuple[list[tuple[PageRange, PdfConversion]], bool]:
    """Convert ``ranges`` in one worker; return the finished ranges and whether time ran out.

    The worker sends one message per finished range, so the ranges converted before the
    deadline survive the worker being killed.
    """
    stop = time.monotonic() + timeout
    total = sum(last - first + 1 for first, last in ranges)
    context = get_context("spawn")
    output = context.Queue(maxsize=1)
    process = context.Process(
        target=_pdf_worker,
        args=(converter, str(path), artifacts_path, max_cells, output, ranges, block_network),
    )
    chunks: list[tuple[PageRange, PdfConversion]] = []
    cells = 0
    try:
        process.start()
        while True:
            try:
                remaining = stop - time.monotonic()
                if remaining <= 0:
                    raise Empty
                status, code, payload = _wait_for_worker_message(output, process, remaining)
            except Empty:
                _bounded_process_cleanup(process)
                if partial_on_deadline and chunks:
                    return chunks, True
                raise SourceTimeoutError(
                    "PDF conversion exceeded the configured deadline"
                ) from None
            except ChildProcessError:
                _bounded_process_cleanup(process)
                raise SourceConversionError(
                    f"PDF conversion worker exited before returning a result{_exit_note(process)}"
                ) from None
            if (
                status == "chunk"
                and isinstance(payload, PdfConversion)
                and len(chunks) < len(ranges)
            ):
                if max_cells is not None:
                    for block in payload.blocks:
                        if block.table_rows:
                            cells = _add_table_cells(cells, block.table_rows, max_cells)
                chunks.append((ranges[len(chunks)], payload))
                if progress is not None:
                    progress(sum(last - first + 1 for (first, last), _ in chunks), total)
                continue
            _bounded_process_cleanup(process)
            if status == "done" and len(chunks) == len(ranges):
                return chunks, False
            raise _worker_error(code, payload, "PDF")
    except BaseException:
        if process.pid is not None:
            _bounded_process_cleanup(process)
        raise
    finally:
        output.close()
        output.join_thread()


def _pdf_worker(
    converter: PdfConverter,
    path: str,
    artifacts_path: str | None,
    max_cells: int | None,
    output: Any,
    ranges: tuple[PageRange, ...] | None = None,
    block_network: bool = True,
) -> None:
    if artifacts_path is not None:
        os.environ["DOCLING_ARTIFACTS_PATH"] = artifacts_path
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    if max_cells is not None:
        os.environ["SURVEY_SCRIBE_PDF_MAX_CELLS"] = str(max_cells)
    try:
        with _blocked_network() if block_network else nullcontext():
            if ranges is not None:
                _pdf_range_worker(
                    cast(PdfPageRangeConverter, converter),
                    path,
                    artifacts_path,
                    max_cells,
                    output,
                    ranges,
                )
                return
            conversion = converter(path, artifacts_path)
        if max_cells is not None:
            _validate_pdf_table_cells(conversion, max_cells)
        output.put(("ok", "", conversion))
    except SourceError as error:
        output.put(("error", error.code, _bounded_text(str(error))))
    except BaseException as error:
        output.put(("error", SourceConversionError.code, _error_detail(error)))


def _pdf_range_worker(
    converter: PdfPageRangeConverter,
    path: str,
    artifacts_path: str | None,
    max_cells: int | None,
    output: Any,
    ranges: tuple[PageRange, ...],
) -> None:
    cells = 0
    sent = 0
    for conversion in converter.convert_pages(path, artifacts_path, ranges):
        if sent == len(ranges):
            raise SourceConversionError("PDF converter returned more ranges than requested")
        if max_cells is not None:
            for block in conversion.blocks:
                if block.table_rows:
                    cells = _add_table_cells(cells, block.table_rows, max_cells)
        output.put(("chunk", "", conversion))
        sent += 1
    if sent != len(ranges):
        raise SourceConversionError("PDF converter returned fewer ranges than requested")
    output.put(("done", "", None))


@contextmanager
def _blocked_network() -> Any:
    original_create_connection = socket.create_connection
    original_connect = socket.socket.connect

    def deny_connection(*_args: object, **_kwargs: object) -> None:
        raise OSError("Network access is disabled during source conversion")

    socket.create_connection = deny_connection
    socket.socket.connect = deny_connection
    try:
        yield
    finally:
        socket.create_connection = original_create_connection
        socket.socket.connect = original_connect


def _inspect_pdf(
    path: Path,
    limits: SourceLimits,
    *,
    timeout: float | None = None,
    in_process: bool = False,
) -> int:
    try:
        with path.open("rb") as stream:
            if stream.read(5) != b"%PDF-":
                raise SourceFormatError("PDF extension does not match file content")
    except (SourceError, ValueError):
        raise
    except OSError as error:
        raise SourceConversionError("PDF source could not be inspected") from error
    if in_process:
        return _preflight_in_process(path, max_pages=limits.max_pages)
    return _run_pdf_preflight(
        path,
        max_pages=limits.max_pages,
        timeout=(limits.deadline_seconds if timeout is None else timeout),
    )


class _MessageCollector:
    """A minimal ``put``-only stand-in for a worker queue, for in-process inspection."""

    def __init__(self) -> None:
        self.message: Any = None

    def put(self, message: Any) -> None:
        self.message = message


def _preflight_in_process(path: Path, *, max_pages: int) -> int:
    """Count a PDF's pages here with no child, for the ``"inprocess"`` isolation mode."""
    collector = _MessageCollector()
    _pdf_preflight_worker(str(path), max_pages, collector)
    if collector.message is None:
        raise SourceConversionError("PDF source could not be inspected")
    return _preflight_result(collector.message)


def _preflight_result(message: Any) -> int:
    status, code, payload = message
    if status == "ok" and isinstance(payload, int) and not isinstance(payload, bool):
        return payload
    if code == SourceSecurityError.code:
        raise SourceSecurityError(str(payload))
    if code == SourceLimitError.code:
        raise SourceLimitError("max_pages", str(payload))
    if code == SourceDependencyError.code:
        raise SourceDependencyError(str(payload))
    if code == SourceFormatError.code:
        raise SourceFormatError(str(payload))
    raise SourceConversionError("PDF source could not be inspected", detail=str(payload) or None)


def _run_pdf_preflight(path: Path, *, max_pages: int, timeout: float) -> int:
    context = get_context("spawn")
    output = context.Queue(maxsize=1)
    process = context.Process(
        target=_pdf_preflight_worker,
        args=(str(path), max_pages, output),
    )
    try:
        process.start()
        try:
            status, code, payload = _wait_for_worker_message(output, process, timeout)
        except Empty:
            _bounded_process_cleanup(process)
            raise SourceTimeoutError("PDF inspection exceeded the configured deadline") from None
        except ChildProcessError:
            _bounded_process_cleanup(process)
            raise SourceConversionError(
                f"PDF inspection worker exited before returning a result{_exit_note(process)}"
            ) from None
        _bounded_process_cleanup(process)
        return _preflight_result((status, code, payload))
    except (KeyboardInterrupt, SystemExit):
        _bounded_process_cleanup(process)
        raise
    finally:
        output.close()
        output.join_thread()


def _exit_note(process: Any) -> str:
    """How the worker ended, for the error a caller sees.

    A negative exit code is the signal that killed it (-9: the kernel's OOM killer, the usual
    cause in a memory-capped container; -11: a native crash).
    """
    code = getattr(process, "exitcode", None)
    if code is None:
        return ""
    if code < 0:
        try:
            name = signal.Signals(-code).name
        except ValueError:
            name = "unknown signal"
        cause = ", likely out of memory)" if -code == 9 else ")"
        return f" (killed by signal {-code} {name}{cause}"
    return f" (exit code {code})"


_MAX_ERROR_DETAIL_CHARS = 500


def _bounded_text(text: str, limit: int = _MAX_ERROR_DETAIL_CHARS) -> str:
    """One line of printable text, at most ``limit`` characters."""
    text = " ".join("".join(ch if ch.isprintable() else " " for ch in text).split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _error_detail(error: BaseException) -> str:
    """``Type: message (at file.py:line in function)`` for an unexpected worker failure.

    The location is the frame that raised, by file name only. Up to two chained causes follow.
    The text is untrusted: it is for a record or a log, never for a prompt.
    """
    parts: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen and len(parts) < 3:
        seen.add(id(current))
        message = str(current).strip()
        part = f"{type(current).__name__}: {message}" if message else type(current).__name__
        frames = traceback.extract_tb(current.__traceback__)
        if frames:
            last = frames[-1]
            part += f" (at {Path(last.filename).name}:{last.lineno} in {last.name})"
        parts.append(part)
        current = current.__cause__ or (
            None if current.__suppress_context__ else current.__context__
        )
    return _bounded_text("; caused by ".join(parts))


def _wait_for_worker_message(output: Any, process: Any, timeout: float) -> Any:
    reader = getattr(output, "_reader", None)
    sentinel = getattr(process, "sentinel", None)
    if reader is not None and sentinel is not None:
        ready = wait((reader, sentinel), timeout=timeout)
        if reader in ready:
            return output.get(timeout=0.1)
        if sentinel in ready:
            try:
                return output.get(timeout=0.1)
            except Empty:
                raise ChildProcessError from None
        raise Empty
    try:
        return output.get(timeout=timeout)
    except Empty:
        if not process.is_alive():
            raise ChildProcessError from None
        raise


def _bounded_process_cleanup(process: Any) -> None:
    process.join(timeout=0.1)
    if not process.is_alive():
        return
    process.terminate()
    process.join(timeout=0.5)
    if not process.is_alive():
        return
    kill = getattr(process, "kill", None)
    if callable(kill):
        kill()
    process.join(timeout=0.5)
    if process.is_alive():
        raise SourceConversionError("PDF worker cleanup did not complete")


def _pdf_preflight_worker(path: str, max_pages: int, output: Any) -> None:
    try:
        pdfium = import_module("pypdfium2")
        pdfium_raw = import_module("pypdfium2.raw")
    except ModuleNotFoundError:
        output.put(
            (
                "error",
                SourceDependencyError.code,
                "PDF inspection requires the optional 'pdf' dependencies",
            )
        )
        return
    document = None
    try:
        try:
            document = pdfium.PdfDocument(path)
        except pdfium.PdfiumError as error:
            output.put(_pdfium_open_error(int(pdfium_raw.FPDF_GetLastError()), pdfium_raw, error))
            return
        if pdfium_raw.FPDF_GetSecurityHandlerRevision(document.raw) >= 0:
            output.put(
                ("error", SourceSecurityError.code, "encrypted PDF sources are not supported")
            )
            return
        page_count = len(document)
        if page_count > max_pages:
            output.put(("error", SourceLimitError.code, "PDF exceeds the configured page limit"))
            return
        output.put(("ok", "", page_count))
    except BaseException as error:
        output.put(("error", SourceConversionError.code, _error_detail(error)))
    finally:
        if document is not None:
            document.close()


def _pdfium_open_error(
    last_error: int, pdfium_raw: Any, error: BaseException
) -> tuple[str, str, str]:
    """The preflight's answer when PDFium cannot open a file that starts with ``%PDF-``."""
    if last_error == int(pdfium_raw.FPDF_ERR_PASSWORD):
        return ("error", SourceSecurityError.code, "encrypted PDF sources are not supported")
    if last_error == int(pdfium_raw.FPDF_ERR_SECURITY):
        return ("error", SourceSecurityError.code, "PDF security handler is not supported")
    if last_error == int(pdfium_raw.FPDF_ERR_FORMAT):
        return (
            "error",
            SourceFormatError.code,
            "PDF content is damaged or not a valid PDF (PDFium could not parse it)",
        )
    if last_error == int(pdfium_raw.FPDF_ERR_FILE):
        return (
            "error",
            SourceConversionError.code,
            f"PDFium could not open the file: {_error_detail(error)}",
        )
    return (
        "error",
        SourceConversionError.code,
        f"PDFium could not open the PDF (error {last_error}): {_error_detail(error)}",
    )


def _inspect_docx_content_types(
    archive: zipfile.ZipFile,
    names: set[str],
    limits: SourceLimits,
    deadline: float,
) -> None:
    content_name = next(
        (name for name in archive.namelist() if name.lower() == "[content_types].xml"), None
    )
    if content_name is None:
        raise SourceFormatError("DOCX is missing [Content_Types].xml")
    content_types = _read_zip_part(
        archive,
        content_name,
        limits=limits,
        deadline=deadline,
    )
    _parse_bounded_xml(
        content_types,
        limits=limits,
        deadline=deadline,
        malformed_message="DOCX content type XML is malformed",
    )
    content_types = content_types.lower()
    if b"macroenabled" in content_types or any("vbaproject.bin" in name for name in names):
        raise SourceSecurityError("DOCX macro content is prohibited")


def _inspect_relationships(
    archive: zipfile.ZipFile,
    names: set[str],
    limits: SourceLimits,
    deadline: float,
) -> int:
    """Validate package relationships and return how many external ones were stripped."""
    stripped = 0
    for original_name in archive.namelist():
        name = original_name.replace("\\", "/").lower()
        if not name.endswith(".rels") or name not in names:
            continue
        try:
            root = _parse_bounded_xml(
                _read_zip_part(
                    archive,
                    original_name,
                    limits=limits,
                    deadline=deadline,
                ),
                limits=limits,
                deadline=deadline,
                malformed_message="DOCX relationship XML is malformed",
            )
        except ElementTree.ParseError as error:
            raise SourceFormatError("DOCX relationship XML is malformed") from error
        for relationship in root.findall(f"{{{_RELATIONSHIP_NAMESPACE}}}Relationship"):
            mode = relationship.attrib.get("TargetMode", "").lower()
            target = relationship.attrib.get("Target", "")
            if mode == "external" or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE):
                if limits.external_links == "refuse":
                    raise SourceSecurityError("DOCX external relationship is prohibited")
                stripped += 1
    return stripped


def _read_zip_part(
    archive: zipfile.ZipFile,
    name: str,
    *,
    limits: SourceLimits,
    deadline: float,
) -> bytes:
    try:
        information = archive.getinfo(name)
    except KeyError:
        raise
    if information.file_size > limits.max_xml_part_bytes:
        raise SourceLimitError(
            "max_xml_part_bytes",
            "DOCX XML part exceeds the configured byte limit",
        )
    payload = bytearray()
    with archive.open(information) as stream:
        while chunk := stream.read(min(1024 * 1024, limits.max_xml_part_bytes + 1)):
            _remaining_deadline(deadline)
            payload.extend(chunk)
            if len(payload) > limits.max_xml_part_bytes:
                raise SourceLimitError(
                    "max_xml_part_bytes",
                    "DOCX XML part exceeds the configured byte limit",
                )
    return bytes(payload)


def _parse_bounded_xml(
    payload: bytes,
    *,
    limits: SourceLimits,
    deadline: float,
    malformed_message: str,
) -> Element:
    parser = ElementTree.iterparse(BytesIO(payload), events=("start", "end"))
    count = 0
    depth = 0
    root: Element | None = None
    try:
        for event, element in parser:
            if event == "start":
                if root is None:
                    root = element
                count += 1
                depth += 1
                if count > limits.max_xml_elements:
                    raise SourceLimitError(
                        "max_xml_elements",
                        "DOCX XML exceeds the configured element limit",
                    )
                if depth > limits.max_xml_depth:
                    raise SourceLimitError(
                        "max_xml_depth",
                        "DOCX XML exceeds the configured depth limit",
                    )
                if count % 1024 == 0:
                    _remaining_deadline(deadline)
            else:
                depth -= 1
    except ElementTree.ParseError:
        raise SourceFormatError(malformed_message) from None
    _remaining_deadline(deadline)
    if root is None:
        raise SourceFormatError(malformed_message)
    return root


def _word_text(element: Element) -> str:
    text = "".join(node.text or "" for node in element.iter(f"{{{_WORD_NAMESPACE}}}t"))
    return _normalize_text(text)


def _word_body_blocks(
    body: Element,
) -> tuple[tuple[Element, ...], int]:
    blocks: list[Element] = []
    unsupported = 0

    stack = [iter(body)]
    while stack:
        try:
            child = next(stack[-1])
        except StopIteration:
            stack.pop()
            continue
        local_name = _word_local_name(child.tag)
        if local_name in {"p", "tbl"}:
            blocks.append(child)
        elif local_name in _WORD_TRANSPARENT_CONTAINERS:
            stack.append(iter(child))
        elif local_name not in _WORD_METADATA_ELEMENTS and _word_element_is_nonempty(child):
            unsupported += 1
    return tuple(blocks), unsupported


def _word_local_name(tag: str) -> str:
    prefix = f"{{{_WORD_NAMESPACE}}}"
    return tag[len(prefix) :] if tag.startswith(prefix) else tag


def _word_element_is_nonempty(element: Element) -> bool:
    return bool(
        element.attrib
        or len(element)
        or (element.text is not None and element.text.strip())
        or _word_text(element)
    )


def _word_table_rows(table: Element) -> tuple[tuple[str, ...], ...]:
    rows: list[tuple[str, ...]] = []
    for row in table.findall(f"{{{_WORD_NAMESPACE}}}tr"):
        cells = tuple(_word_text(cell) for cell in row.findall(f"{{{_WORD_NAMESPACE}}}tc"))
        if cells:
            rows.append(cells)
    return tuple(rows)


def _text_block(
    source_name: str,
    order: int,
    text: str,
    *,
    section_path: tuple[str, ...] = (),
) -> SourceBlock:
    return SourceBlock(
        id=f"block-{order + 1:06d}",
        order=order,
        kind="text",
        text=text,
        provenance=SourceProvenance(source_name=source_name, section_path=section_path),
    )


class _SafeHtmlParser(HTMLParser):
    _BLOCKED = {"script", "style", "noscript", "template", "iframe", "object", "embed"}
    _BLOCKS = {
        "address",
        "article",
        "aside",
        "blockquote",
        "div",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "li",
        "main",
        "nav",
        "p",
        "pre",
        "section",
    }

    def __init__(self, *, max_cells: int | None = None) -> None:
        super().__init__(convert_charrefs=True)
        self.events: list[tuple[str, object]] = []
        self._blocked_depth = 0
        self._text: list[str] = []
        self._table_depth = 0
        self._rows: list[tuple[str, ...]] = []
        self._cells: list[str] = []
        self._cell_text: list[str] | None = None
        self._max_cells = max_cells
        self._cell_count = 0
        self._heading_tag: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        tag = tag.lower()
        if tag in self._BLOCKED:
            self._blocked_depth += 1
            return
        if self._blocked_depth:
            return
        if tag == "table":
            self._flush_text()
            self._table_depth += 1
            if self._table_depth == 1:
                self._rows = []
            return
        if self._table_depth:
            if tag == "tr":
                self._cells = []
            elif tag in {"td", "th"}:
                self._cell_text = []
            return
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._flush_text()
            self._heading_tag = tag
            return
        if tag in self._BLOCKS:
            self._flush_text()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._BLOCKED:
            if self._blocked_depth:
                self._blocked_depth -= 1
            return
        if self._blocked_depth:
            return
        if self._table_depth:
            if tag in {"td", "th"} and self._cell_text is not None:
                self._cell_count += 1
                if self._max_cells is not None and self._cell_count > self._max_cells:
                    raise SourceLimitError(
                        "max_cells", "Document tables exceed the configured cell limit"
                    )
                self._cells.append(_normalize_text(" ".join(self._cell_text)))
                self._cell_text = None
            elif tag == "tr" and self._cells:
                self._rows.append(tuple(self._cells))
                self._cells = []
            elif tag == "table":
                self._table_depth -= 1
                if self._table_depth == 0 and self._rows:
                    self.events.append(("table", tuple(self._rows)))
            return
        if tag == self._heading_tag:
            text = _normalize_text(" ".join(self._text))
            self._text = []
            self._heading_tag = None
            if text:
                self.events.append(("section", text))
            return
        if tag in self._BLOCKS:
            self._flush_text()

    def handle_data(self, data: str) -> None:
        if self._blocked_depth:
            return
        if self._table_depth and self._cell_text is not None:
            self._cell_text.append(data)
        elif not self._table_depth:
            self._text.append(data)

    def close(self) -> None:
        super().close()
        self._flush_text()

    def _flush_text(self) -> None:
        text = _normalize_text(" ".join(self._text))
        self._text = []
        if text:
            self.events.append(("text", text))


def _events_to_blocks(
    source_name: str,
    events: list[tuple[str, object]] | tuple[tuple[str, object], ...],
    *,
    max_cells: int | None = None,
) -> tuple[SourceBlock, ...]:
    blocks: list[SourceBlock] = []
    table_index = 0
    table_cells = 0
    current_section: tuple[str, ...] = ()
    for kind, value in events:
        if kind == "section":
            current_section = (str(value),)
            blocks.append(
                _text_block(
                    source_name,
                    len(blocks),
                    str(value),
                    section_path=current_section,
                )
            )
            continue
        if kind == "text":
            blocks.append(
                _text_block(
                    source_name,
                    len(blocks),
                    str(value),
                    section_path=current_section,
                )
            )
            continue
        rows = tuple(tuple(str(cell) for cell in row) for row in value)  # type: ignore[union-attr]
        if not rows:
            continue
        if max_cells is not None:
            table_cells = _add_table_cells(table_cells, rows, max_cells)
        table_index += 1
        provenance = SourceProvenance(
            source_name=source_name,
            section_path=current_section,
            row_start=1,
            row_end=len(rows),
        )
        table = SourceTable(id=f"table-{table_index:06d}", rows=rows, provenance=provenance)
        blocks.append(
            SourceBlock(
                id=f"block-{len(blocks) + 1:06d}",
                order=len(blocks),
                kind="table",
                text=render_table(rows),
                provenance=provenance,
                table=table,
            )
        )
    return tuple(blocks)


def _markdown_events(text: str, *, max_cells: int | None = None) -> list[tuple[str, object]]:
    lines = text.splitlines()
    events: list[tuple[str, object]] = []
    paragraph: list[str] = []
    index = 0
    table_cells = 0

    def flush_paragraph() -> None:
        rendered = "\n".join(paragraph).strip()
        paragraph.clear()
        if rendered:
            events.append(("text", rendered))

    while index < len(lines):
        line = lines[index]
        heading = re.fullmatch(r"\s{0,3}#{1,6}\s+(.+?)\s*#*\s*", line)
        if heading is not None:
            flush_paragraph()
            events.append(("section", heading.group(1)))
            index += 1
            continue
        if "|" in line and index + 1 < len(lines) and "|" in lines[index + 1]:
            table_lines: list[str] = []
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                table_lines.append(lines[index])
                index += 1
            remaining_cells = None if max_cells is None else max(max_cells - table_cells, 0)
            rows = _parse_markdown_table(table_lines, max_cells=remaining_cells)
            if rows:
                if max_cells is not None:
                    table_cells = _add_table_cells(table_cells, rows, max_cells)
                flush_paragraph()
                events.append(("table", rows))
                continue
            paragraph.extend(table_lines)
            continue
        if not line.strip():
            flush_paragraph()
        else:
            paragraph.append(line.rstrip())
        index += 1
    flush_paragraph()
    return events


def _word_is_heading(paragraph: Element) -> bool:
    properties = paragraph.find(f"{{{_WORD_NAMESPACE}}}pPr")
    if properties is None:
        return False
    style = properties.find(f"{{{_WORD_NAMESPACE}}}pStyle")
    value = style.attrib.get(f"{{{_WORD_NAMESPACE}}}val", "") if style is not None else ""
    return value.casefold().startswith(("heading", "title"))


def _plain_text_heading(paragraph: str) -> bool:
    stripped = paragraph.strip()
    if "\n" in stripped or len(stripped) > 120:
        return False
    return bool(re.match(r"(?i)^(?:section|module)\b", stripped)) or (
        len(stripped.split()) <= 12 and stripped.isupper()
    )


def _parse_markdown_table(
    lines: list[str],
    *,
    max_cells: int | None = None,
) -> tuple[tuple[str, ...], ...]:
    rows: list[tuple[str, ...]] = []
    cell_count = 0
    for line in lines:
        cells = _split_markdown_table_row(line)
        if cells and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        if any(cells):
            cell_count += len(cells)
            if max_cells is not None and cell_count > max_cells:
                raise SourceLimitError(
                    "max_cells", "Document tables exceed the configured cell limit"
                )
            rows.append(cells)
    return tuple(rows)


def _split_markdown_table_row(line: str) -> tuple[str, ...]:
    cells: list[list[str]] = [[]]
    code_delimiter = 0
    index = 0
    while index < len(line):
        character = line[index]
        if character == "`":
            end = index + 1
            while end < len(line) and line[end] == "`":
                end += 1
            count = end - index
            cells[-1].append(line[index:end])
            if code_delimiter == 0:
                code_delimiter = count
            elif code_delimiter == count:
                code_delimiter = 0
            index = end
            continue
        if character == "\\" and code_delimiter == 0:
            end = index + 1
            while end < len(line) and line[end] == "\\":
                end += 1
            count = end - index
            if end < len(line) and line[end] == "|":
                cells[-1].append("\\" * (count // 2))
                if count % 2:
                    cells[-1].append("|")
                else:
                    cells.append([])
                index = end + 1
                continue
            cells[-1].append("\\" * count)
            index = end
            continue
        if character == "|" and code_delimiter == 0:
            cells.append([])
        else:
            cells[-1].append(character)
        index += 1

    rendered = ["".join(cell).strip() for cell in cells]
    if len(rendered) > 1 and not rendered[0]:
        rendered.pop(0)
    if len(rendered) > 1 and not rendered[-1]:
        rendered.pop()
    return tuple(rendered)


def _add_table_cells(
    current: int,
    rows: tuple[tuple[str, ...], ...],
    max_cells: int,
) -> int:
    total = current + sum(len(row) for row in rows)
    if total > max_cells:
        raise SourceLimitError("max_cells", "Document tables exceed the configured cell limit")
    return total


def _validate_pdf_table_cells(conversion: PdfConversion, max_cells: int) -> None:
    total = 0
    for block in conversion.blocks:
        if block.table_rows:
            total = _add_table_cells(total, block.table_rows, max_cells)


def _docling_page(item: object) -> int | None:
    pages = _docling_pages(item)
    return pages[0] if pages else None


def _docling_pages(item: object) -> tuple[int, ...]:
    provenance = getattr(item, "prov", ()) or ()
    pages = {
        page
        for origin in provenance
        if isinstance((page := getattr(origin, "page_no", None)), int)
        and not isinstance(page, bool)
        and page >= 1
    }
    return tuple(sorted(pages))


def _docling_failed_pages(result: object) -> tuple[int, ...]:
    failed: set[int] = set()
    for error in getattr(result, "errors", ()) or ():
        page = getattr(error, "page_no", None)
        if page is None:
            page = getattr(error, "page", None)
        if isinstance(page, int) and not isinstance(page, bool) and page >= 1:
            failed.add(page)
            continue
        failed.update(_docling_pages(error))
    return tuple(sorted(failed))


def _docling_page_count(
    result: object,
    document: object,
    blocks: list[PdfConversionBlock],
) -> int:
    candidates = [max((page for block in blocks for page in block.pages), default=0)]
    pages = getattr(document, "pages", ()) or ()
    keys = getattr(pages, "keys", None)
    if callable(keys):
        page_keys: Any = keys()
        candidates.append(
            max(
                (
                    page
                    for page in page_keys
                    if isinstance(page, int) and not isinstance(page, bool) and page >= 1
                ),
                default=0,
            )
        )
    else:
        candidates.append(len(pages))
    source_input = getattr(result, "input", None)
    reported = getattr(source_input, "page_count", 0)
    if isinstance(reported, int) and not isinstance(reported, bool) and reported >= 0:
        candidates.append(reported)
    return max(candidates)


def _docling_conversion_incomplete(result: object) -> bool:
    errors = getattr(result, "errors", ()) or ()
    if errors:
        return True
    status = getattr(result, "status", None)
    if status is None:
        return False
    value = getattr(status, "value", status)
    normalized = str(value).lower()
    return any(marker in normalized for marker in ("partial", "failure", "failed", "error"))


def _docling_table_markdown(item: object, document: object) -> str:
    exporter = getattr(item, "export_to_markdown", None)
    if not callable(exporter):
        return ""
    try:
        return str(exporter(doc=document))
    except TypeError:
        return str(exporter())


def _docling_cell_text(cell: object, document: object) -> str:
    getter = getattr(cell, "_get_text", None)
    if callable(getter):
        try:
            return str(getter(doc=document))
        except TypeError:
            return str(getter())
    return str(getattr(cell, "text", ""))


def _docling_cell_starts(cell: object, axis: str, index: int) -> bool:
    """Whether ``cell`` begins at row or column ``index`` rather than continuing into it."""
    return int(getattr(cell, f"start_{axis}_offset_idx", index)) >= index


def _docling_grid_rows(item: object, document: object) -> tuple[tuple[str, ...], ...] | None:
    """Rows from a Docling table's cell grid, a merged cell's text written once.

    Docling's grid places a merged cell in every position it covers, so its exports repeat
    the text in each spanned column. Here a body cell's text stands in the first column it
    spans and the columns it continues into stay empty; a cell spanning rows keeps its text
    in each row, so a row read without its neighbours (a split table) still carries it.
    The leading column-header rows become one header row, as in Docling's DataFrame export:
    each column joins the header cells over it with ``.``, a cell spanning header rows counts
    once, and a column covered only by cells that start to its left has an empty header.
    Returns None when the item has no grid.
    """
    grid = getattr(getattr(item, "data", None), "grid", None)
    if not grid:
        return None
    rows = [list(row) for row in cast(Iterable[Iterable[object]], grid)]
    if not all(rows):
        return None
    width = max(len(row) for row in rows)
    starts = _docling_cell_starts

    def text(cell: object) -> str:
        return _docling_cell_text(cell, document)

    headers = 0
    for index, row in enumerate(rows):
        if not any(
            getattr(cell, "column_header", False) and starts(cell, "row", index) for cell in row
        ):
            break
        headers += 1
    header: tuple[str, ...]
    if headers:
        names: list[str] = []
        for column in range(width):
            over = [(r, rows[r][column]) for r in range(headers) if column < len(rows[r])]
            if not any(starts(cell, "col", column) for _, cell in over):
                names.append("")
                continue
            names.append(".".join(text(cell) for r, cell in over if starts(cell, "row", r)))
        header = tuple(names)
    else:
        header = tuple(str(column) for column in range(width))
    body = tuple(
        tuple(text(cell) if starts(cell, "col", column) else "" for column, cell in enumerate(row))
        for row in rows[headers:]
    )
    return (header, *body)


def _docling_table_rows(
    item: object,
    document: object,
    *,
    max_cells: int | None,
) -> tuple[tuple[str, ...], ...]:
    rows = _docling_grid_rows(item, document)
    if rows is not None:
        if max_cells is not None:
            _add_table_cells(0, rows, max_cells)
        return rows
    dataframe_exporter = getattr(item, "export_to_dataframe", None)
    if callable(dataframe_exporter):
        try:
            dataframe = dataframe_exporter(doc=document)
        except TypeError:
            dataframe = dataframe_exporter()
        columns = getattr(dataframe, "columns", None)
        row_exporter = getattr(dataframe, "itertuples", None)
        if columns is not None and callable(row_exporter):
            column_values = cast(Iterable[object], columns)
            row_values = cast(
                Iterable[Iterable[object]],
                row_exporter(index=False, name=None),
            )
            rows = (tuple(str(value) for value in column_values),) + tuple(
                tuple(str(value) for value in row) for row in row_values
            )
            if max_cells is not None:
                _add_table_cells(0, rows, max_cells)
            return rows
    table_text = _docling_table_markdown(item, document)
    return _parse_markdown_table(table_text.splitlines(), max_cells=max_cells)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _remaining_deadline(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise SourceTimeoutError("Source conversion exceeded the configured deadline")
    return remaining
