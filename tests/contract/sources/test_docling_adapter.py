"""PDF adapter contracts for local Docling configuration and worker isolation."""

from __future__ import annotations

import os
import socket
import time
import zipfile
from dataclasses import replace
from pathlib import Path
from queue import Empty
from types import SimpleNamespace
from typing import Any

import pytest

from survey_scribe.sources import docling as docling_source
from survey_scribe.sources.base import (
    DEFAULT_SOURCE_LIMITS,
    SourceConversionError,
    SourceCoverage,
    SourceDependencyError,
    SourceDiagnostic,
    SourceFormatError,
    SourceLimitError,
    SourceSecurityError,
    SourceTimeoutError,
    resolve_local_source,
)
from survey_scribe.sources.docling import (
    DoclingConverter,
    DoclingPdfAdapter,
    DocxAdapter,
    HtmlAdapter,
    MarkdownAdapter,
    PdfConversion,
    PdfConversionBlock,
)


def fake_pdf_conversion(path: str, artifacts_path: str | None) -> PdfConversion:
    """Pickle-safe fake used by the Windows spawn worker."""
    del path, artifacts_path
    return PdfConversion(
        page_count=3,
        blocks=(
            PdfConversionBlock(text="Survey preamble", page=1),
            PdfConversionBlock(text="Digital question", page=2),
            PdfConversionBlock(text="Scanned OCR question", page=3),
        ),
    )


def slow_pdf_conversion(path: str, artifacts_path: str | None) -> PdfConversion:
    """Pickle-safe blocking fake used to prove deadline termination."""
    del path, artifacts_path
    time.sleep(30)
    return PdfConversion(page_count=1, blocks=())


def network_pdf_conversion(path: str, artifacts_path: str | None) -> PdfConversion:
    """Attempt a forbidden fetch so the worker-level network guard is exercised."""
    del path, artifacts_path
    socket.create_connection(("example.invalid", 443), timeout=1)
    return PdfConversion(page_count=1, blocks=())


def dependency_pdf_conversion(path: str, artifacts_path: str | None) -> PdfConversion:
    """Raise a typed dependency error across the spawned worker boundary."""
    del path, artifacts_path
    raise SourceDependencyError("OCR artifacts unavailable")


def security_pdf_conversion(path: str, artifacts_path: str | None) -> PdfConversion:
    """Raise a typed security error across the spawned worker boundary."""
    del path, artifacts_path
    raise SourceSecurityError("unsafe PDF")


def table_pdf_conversion(path: str, artifacts_path: str | None) -> PdfConversion:
    """Return table, empty, and page-provenance blocks for adapter normalization."""
    del path, artifacts_path
    return PdfConversion(
        page_count=1,
        blocks=(
            PdfConversionBlock(text="code | label", page=1, table_rows=(("code", "label"),)),
            PdfConversionBlock(text="   ", page=None),
        ),
    )


def oversized_pdf_conversion(path: str, artifacts_path: str | None) -> PdfConversion:
    """Report more converted pages than the static PDF inspection found."""
    del path, artifacts_path
    return PdfConversion(page_count=3, blocks=())


def out_of_range_block_conversion(path: str, artifacts_path: str | None) -> PdfConversion:
    """Return one converted block beyond the configured page ceiling."""
    del path, artifacts_path
    return PdfConversion(
        page_count=1,
        blocks=(PdfConversionBlock(text="Question", page=3),),
    )


def partial_pdf_conversion(path: str, artifacts_path: str | None) -> PdfConversion:
    """Represent one failed page without making the converted pages look complete."""
    del path, artifacts_path
    return PdfConversion(
        page_count=3,
        blocks=(
            PdfConversionBlock(text="Page one", page=1),
            PdfConversionBlock(text="Page three", page=3),
        ),
        coverage=SourceCoverage(
            unit="page",
            total_units=3,
            converted_units=(1, 3),
            failed_units=(2,),
        ),
        diagnostics=(
            SourceDiagnostic(
                code="PDF_PAGE_CONVERSION_FAILED",
                message="PDF page conversion failed",
                unit="page",
                unit_index=2,
            ),
        ),
    )


def multi_page_table_conversion(path: str, artifacts_path: str | None) -> PdfConversion:
    """Return one table whose physical source spans two pages."""
    del path, artifacts_path
    return PdfConversion(
        page_count=2,
        blocks=(
            PdfConversionBlock(
                text="code | label",
                page=1,
                pages=(1, 2),
                table_rows=(("code", "label"),),
            ),
        ),
    )


def _write_pdf(path: Path, body: bytes = b"1 0 obj <</Type /Page>> endobj") -> None:
    path.write_bytes(b"%PDF-1.7\n" + body + b"\n%%EOF")


def test_pdf_fake_preserves_preamble_scanned_content_and_page_provenance(tmp_path: Path) -> None:
    path = tmp_path / "questionnaire.pdf"
    _write_pdf(path)

    document = DoclingPdfAdapter(converter=fake_pdf_conversion).convert(
        resolve_local_source(path), limits=replace(DEFAULT_SOURCE_LIMITS, deadline_seconds=10)
    )

    assert [block.text for block in document.blocks] == [
        "Survey preamble",
        "Digital question",
        "Scanned OCR question",
    ]
    assert [block.provenance.page for block in document.blocks] == [1, 2, 3]


def test_pdf_partial_conversion_preserves_failed_page_coverage(tmp_path: Path) -> None:
    path = tmp_path / "partial.pdf"
    _write_pdf(path)

    document = DoclingPdfAdapter(converter=partial_pdf_conversion).convert(
        resolve_local_source(path), limits=replace(DEFAULT_SOURCE_LIMITS, deadline_seconds=10)
    )

    assert document.coverage.unit == "page"
    assert document.coverage.converted_units == (1, 3)
    assert document.coverage.failed_units == (2,)
    assert document.coverage.complete is False
    assert document.diagnostics[0].unit_index == 2
    with pytest.raises(Exception, match="frozen"):
        document.coverage.failed_units = ()


def test_pdf_block_and_table_keep_complete_multi_page_provenance(tmp_path: Path) -> None:
    path = tmp_path / "multi-page.pdf"
    _write_pdf(path)

    document = DoclingPdfAdapter(converter=multi_page_table_conversion).convert(
        resolve_local_source(path), limits=replace(DEFAULT_SOURCE_LIMITS, deadline_seconds=10)
    )

    assert document.blocks[0].provenance.page == 1
    assert document.blocks[0].provenance.pages == (1, 2)
    assert document.tables[0].provenance.pages == (1, 2)


def test_pdf_rejects_encryption_and_page_limit_before_worker(tmp_path: Path) -> None:
    encrypted = tmp_path / "encrypted.pdf"
    _write_pdf(encrypted, b"/Encrypt 1 0 R")
    with pytest.raises(SourceSecurityError, match="encrypted"):
        DoclingPdfAdapter(converter=fake_pdf_conversion).convert(
            resolve_local_source(encrypted), limits=DEFAULT_SOURCE_LIMITS
        )

    too_many = tmp_path / "many-pages.pdf"
    _write_pdf(too_many, b"\n".join(b"<</Type /Page>>" for _ in range(3)))
    with pytest.raises(SourceLimitError) as raised:
        DoclingPdfAdapter(converter=fake_pdf_conversion).convert(
            resolve_local_source(too_many),
            limits=replace(DEFAULT_SOURCE_LIMITS, max_pages=2),
        )
    assert raised.value.limit == "max_pages"


def test_pdf_deadline_yields_stable_typed_error_and_worker_is_recreated(tmp_path: Path) -> None:
    path = tmp_path / "questionnaire.pdf"
    _write_pdf(path)
    adapter = DoclingPdfAdapter(converter=slow_pdf_conversion)
    limits = replace(DEFAULT_SOURCE_LIMITS, deadline_seconds=0.05)

    with pytest.raises(SourceTimeoutError) as first:
        adapter.convert(resolve_local_source(path), limits=limits)
    with pytest.raises(SourceTimeoutError) as second:
        adapter.convert(resolve_local_source(path), limits=limits)

    assert first.value.code == "SOURCE_TIMEOUT"
    assert first.value.diagnostic.code == "SOURCE_TIMEOUT"
    assert (
        str(first.value) == str(second.value) == "PDF conversion exceeded the configured deadline"
    )


def test_pdf_worker_blocks_network_even_for_an_injected_converter(tmp_path: Path) -> None:
    path = tmp_path / "questionnaire.pdf"
    _write_pdf(path)

    with pytest.raises(SourceConversionError, match="PDF conversion failed"):
        DoclingPdfAdapter(converter=network_pdf_conversion).convert(
            resolve_local_source(path),
            limits=replace(DEFAULT_SOURCE_LIMITS, deadline_seconds=10),
        )


def test_docling_configuration_forces_local_pdfium_ocr_and_disables_remote_services(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    class FakePdfiumBackend:
        pass

    class FakePipelineOptions:
        do_ocr = False
        do_table_structure = False
        enable_remote_services = True
        artifacts_path: Path | None = None
        ocr_options: object | None = None

    class FakeEasyOcrOptions:
        def __init__(self, **kwargs: object) -> None:
            captured["ocr_kwargs"] = kwargs

    class FakePdfFormatOption:
        def __init__(self, **kwargs: object) -> None:
            captured["format_kwargs"] = kwargs

    class FakeDocument:
        def iterate_items(self) -> list[tuple[object, int]]:
            item = SimpleNamespace(text="Short questionnaire", prov=[SimpleNamespace(page_no=1)])
            return [(item, 0)]

    class FakeDocumentConverter:
        def __init__(self, **kwargs: object) -> None:
            captured["converter_kwargs"] = kwargs

        def convert(self, path: str) -> object:
            captured["path"] = path
            return SimpleNamespace(document=FakeDocument())

    modules = {
        "docling.backend.pypdfium2_backend": SimpleNamespace(
            PyPdfiumDocumentBackend=FakePdfiumBackend
        ),
        "docling.datamodel.base_models": SimpleNamespace(InputFormat=SimpleNamespace(PDF="pdf")),
        "docling.datamodel.pipeline_options": SimpleNamespace(
            EasyOcrOptions=FakeEasyOcrOptions,
            PdfPipelineOptions=FakePipelineOptions,
        ),
        "docling.document_converter": SimpleNamespace(
            DocumentConverter=FakeDocumentConverter,
            PdfFormatOption=FakePdfFormatOption,
        ),
    }

    def fake_import(name: str) -> object:
        return modules[name]

    monkeypatch.setattr("survey_scribe.sources.docling.import_module", fake_import)
    artifacts = tmp_path / "ocr"
    artifacts.mkdir()
    conversion = DoclingConverter()(str(tmp_path / "questionnaire.pdf"), str(artifacts))

    format_kwargs = captured["format_kwargs"]
    assert isinstance(format_kwargs, dict)
    pipeline = format_kwargs["pipeline_options"]
    assert pipeline.do_ocr is True
    assert pipeline.do_table_structure is True
    assert pipeline.enable_remote_services is False
    assert pipeline.artifacts_path == artifacts
    assert captured["ocr_kwargs"] == {"force_full_page_ocr": True}
    assert format_kwargs["backend"] is FakePdfiumBackend
    assert conversion.blocks[0].text == "Short questionnaire"
    assert conversion.blocks[0].page == 1
    assert os.environ.get("DOCLING_ARTIFACTS_PATH") != str(artifacts)


def test_docling_converter_requires_local_artifacts_and_installed_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    converter = DoclingConverter()

    with pytest.raises(SourceDependencyError, match="not configured"):
        converter(str(tmp_path / "questionnaire.pdf"), None)
    with pytest.raises(SourceDependencyError, match="does not exist"):
        converter(str(tmp_path / "questionnaire.pdf"), str(tmp_path / "missing"))

    artifacts = tmp_path / "ocr"
    artifacts.mkdir()

    def missing_module(_name: str) -> object:
        raise ModuleNotFoundError

    monkeypatch.setattr(docling_source, "import_module", missing_module)
    with pytest.raises(SourceDependencyError, match="optional 'pdf'"):
        converter(str(tmp_path / "questionnaire.pdf"), str(artifacts))


def test_docling_converter_normalizes_tables_and_skips_empty_items(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakePipelineOptions:
        pass

    class FakeEasyOcrOptions:
        def __init__(self, **_kwargs: object) -> None:
            return None

    class FakePdfFormatOption:
        def __init__(self, **_kwargs: object) -> None:
            return None

    class TableItem:
        label = "table"
        prov = [SimpleNamespace(page_no=1), SimpleNamespace(page_no=2)]

        def export_to_markdown(self, *, doc: object) -> str:
            del doc
            return "| code | label |\n| --- | --- |\n| Q1 | Age |"

    class EmptyTableItem:
        label = "table"
        prov: list[object] = []

        def export_to_markdown(self, *, doc: object) -> str:
            del doc
            return "| |"

    class EmptyItem:
        label = "text"
        text = "   "
        prov: list[object] = []

    class FakeDocument:
        pages = {1: object(), 2: object()}

        def iterate_items(self) -> list[tuple[object, int]]:
            return [(TableItem(), 0), (EmptyTableItem(), 0), (EmptyItem(), 0)]

    class FakeDocumentConverter:
        def __init__(self, **_kwargs: object) -> None:
            return None

        def convert(self, _path: str) -> object:
            return SimpleNamespace(document=FakeDocument())

    modules = {
        "docling.backend.pypdfium2_backend": SimpleNamespace(PyPdfiumDocumentBackend=object()),
        "docling.datamodel.base_models": SimpleNamespace(InputFormat=SimpleNamespace(PDF="pdf")),
        "docling.datamodel.pipeline_options": SimpleNamespace(
            EasyOcrOptions=FakeEasyOcrOptions,
            PdfPipelineOptions=FakePipelineOptions,
        ),
        "docling.document_converter": SimpleNamespace(
            DocumentConverter=FakeDocumentConverter,
            PdfFormatOption=FakePdfFormatOption,
        ),
    }
    monkeypatch.setattr(docling_source, "import_module", modules.__getitem__)
    artifacts = tmp_path / "ocr"
    artifacts.mkdir()

    conversion = DoclingConverter()(str(tmp_path / "questionnaire.pdf"), str(artifacts))

    assert conversion.page_count == 2
    assert conversion.blocks == (
        PdfConversionBlock(
            text="code | label\nQ1 | Age",
            page=1,
            pages=(1, 2),
            table_rows=(("code", "label"), ("Q1", "Age")),
        ),
    )


def test_pdf_adapter_normalizes_tables_and_skips_empty_blocks(tmp_path: Path) -> None:
    path = tmp_path / "questionnaire.pdf"
    _write_pdf(path)

    document = DoclingPdfAdapter(converter=table_pdf_conversion, artifacts_path=tmp_path).convert(
        resolve_local_source(path), limits=replace(DEFAULT_SOURCE_LIMITS, deadline_seconds=10)
    )

    assert [block.kind for block in document.blocks] == ["table"]
    assert document.tables[0].rows == (("code", "label"),)


@pytest.mark.parametrize(
    "converter",
    [oversized_pdf_conversion, out_of_range_block_conversion],
)
def test_pdf_adapter_enforces_converted_page_limits(tmp_path: Path, converter: object) -> None:
    path = tmp_path / "questionnaire.pdf"
    _write_pdf(path)

    with pytest.raises(SourceLimitError, match="page limit"):
        DoclingPdfAdapter(converter=converter).convert(  # type: ignore[arg-type]
            resolve_local_source(path),
            limits=replace(DEFAULT_SOURCE_LIMITS, max_pages=2, deadline_seconds=10),
        )


@pytest.mark.parametrize(
    ("converter", "error_type", "message"),
    [
        (dependency_pdf_conversion, SourceDependencyError, "OCR artifacts unavailable"),
        (security_pdf_conversion, SourceSecurityError, "unsafe PDF"),
    ],
)
def test_pdf_worker_preserves_typed_source_errors(
    tmp_path: Path,
    converter: object,
    error_type: type[Exception],
    message: str,
) -> None:
    path = tmp_path / "questionnaire.pdf"
    _write_pdf(path)

    with pytest.raises(error_type, match=message):
        DoclingPdfAdapter(converter=converter).convert(  # type: ignore[arg-type]
            resolve_local_source(path),
            limits=replace(DEFAULT_SOURCE_LIMITS, deadline_seconds=10),
        )


def test_pdf_inspection_rejects_bad_content_and_io_errors(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.pdf"
    invalid.write_bytes(b"not a PDF")
    with pytest.raises(SourceFormatError, match="does not match"):
        DoclingPdfAdapter(converter=fake_pdf_conversion).convert(
            resolve_local_source(invalid), limits=DEFAULT_SOURCE_LIMITS
        )

    with pytest.raises(SourceConversionError, match="could not be inspected"):
        docling_source._inspect_pdf(tmp_path / "missing.pdf", DEFAULT_SOURCE_LIMITS)


def _write_docx_parts(
    path: Path,
    *,
    content_types: str | None = "<Types/>",
    document: str | None = None,
    relationship: str | None = None,
) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        if content_types is not None:
            archive.writestr("[Content_Types].xml", content_types)
        if document is not None:
            archive.writestr("word/document.xml", document)
        if relationship is not None:
            archive.writestr("word/_rels/document.xml.rels", relationship)


@pytest.mark.parametrize(
    ("content_types", "document", "relationship", "message"),
    [
        (None, "<document/>", None, "Content_Types"),
        ("<Types>macroEnabled</Types>", "<document/>", None, "macro"),
        ("<Types/>", None, None, "word/document.xml"),
        ("<Types/>", "<document", None, "malformed"),
        ("<Types/>", "<document/>", None, "body is missing"),
        (
            "<Types/>",
            f'<w:document xmlns:w="{docling_source._WORD_NAMESPACE}"><w:body/></w:document>',
            "<Relationships",
            "relationship XML is malformed",
        ),
        (
            "<Types/>",
            f'<w:document xmlns:w="{docling_source._WORD_NAMESPACE}"><w:body/></w:document>',
            f'<Relationships xmlns="{docling_source._RELATIONSHIP_NAMESPACE}">'
            '<Relationship Target="https://example.invalid/template" />'
            "</Relationships>",
            "external relationship",
        ),
    ],
)
def test_docx_rejects_missing_malformed_and_active_package_parts(
    tmp_path: Path,
    content_types: str | None,
    document: str | None,
    relationship: str | None,
    message: str,
) -> None:
    path = tmp_path / "questionnaire.docx"
    _write_docx_parts(
        path,
        content_types=content_types,
        document=document,
        relationship=relationship,
    )

    with pytest.raises((SourceFormatError, SourceSecurityError), match=message):
        DocxAdapter().convert(resolve_local_source(path), limits=DEFAULT_SOURCE_LIMITS)


def test_docx_ignores_empty_paragraphs_and_tables(tmp_path: Path) -> None:
    path = tmp_path / "empty-parts.docx"
    document = f"""<w:document xmlns:w="{docling_source._WORD_NAMESPACE}"><w:body>
<w:p><w:r><w:t>   </w:t></w:r></w:p><w:tbl><w:tr /></w:tbl><w:bookmarkStart />
</w:body></w:document>"""
    _write_docx_parts(path, document=document)

    converted = DocxAdapter().convert(resolve_local_source(path), limits=DEFAULT_SOURCE_LIMITS)

    assert converted.blocks == ()


def test_docx_accepts_local_relationships(
    tmp_path: Path,
) -> None:
    path = tmp_path / "local-relationship.docx"
    document = f'<w:document xmlns:w="{docling_source._WORD_NAMESPACE}"><w:body/></w:document>'
    relationship = (
        f'<Relationships xmlns="{docling_source._RELATIONSHIP_NAMESPACE}">'
        '<Relationship Target="styles.xml" />'
        "</Relationships>"
    )
    _write_docx_parts(path, document=document, relationship=relationship)

    converted = DocxAdapter().convert(resolve_local_source(path), limits=DEFAULT_SOURCE_LIMITS)

    assert converted.blocks == ()


def test_docx_archive_read_errors_are_typed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "questionnaire.docx"
    _write_docx_parts(path, document="<document/>")
    source = resolve_local_source(path)
    monkeypatch.setattr(docling_source, "inspect_zip_archive", lambda _path, _limits: ())

    class BrokenArchive:
        def __init__(self, _path: Path) -> None:
            raise OSError

    monkeypatch.setattr(docling_source.zipfile, "ZipFile", BrokenArchive)
    with pytest.raises(SourceFormatError, match="could not be read"):
        DocxAdapter().convert(source, limits=DEFAULT_SOURCE_LIMITS)


def test_html_parser_handles_nested_blocked_content_and_empty_tables(tmp_path: Path) -> None:
    path = tmp_path / "questionnaire.html"
    path.write_text(
        "<script><style>hidden</style></script><table><tr></tr></table>"
        "<table><tr><td>Q1</td><th>Age</th></tr></table><p>End</p>",
        encoding="utf-8",
    )

    document = HtmlAdapter().convert(resolve_local_source(path), limits=DEFAULT_SOURCE_LIMITS)

    assert [block.kind for block in document.blocks] == ["table", "text"]
    assert "hidden" not in " ".join(block.text for block in document.blocks)


def test_html_parser_errors_are_typed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "questionnaire.html"
    path.write_text("<p>Question</p>", encoding="utf-8")

    class BrokenParser:
        events: list[tuple[str, object]] = []

        def feed(self, _text: str) -> None:
            raise ValueError("broken")

        def close(self) -> None:
            return None

    monkeypatch.setattr(docling_source, "_SafeHtmlParser", BrokenParser)
    with pytest.raises(SourceFormatError, match="could not be parsed"):
        HtmlAdapter().convert(resolve_local_source(path), limits=DEFAULT_SOURCE_LIMITS)


def test_markdown_tables_and_non_tables_preserve_content(tmp_path: Path) -> None:
    path = tmp_path / "questionnaire.md"
    path.write_text(
        "Preamble\n\n| code | label |\n| --- | --- |\n| Q1 | Age |\n\n"
        "not | a table\nstill | content\n",
        encoding="utf-8",
    )

    document = MarkdownAdapter().convert(resolve_local_source(path), limits=DEFAULT_SOURCE_LIMITS)

    assert [block.kind for block in document.blocks] == ["text", "table", "table"]
    assert document.tables[0].rows == (("code", "label"), ("Q1", "Age"))


def test_docling_helper_fallbacks_are_deterministic() -> None:
    class PositionalExporter:
        def export_to_markdown(self, *args: object, **kwargs: object) -> str:
            if kwargs:
                raise TypeError
            return "fallback"

    assert docling_source._docling_page(SimpleNamespace(prov=[])) is None
    assert docling_source._docling_page(SimpleNamespace(prov=[SimpleNamespace(page_no=0)])) is None
    assert docling_source._docling_pages(
        SimpleNamespace(prov=[SimpleNamespace(page_no=1), SimpleNamespace(page_no=2)])
    ) == (1, 2)
    assert (
        docling_source._docling_page_count(
            SimpleNamespace(input=SimpleNamespace(page_count=3)),
            SimpleNamespace(pages={1: object(), 3: object()}),
            [PdfConversionBlock(text="Page three", page=3)],
        )
        == 3
    )
    assert docling_source._docling_table_markdown(object(), object()) == ""
    assert docling_source._docling_table_markdown(PositionalExporter(), object()) == "fallback"
    assert docling_source._parse_markdown_table(["| --- | --- |", "| | |"]) == ()
    assert docling_source._events_to_blocks("empty.md", [("table", ())]) == ()


def test_html_parser_state_fallbacks_are_safe() -> None:
    parser = docling_source._SafeHtmlParser()

    parser.handle_starttag("template", [])
    parser.handle_starttag("div", [])
    parser.handle_endtag("div")
    parser.handle_endtag("template")
    parser.handle_endtag("script")
    parser.handle_starttag("table", [])
    parser.handle_starttag("table", [])
    parser.handle_starttag("span", [])
    parser.handle_data("orphaned table text")
    parser.handle_endtag("table")
    parser.handle_endtag("table")

    assert parser.events == []


def test_invalid_markdown_table_candidate_remains_text() -> None:
    assert docling_source._markdown_events("| |\n| |") == [("text", "| |\n| |")]


def test_pdf_worker_terminates_lingering_process_and_handles_interrupts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeQueue:
        def __init__(self, payload: object) -> None:
            self.payload = payload

        def get(self, *, timeout: float) -> object:
            del timeout
            if isinstance(self.payload, BaseException):
                raise self.payload
            return self.payload

        def close(self) -> None:
            return None

        def join_thread(self) -> None:
            return None

    class FakeProcess:
        def __init__(self, *, alive: bool = True) -> None:
            self.alive = alive
            self.terminated = False
            self.joined = False

        def start(self) -> None:
            return None

        def is_alive(self) -> bool:
            return self.alive and not self.terminated

        def terminate(self) -> None:
            self.terminated = True

        def join(self, timeout: float | None = None) -> None:
            del timeout
            self.joined = True

    class FakeContext:
        def __init__(self, payload: object, *, process_alive: bool = True) -> None:
            self.queue = FakeQueue(payload)
            self.process = FakeProcess(alive=process_alive)

        def Queue(self, *, maxsize: int) -> FakeQueue:
            assert maxsize == 1
            return self.queue

        def Process(self, **_kwargs: object) -> FakeProcess:
            return self.process

    conversion = PdfConversion(page_count=0, blocks=())
    context = FakeContext(("ok", "", conversion))
    monkeypatch.setattr(docling_source, "get_context", lambda _method: context)

    assert (
        docling_source._run_pdf_worker(
            fake_pdf_conversion,
            tmp_path / "questionnaire.pdf",
            artifacts_path=None,
            timeout=1,
        )
        == conversion
    )
    assert context.process.terminated is True
    assert context.process.joined is True

    interrupted = FakeContext(KeyboardInterrupt())
    monkeypatch.setattr(docling_source, "get_context", lambda _method: interrupted)
    with pytest.raises(KeyboardInterrupt):
        docling_source._run_pdf_worker(
            fake_pdf_conversion,
            tmp_path / "questionnaire.pdf",
            artifacts_path=None,
            timeout=1,
        )
    assert interrupted.process.terminated is True
    assert interrupted.process.joined is True

    finished_without_output = FakeContext(Empty(), process_alive=False)
    monkeypatch.setattr(docling_source, "get_context", lambda _method: finished_without_output)
    with pytest.raises(SourceTimeoutError):
        docling_source._run_pdf_worker(
            fake_pdf_conversion,
            tmp_path / "questionnaire.pdf",
            artifacts_path=None,
            timeout=1,
        )
    assert finished_without_output.process.terminated is False
    assert finished_without_output.process.joined is True

    finished_before_interrupt = FakeContext(KeyboardInterrupt(), process_alive=False)
    monkeypatch.setattr(docling_source, "get_context", lambda _method: finished_before_interrupt)
    with pytest.raises(KeyboardInterrupt):
        docling_source._run_pdf_worker(
            fake_pdf_conversion,
            tmp_path / "questionnaire.pdf",
            artifacts_path=None,
            timeout=1,
        )
    assert finished_before_interrupt.process.terminated is False
    assert finished_before_interrupt.process.joined is True


@pytest.mark.parametrize(
    ("page", "pages", "message"),
    [
        (True, (), "positive integers"),
        (None, (True,), "positive integers"),
        (None, (0,), "positive integers"),
        (None, (2, 1), "unique and ordered"),
        (None, (1, 1), "unique and ordered"),
        (2, (1, 2), "first provenance page"),
    ],
)
def test_pdf_conversion_block_rejects_invalid_page_states(
    page: int | None, pages: tuple[int, ...], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        PdfConversionBlock(text="Question", page=page, pages=pages)


def test_pdf_conversion_block_synchronizes_page_and_pages() -> None:
    from_page = PdfConversionBlock(text="Question", page=2)
    from_pages = PdfConversionBlock(text="Question", pages=(3, 4))

    assert (from_page.page, from_page.pages) == (2, (2,))
    assert (from_pages.page, from_pages.pages) == (3, (3, 4))


def _install_docling_result(
    monkeypatch: pytest.MonkeyPatch,
    result: object,
) -> None:
    class FakePipelineOptions:
        pass

    class FakeDocumentConverter:
        def __init__(self, **_kwargs: object) -> None:
            return None

        def convert(self, _path: str) -> object:
            return result

    modules = {
        "docling.backend.pypdfium2_backend": SimpleNamespace(PyPdfiumDocumentBackend=object()),
        "docling.datamodel.base_models": SimpleNamespace(InputFormat=SimpleNamespace(PDF="pdf")),
        "docling.datamodel.pipeline_options": SimpleNamespace(
            EasyOcrOptions=lambda **_kwargs: object(),
            PdfPipelineOptions=FakePipelineOptions,
        ),
        "docling.document_converter": SimpleNamespace(
            DocumentConverter=FakeDocumentConverter,
            PdfFormatOption=lambda **_kwargs: object(),
        ),
    }
    monkeypatch.setattr(docling_source, "import_module", modules.__getitem__)


class EmptyDoclingDocument:
    def __init__(self, page_count: int) -> None:
        self.pages = {page: object() for page in range(1, page_count + 1)}

    def iterate_items(self) -> tuple[tuple[object, int], ...]:
        return ()


@pytest.mark.parametrize(
    ("errors", "status", "message"),
    [
        ((SimpleNamespace(page_no=2),), "partial", "invalid failed-page metadata"),
        ((), SimpleNamespace(value="partial_success"), "incomplete without page coverage"),
    ],
)
def test_docling_converter_rejects_invalid_partial_states(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    errors: tuple[object, ...],
    status: object,
    message: str,
) -> None:
    result = SimpleNamespace(
        document=EmptyDoclingDocument(1),
        input=SimpleNamespace(page_count=1),
        errors=errors,
        status=status,
    )
    _install_docling_result(monkeypatch, result)
    artifacts = tmp_path / "ocr"
    artifacts.mkdir()

    with pytest.raises(SourceConversionError, match=message):
        DoclingConverter()(str(tmp_path / "questionnaire.pdf"), str(artifacts))


def test_docling_converter_builds_partial_coverage_from_all_error_page_forms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    errors = (
        SimpleNamespace(page_no=None, page=2, prov=()),
        SimpleNamespace(page_no=None, page=None, prov=(SimpleNamespace(page_no=3),)),
    )
    result = SimpleNamespace(
        document=EmptyDoclingDocument(3),
        input=SimpleNamespace(page_count=3),
        errors=errors,
        status="partial",
    )
    _install_docling_result(monkeypatch, result)
    artifacts = tmp_path / "ocr"
    artifacts.mkdir()

    conversion = DoclingConverter()(str(tmp_path / "questionnaire.pdf"), str(artifacts))

    assert conversion.coverage == SourceCoverage(
        unit="page",
        total_units=3,
        converted_units=(1,),
        failed_units=(2, 3),
    )
    assert tuple(diagnostic.unit_index for diagnostic in conversion.diagnostics) == (2, 3)


def test_docling_converter_preserves_a_zero_page_conversion_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = SimpleNamespace(
        document=EmptyDoclingDocument(0),
        input=SimpleNamespace(page_count=0),
        errors=(),
        status="success",
    )
    _install_docling_result(monkeypatch, result)
    artifacts = tmp_path / "ocr"
    artifacts.mkdir()

    conversion = DoclingConverter()(str(tmp_path / "questionnaire.pdf"), str(artifacts))

    assert conversion.page_count == 0
    assert conversion.blocks == ()
    assert conversion.coverage is None
    assert conversion.diagnostics == ()


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (SimpleNamespace(errors=(object(),), status="success"), True),
        (SimpleNamespace(errors=(), status=None), False),
        (SimpleNamespace(errors=(), status=SimpleNamespace(value="failure")), True),
        (SimpleNamespace(errors=(), status="success"), False),
    ],
)
def test_docling_incomplete_status_detection(result: object, expected: bool) -> None:
    assert docling_source._docling_conversion_incomplete(result) is expected


def test_docling_page_count_accepts_sequence_pages_and_ignores_boolean_report() -> None:
    result = SimpleNamespace(input=SimpleNamespace(page_count=True))
    document = SimpleNamespace(pages=[object(), object()])

    assert docling_source._docling_page_count(result, document, []) == 2


@pytest.mark.parametrize(
    ("conversion", "message"),
    [
        (
            PdfConversion(
                page_count=1,
                blocks=(PdfConversionBlock(text="Question", page=2),),
            ),
            "provenance exceeds",
        ),
        (
            PdfConversion(
                page_count=1,
                blocks=(),
                coverage=SourceCoverage(),
            ),
            "coverage does not match",
        ),
        (
            PdfConversion(
                page_count=1,
                blocks=(),
                coverage=SourceCoverage(
                    unit="page",
                    total_units=2,
                    converted_units=(1, 2),
                ),
            ),
            "coverage does not match",
        ),
    ],
)
def test_pdf_adapter_rejects_inconsistent_conversion_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    conversion: PdfConversion,
    message: str,
) -> None:
    path = tmp_path / "questionnaire.pdf"
    _write_pdf(path)
    monkeypatch.setattr(docling_source, "_run_pdf_worker", lambda *_args, **_kwargs: conversion)

    with pytest.raises(SourceConversionError, match=message):
        DoclingPdfAdapter(converter=fake_pdf_conversion).convert(
            resolve_local_source(path), limits=DEFAULT_SOURCE_LIMITS
        )


def test_pdf_adapter_uses_document_coverage_when_no_pages_are_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "empty.pdf"
    _write_pdf(path, b"1 0 obj <<>> endobj")
    conversion = PdfConversion(page_count=0, blocks=())
    monkeypatch.setattr(docling_source, "_run_pdf_worker", lambda *_args, **_kwargs: conversion)

    document = DoclingPdfAdapter(converter=fake_pdf_conversion).convert(
        resolve_local_source(path), limits=DEFAULT_SOURCE_LIMITS
    )

    assert document.coverage == SourceCoverage()
