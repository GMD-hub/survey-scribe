"""DOCX, HTML, XLSX, and CSV untrusted-document contracts."""

from __future__ import annotations

import hashlib
import importlib
import sys
import time
import zipfile
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from survey_scribe.sources import tabular as tabular_source
from survey_scribe.sources.base import (
    DEFAULT_SOURCE_LIMITS,
    SourceConversionError,
    SourceDependencyError,
    SourceFormatError,
    SourceLimitError,
    SourceSecurityError,
    SourceTimeoutError,
    resolve_local_source,
)
from survey_scribe.sources.registry import SourceRegistry
from survey_scribe.sources.tabular import CsvAdapter, XlsxAdapter

CONTENT_TYPES = """<?xml version="1.0"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types" />
"""


def _write_docx(
    path: Path,
    *,
    extra_files: dict[str, bytes | str] | None = None,
    compression: int = zipfile.ZIP_DEFLATED,
) -> None:
    document = """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>Survey preamble</w:t></w:r></w:p>
    <w:tbl>
      <w:tr><w:tc><w:p><w:r><w:t>Code</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Label</w:t></w:r></w:p></w:tc></w:tr>
      <w:tr><w:tc><w:p><w:r><w:t>Q1</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Age</w:t></w:r></w:p></w:tc></w:tr>
    </w:tbl>
    <w:p><w:r><w:t>End note</w:t></w:r></w:p>
  </w:body>
</w:document>
"""
    with zipfile.ZipFile(path, "w", compression=compression) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("word/document.xml", document)
        for name, content in (extra_files or {}).items():
            archive.writestr(name, content)


def _write_xlsx_container(
    path: Path,
    *,
    extra_files: dict[str, str] | None = None,
    sheet_xml: str | None = None,
) -> None:
    workbook = """<?xml version="1.0"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" />
"""
    sheet = """<?xml version="1.0"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData><row r="1"><c r="A1"/><c r="B1"/></row><row r="2"><c r="A2"/><c r="B2"/></row></sheetData>
</worksheet>
"""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/worksheets/sheet1.xml", sheet if sheet_xml is None else sheet_xml)
        for name, content in (extra_files or {}).items():
            archive.writestr(name, content)


class FakeCell:
    def __init__(self, value: object, data_type: str = "s") -> None:
        self.value = value
        self.data_type = data_type


class FakeSheet:
    def __init__(self, rows: list[list[FakeCell]]) -> None:
        self._rows = rows

    def iter_rows(self) -> list[list[FakeCell]]:
        return self._rows


class FakeWorkbook:
    def __init__(self, rows: list[list[FakeCell]]) -> None:
        self.sheetnames = ["Survey"]
        self._sheet = FakeSheet(rows)
        self.closed = False

    def __getitem__(self, name: str) -> FakeSheet:
        assert name == "Survey"
        return self._sheet

    def close(self) -> None:
        self.closed = True


def test_docx_preserves_paragraph_table_order_and_real_table_origin(tmp_path: Path) -> None:
    path = tmp_path / "questionnaire.docx"
    _write_docx(path)

    document = SourceRegistry.default().convert(path)

    assert [block.kind for block in document.blocks] == ["text", "table", "text"]
    assert document.blocks[0].text == "Survey preamble"
    assert document.blocks[1].table is not None
    assert document.blocks[1].table.rows == (("Code", "Label"), ("Q1", "Age"))
    assert document.blocks[1].table.provenance.row_start == 1
    assert document.blocks[1].table.provenance.row_end == 2
    assert document.blocks[2].text == "End note"


@pytest.mark.parametrize(
    ("extra_files", "message"),
    [
        ({"../escaped.txt": "escape"}, "path traversal"),
        ({"word/vbaProject.bin": b"macro"}, "macro"),
        (
            {
                "word/_rels/document.xml.rels": """<?xml version="1.0"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Target="https://example.invalid/template" TargetMode="External" />
</Relationships>"""
            },
            "external relationship",
        ),
    ],
)
def test_docx_rejects_archive_execution_and_escape_vectors(
    tmp_path: Path, extra_files: dict[str, bytes | str], message: str
) -> None:
    path = tmp_path / "unsafe.docx"
    _write_docx(path, extra_files=extra_files)

    with pytest.raises(SourceSecurityError, match=message):
        SourceRegistry.default().convert(path)


def test_docx_rejects_archive_expansion_and_ratio_limits(tmp_path: Path) -> None:
    path = tmp_path / "large.docx"
    _write_docx(path, extra_files={"word/large.bin": b"0" * 20_000})

    with pytest.raises(SourceLimitError) as ratio_error:
        SourceRegistry.default().convert(
            path,
            limits=replace(DEFAULT_SOURCE_LIMITS, max_archive_ratio=1.1),
        )
    assert ratio_error.value.limit == "max_archive_ratio"

    with pytest.raises(SourceLimitError) as size_error:
        SourceRegistry.default().convert(
            path,
            limits=replace(DEFAULT_SOURCE_LIMITS, max_archive_expanded_bytes=100),
        )
    assert size_error.value.limit == "max_archive_expanded_bytes"


def test_html_discards_scripts_styles_and_remote_resources(tmp_path: Path) -> None:
    path = tmp_path / "questionnaire.html"
    path.write_text(
        """<!doctype html><html><head><style>hidden</style><script>attack()</script></head>
<body><img src="https://example.invalid/tracker"><p>Survey preamble</p>
<table><tr><th>Code</th><th>Question</th></tr><tr><td>Q1</td><td>Age?</td></tr></table>
<a href="https://example.invalid/payload">Visible label</a></body></html>""",
        encoding="utf-8",
    )

    document = SourceRegistry.default().convert(path)
    rendered = "\n".join(block.text for block in document.blocks)

    assert "Survey preamble" in rendered
    assert "Visible label" in rendered
    assert "attack" not in rendered
    assert "hidden" not in rendered
    assert "https://" not in rendered
    assert document.tables[0].rows[1] == ("Q1", "Age?")


def test_csv_has_deterministic_rows_provenance_and_cell_limit(tmp_path: Path) -> None:
    path = tmp_path / "questionnaire.csv"
    path.write_text("code,label\nQ1,Age\nQ2,Name\n", encoding="utf-8", newline="")

    document = SourceRegistry.default().convert(path)
    table = document.tables[0]

    assert table.rows == (("code", "label"), ("Q1", "Age"), ("Q2", "Name"))
    assert table.provenance.row_start == 1
    assert table.provenance.row_end == 3
    with pytest.raises(SourceLimitError) as raised:
        SourceRegistry.default().convert(
            path,
            limits=replace(DEFAULT_SOURCE_LIMITS, max_cells=5),
        )
    assert raised.value.limit == "max_cells"


def test_csv_rejects_binary_nul_while_streaming(tmp_path: Path) -> None:
    path = tmp_path / "binary.csv"
    path.write_bytes(b"code,label\nQ1,Age\x00hidden\n")

    with pytest.raises(SourceFormatError, match="NUL"):
        SourceRegistry.default().convert(path)


def test_xlsx_dependency_is_lazy_and_loader_flags_are_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "questionnaire.xlsx"
    _write_xlsx_container(path)
    workbook = FakeWorkbook(
        [
            [FakeCell("code"), FakeCell("label")],
            [FakeCell("Q1"), FakeCell("Age")],
        ]
    )
    calls: list[tuple[Path, dict[str, object]]] = []

    def fake_load_workbook(filename: Path, **kwargs: object) -> FakeWorkbook:
        calls.append((filename, kwargs))
        return workbook

    real_import = importlib.import_module

    def fake_import(name: str, package: str | None = None) -> Any:
        if name == "openpyxl":
            return SimpleNamespace(load_workbook=fake_load_workbook)
        return real_import(name, package)

    monkeypatch.setattr("survey_scribe.sources.tabular.import_module", fake_import)
    sys.modules.pop("openpyxl", None)
    adapter = XlsxAdapter()
    assert "openpyxl" not in sys.modules

    document = adapter.convert(resolve_local_source(path), limits=DEFAULT_SOURCE_LIMITS)

    assert calls == [(path.resolve(), {"read_only": True, "data_only": False, "keep_links": False})]
    assert workbook.closed is True
    assert document.tables[0].provenance.sheet == "Survey"
    assert document.tables[0].rows[1] == ("Q1", "Age")


def test_xlsx_rejects_formulas_external_links_and_cell_limit(tmp_path: Path) -> None:
    path = tmp_path / "questionnaire.xlsx"
    _write_xlsx_container(path)
    formula_workbook = FakeWorkbook([[FakeCell('=WEBSERVICE("https://invalid")', "f")]])
    adapter = XlsxAdapter(workbook_loader=lambda _path, **_kwargs: formula_workbook)

    with pytest.raises(SourceSecurityError, match="formula"):
        adapter.convert(resolve_local_source(path), limits=DEFAULT_SOURCE_LIMITS)

    external = tmp_path / "external.xlsx"
    _write_xlsx_container(external, extra_files={"xl/externalLinks/externalLink1.xml": "<x/>"})
    with pytest.raises(SourceSecurityError, match="external link"):
        XlsxAdapter(workbook_loader=lambda _path, **_kwargs: FakeWorkbook([])).convert(
            resolve_local_source(external), limits=DEFAULT_SOURCE_LIMITS
        )

    macro = tmp_path / "macro.xlsx"
    _write_xlsx_container(macro, extra_files={"xl/vbaProject.bin": "macro"})
    with pytest.raises(SourceSecurityError, match="macro"):
        XlsxAdapter(workbook_loader=lambda _path, **_kwargs: FakeWorkbook([])).convert(
            resolve_local_source(macro), limits=DEFAULT_SOURCE_LIMITS
        )

    with pytest.raises(SourceLimitError) as raised:
        XlsxAdapter(workbook_loader=lambda _path, **_kwargs: FakeWorkbook([])).convert(
            resolve_local_source(path),
            limits=replace(DEFAULT_SOURCE_LIMITS, max_cells=3),
        )
    assert raised.value.limit == "max_cells"


def test_xlsx_rejects_formula_xml_before_loading_openpyxl(tmp_path: Path) -> None:
    path = tmp_path / "formula.xlsx"
    _write_xlsx_container(
        path,
        sheet_xml="""<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<sheetData><row r="1"><c r="A1"><f>WEBSERVICE(&quot;https://invalid&quot;)</f></c></row></sheetData>
</worksheet>""",
    )

    def forbidden_loader(*_args: object, **_kwargs: object) -> object:
        pytest.fail("openpyxl must not load a workbook containing formula XML")

    with pytest.raises(SourceSecurityError, match="formula"):
        XlsxAdapter(workbook_loader=forbidden_loader).convert(
            resolve_local_source(path), limits=DEFAULT_SOURCE_LIMITS
        )


def test_xlsx_rejects_stale_dimension_that_would_truncate_cells(tmp_path: Path) -> None:
    path = tmp_path / "stale-dimension.xlsx"
    _write_xlsx_container(
        path,
        sheet_xml="""<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<dimension ref="A1"/><sheetData><row r="1"><c r="A1"/></row><row r="2"><c r="B2"/></row></sheetData>
</worksheet>""",
    )

    with pytest.raises(SourceFormatError, match="dimension"):
        XlsxAdapter(workbook_loader=lambda _path, **_kwargs: FakeWorkbook([])).convert(
            resolve_local_source(path), limits=DEFAULT_SOURCE_LIMITS
        )


@pytest.mark.parametrize(
    "dimensions",
    [
        '<dimension ref="A1"/><dimension ref="A1:B2"/>',
        '<dimension ref="A1"/><foreign:dimension xmlns:foreign="urn:foreign" ref="A1:B2"/>',
    ],
)
def test_xlsx_dimension_cannot_be_overridden(tmp_path: Path, dimensions: str) -> None:
    path = tmp_path / "overridden-dimension.xlsx"
    _write_xlsx_container(
        path,
        sheet_xml=f"""<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
{dimensions}<sheetData><row r="1"><c r="A1"/></row><row r="2"><c r="B2"/></row></sheetData>
</worksheet>""",
    )

    with pytest.raises(SourceFormatError, match="dimension"):
        XlsxAdapter(workbook_loader=lambda _path, **_kwargs: FakeWorkbook([])).convert(
            resolve_local_source(path), limits=DEFAULT_SOURCE_LIMITS
        )


def test_fixture_content_is_synthetic_and_deterministic() -> None:
    payload = b"code,label\nQ1,Age\n"
    assert (
        hashlib.sha256(payload).hexdigest()
        == "7c197ec18d1cf0767f67e68a45e0b31b7199d593da14bc14528d3374951e73eb"
    )


def test_csv_empty_invalid_utf8_malformed_and_io_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = tmp_path / "empty.csv"
    empty.write_text("", encoding="utf-8")
    assert SourceRegistry.default().convert(empty).blocks == ()

    invalid = tmp_path / "invalid.csv"
    invalid.write_bytes(b"\xff")
    with pytest.raises(SourceFormatError, match="UTF-8"):
        SourceRegistry.default().convert(invalid)

    malformed = tmp_path / "malformed.csv"
    malformed.write_text('code,"unterminated', encoding="utf-8")
    with pytest.raises(SourceFormatError, match="malformed"):
        SourceRegistry.default().convert(malformed)

    unreadable = tmp_path / "unreadable.csv"
    unreadable.write_text("code,label", encoding="utf-8")
    resolved = resolve_local_source(unreadable)

    def fail_open(*_args: object, **_kwargs: object) -> object:
        raise OSError

    monkeypatch.setattr(Path, "open", fail_open)
    with pytest.raises(SourceConversionError, match="could not be read"):
        CsvAdapter().convert(resolved, limits=DEFAULT_SOURCE_LIMITS)


def test_xlsx_loader_errors_are_typed(tmp_path: Path) -> None:
    path = tmp_path / "questionnaire.xlsx"
    _write_xlsx_container(path)
    source = resolve_local_source(path)

    def missing_loader(*_args: object, **_kwargs: object) -> object:
        raise SourceDependencyError("missing dependency")

    def broken_loader(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("broken workbook")

    with pytest.raises(SourceDependencyError, match="missing dependency"):
        XlsxAdapter(workbook_loader=missing_loader).convert(source, limits=DEFAULT_SOURCE_LIMITS)
    with pytest.raises(SourceFormatError, match="could not be opened"):
        XlsxAdapter(workbook_loader=broken_loader).convert(source, limits=DEFAULT_SOURCE_LIMITS)


def test_xlsx_runtime_cell_limit_and_empty_sheet_are_handled(tmp_path: Path) -> None:
    path = tmp_path / "questionnaire.xlsx"
    _write_xlsx_container(path)
    source = resolve_local_source(path)
    many_cells = FakeWorkbook(
        [
            [FakeCell("A"), FakeCell("B")],
            [FakeCell("C"), FakeCell("D")],
            [FakeCell("E")],
        ]
    )

    with pytest.raises(SourceLimitError, match="cell limit"):
        XlsxAdapter(workbook_loader=lambda _path, **_kwargs: many_cells).convert(
            source,
            limits=replace(DEFAULT_SOURCE_LIMITS, max_cells=4),
        )

    empty_workbook = FakeWorkbook([])
    document = XlsxAdapter(workbook_loader=lambda _path, **_kwargs: empty_workbook).convert(
        source, limits=DEFAULT_SOURCE_LIMITS
    )
    assert document.blocks == ()
    assert empty_workbook.closed is True


def test_openpyxl_loader_reports_missing_optional_dependency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing_import(_name: str) -> object:
        raise ModuleNotFoundError

    monkeypatch.setattr(tabular_source, "import_module", missing_import)
    with pytest.raises(SourceDependencyError, match="optional 'tabular'"):
        tabular_source._load_openpyxl_workbook(tmp_path / "questionnaire.xlsx")


def test_xlsx_relationship_validation_rejects_malformed_and_remote_targets() -> None:
    with pytest.raises(SourceFormatError, match="relationship XML is malformed"):
        tabular_source._reject_external_relationships(b"<Relationships", "XLSX")
    with pytest.raises(SourceSecurityError, match="external relationship"):
        tabular_source._reject_external_relationships(
            b'<Relationships><Relationship Target="https://example.invalid" /></Relationships>',
            "XLSX",
        )
    tabular_source._reject_external_relationships(
        b'<Relationships><Relationship Target="worksheet.xml" /></Relationships>',
        "XLSX",
    )


def test_xlsx_preflight_accepts_local_relationships(tmp_path: Path) -> None:
    path = tmp_path / "local-relationship.xlsx"
    _write_xlsx_container(
        path,
        extra_files={
            "xl/_rels/workbook.xml.rels": (
                '<Relationships><Relationship Target="worksheets/sheet1.xml" /></Relationships>'
            )
        },
    )

    document = XlsxAdapter(workbook_loader=lambda _path, **_kwargs: FakeWorkbook([])).convert(
        resolve_local_source(path), limits=DEFAULT_SOURCE_LIMITS
    )

    assert document.blocks == ()


def test_xlsx_rejects_malformed_worksheet_and_package_io_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    malformed = tmp_path / "malformed.xlsx"
    _write_xlsx_container(malformed, sheet_xml="<worksheet")
    with pytest.raises(SourceFormatError, match="package XML is malformed"):
        XlsxAdapter(workbook_loader=lambda _path, **_kwargs: FakeWorkbook([])).convert(
            resolve_local_source(malformed), limits=DEFAULT_SOURCE_LIMITS
        )

    path = tmp_path / "unreadable.xlsx"
    path.write_bytes(b"package")
    entry = SimpleNamespace(filename="xl/worksheets/sheet1.xml")
    monkeypatch.setattr(tabular_source, "inspect_zip_archive", lambda _path, _limits: (entry,))

    class BrokenArchive:
        def __init__(self, _path: Path) -> None:
            raise OSError

    monkeypatch.setattr(tabular_source.zipfile, "ZipFile", BrokenArchive)
    with pytest.raises(SourceConversionError, match="could not be inspected"):
        tabular_source._inspect_xlsx(path, DEFAULT_SOURCE_LIMITS, time.monotonic() + 10)


def test_xlsx_coordinate_dimension_and_observed_bounds() -> None:
    assert tabular_source._dimension_bound(None, DEFAULT_SOURCE_LIMITS) is None
    assert tabular_source._cell_coordinates("$AA$10") == (27, 10)

    with pytest.raises(SourceLimitError, match="dimension exceeds"):
        tabular_source._dimension_bound("A1:B2", replace(DEFAULT_SOURCE_LIMITS, max_cells=3))
    with pytest.raises(SourceFormatError, match="malformed"):
        tabular_source._cell_coordinates("A0")
    with pytest.raises(SourceFormatError, match="Excel worksheet limits"):
        tabular_source._cell_coordinates("XFE1")
    with pytest.raises(SourceLimitError, match="dimension exceeds"):
        tabular_source._check_observed_bound(
            declared=None,
            observed=(2, 2),
            limits=replace(DEFAULT_SOURCE_LIMITS, max_cells=3),
        )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ""),
        (True, "TRUE"),
        (False, "FALSE"),
        (date(2026, 8, 30), "2026-08-30"),
        (42, "42"),
    ],
)
def test_xlsx_cell_rendering_is_stable(value: object, expected: str) -> None:
    assert tabular_source._render_cell(value) == expected


def test_tabular_deadline_check_is_typed() -> None:
    with pytest.raises(SourceTimeoutError):
        tabular_source._check_deadline(time.monotonic() - 1)
