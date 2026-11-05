"""PDF adapter contracts for local Docling configuration and worker isolation."""

from __future__ import annotations

import os
import socket
import time
import zipfile
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from queue import Empty
from types import SimpleNamespace
from typing import Any, cast

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
    PdfConversionOptions,
    PdfPage,
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


def crash_pdf_conversion(path: str, artifacts_path: str | None) -> PdfConversion:
    """Exit without queue output so parent sentinel handling is exercised."""
    del path, artifacts_path
    os._exit(87)


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


def _write_pdf(path: Path, page_count: int = 1) -> None:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument.new()
    try:
        for _ in range(page_count):
            document.new_page(612, 792)
        document.save(path)
    finally:
        document.close()


def _write_text_pdf(
    path: Path,
    page_texts: tuple[str | None, ...],
    images: dict[int, tuple[int, int]] | None = None,
) -> None:
    """A PDF with one line of Helvetica text on each page, so each page has a text layer.
    A ``None`` page points to an object that is not in the file, so the page cannot load.
    ``images`` maps a page number to the width and height of one gray image on that page."""
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        "<< /Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceGray "
        "/BitsPerComponent 8 /Length 1 >>\nstream\n\x80\nendstream",
    ]
    kids = []
    for number, text in enumerate(page_texts, start=1):
        if text is None:
            kids.append("99 0 R")
            continue
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
        if images and number in images:
            width, height = images[number]
            stream = f"q {width} 0 0 {height} 0 0 cm /Im1 Do Q {stream}"
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        objects.append(
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources "
            f"<< /Font << /F1 3 0 R >> /XObject << /Im1 4 0 R >> >> /Contents {len(objects)} 0 R >>"
        )
        kids.append(f"{len(objects)} 0 R")
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    data = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(data))
        data += f"{number} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(data)
    data += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    data += "".join(f"{offset:010d} 00000 n \n" for offset in offsets).encode()
    data += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode()
    data += f"startxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(data)


_QUESTION = "B1. How old were you on your last birthday? 1. Under 15 2. 15 or older"
# A white sheet as a scanner sees it: gray values from 230 to 255, no mark.
_LIGHT_NOISE = bytes(230 + (index * 7919) % 26 for index in range(64 * 64))
# The same sheet with one faded line of text: a dashed row at gray 225 across the page.
_FADED_LINE = bytes(
    225 if index // 64 == 20 and 8 <= index % 64 < 56 and index % 2 else value
    for index, value in enumerate(_LIGHT_NOISE)
)


def _gray_image(width: int, height: int, pixels: bytes) -> str:
    return (
        f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} "
        f"/ColorSpace /DeviceGray /BitsPerComponent 8 /Length {len(pixels)} >>\n"
        f"stream\n{pixels.decode('latin-1')}\nendstream"
    )


def _write_page_pdf(path: Path, pages: tuple[dict[str, Any] | None, ...]) -> None:
    """A PDF with one letter page for each spec; a ``None`` spec gives a page that cannot load.

    A spec can hold ``text`` (one line of 11-point Helvetica), ``color`` (the RGB color of the
    text), ``render`` (the text render mode; 3 is invisible text), ``image`` and ``box`` (a
    ``"gray"`` image, which is ink, a ``"noise"`` image, a white sheet with light noise, or a
    ``"faded"`` image, the same sheet with one faded line of text, drawn ``box`` points wide and
    high from the corner of the page), ``form_scale`` (the gray image sits 60 points square in a
    form XObject that the page scales by these factors) and ``lines`` (a grid of vector lines).
    An empty spec gives a blank page."""
    form_stream = "q 60 0 0 60 0 0 cm /Gray Do Q"
    images = {"gray": "/Gray", "noise": "/Noise", "faded": "/Faded"}
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        _gray_image(1, 1, b"\x80"),
        _gray_image(64, 64, _LIGHT_NOISE),
        "<< /Type /XObject /Subtype /Form /BBox [0 0 100 100] "
        f"/Resources << /XObject << /Gray 4 0 R >> >> /Length {len(form_stream)} >>\n"
        f"stream\n{form_stream}\nendstream",
        _gray_image(64, 64, _FADED_LINE),
    ]
    kids = []
    for spec in pages:
        if spec is None:
            kids.append("99 0 R")
            continue
        parts = []
        if "image" in spec:
            width, height = spec["box"]
            parts.append(f"q {width} 0 0 {height} 0 0 cm {images[spec['image']]} Do Q")
        if "form_scale" in spec:
            scale_x, scale_y = spec["form_scale"]
            parts.append(f"q {scale_x} 0 0 {scale_y} 0 0 cm /Form Do Q")
        if spec.get("lines"):
            rows = " ".join(f"72 {y} m 540 {y} l" for y in range(100, 600, 40))
            columns = " ".join(f"{x} 100 m {x} 580 l" for x in range(72, 600, 117))
            parts.append(f"0.75 w {rows} {columns} S")
        if "text" in spec:
            red, green, blue = spec.get("color", (0, 0, 0))
            parts.append(
                f"BT {red} {green} {blue} rg {spec.get('render', 0)} Tr /F1 11 Tf 72 720 Td "
                f"({spec['text']}) Tj ET"
            )
        stream = " ".join(parts)
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        objects.append(
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources "
            "<< /Font << /F1 3 0 R >> "
            "/XObject << /Gray 4 0 R /Noise 5 0 R /Form 6 0 R /Faded 7 0 R >> >> "
            f"/Contents {len(objects)} 0 R >>"
        )
        kids.append(f"{len(objects)} 0 R")
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    data = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(data))
        data += f"{number} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(data)
    data += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    data += "".join(f"{offset:010d} 00000 n \n" for offset in offsets).encode()
    data += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode()
    data += f"startxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(data)


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
    import fitz

    fitz_api = cast(Any, fitz)
    encrypted = tmp_path / "encrypted.pdf"
    encrypted_document = fitz_api.open()
    encrypted_document.new_page()
    encrypted_document.save(
        encrypted,
        encryption=fitz_api.PDF_ENCRYPT_AES_256,
        owner_pw="owner-secret",
        user_pw="user-secret",
    )
    encrypted_document.close()
    with pytest.raises(SourceSecurityError, match="encrypted"):
        DoclingPdfAdapter(converter=fake_pdf_conversion).convert(
            resolve_local_source(encrypted), limits=DEFAULT_SOURCE_LIMITS
        )

    too_many = tmp_path / "many-pages.pdf"
    _write_pdf(too_many, 3)
    with pytest.raises(SourceLimitError) as raised:
        DoclingPdfAdapter(converter=fake_pdf_conversion).convert(
            resolve_local_source(too_many),
            limits=replace(DEFAULT_SOURCE_LIMITS, max_pages=2),
        )
    assert raised.value.limit == "max_pages"

    token_only = tmp_path / "token-only.pdf"
    token_document = fitz_api.open()
    page = token_document.new_page()
    page.insert_text((72, 72), "/Encrypt is questionnaire text, not PDF security metadata")
    token_document.save(token_only)
    token_document.close()
    converted = DoclingPdfAdapter(converter=fake_pdf_conversion).convert(
        resolve_local_source(token_only), limits=DEFAULT_SOURCE_LIMITS
    )
    assert converted.blocks


def test_pdf_deadline_yields_stable_typed_error_and_worker_is_recreated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "questionnaire.pdf"
    _write_pdf(path)
    monkeypatch.setattr(docling_source, "_run_pdf_preflight", lambda *_args, **_kwargs: 1)
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


def test_crashed_pdf_worker_fails_before_the_configured_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "questionnaire.pdf"
    _write_pdf(path)
    monkeypatch.setattr(docling_source, "_run_pdf_preflight", lambda *_args, **_kwargs: 1)

    with pytest.raises(SourceConversionError, match="exited before returning"):
        DoclingPdfAdapter(converter=crash_pdf_conversion).convert(
            resolve_local_source(path),
            limits=replace(DEFAULT_SOURCE_LIMITS, deadline_seconds=20),
        )


def test_pdf_worker_blocks_network_even_for_an_injected_converter(tmp_path: Path) -> None:
    path = tmp_path / "questionnaire.pdf"
    _write_pdf(path)

    with pytest.raises(SourceConversionError, match="PDF conversion failed"):
        DoclingPdfAdapter(converter=network_pdf_conversion).convert(
            resolve_local_source(path),
            limits=replace(DEFAULT_SOURCE_LIMITS, deadline_seconds=10),
        )


@pytest.mark.skipif(
    not os.environ.get("DOCLING_ARTIFACTS_PATH"),
    reason="approved local OCR cache is not configured",
)
def test_real_docling_smoke_uses_validated_cache_with_worker_network_blocked(
    tmp_path: Path,
) -> None:
    """A text page, a blank page and a page with too little text: the real Docling reads the
    first page from the text layer, OCR reads the third page with the validated cache, and the
    blank page gets no read."""
    path = tmp_path / "questionnaire.pdf"
    _write_page_pdf(path, ({"text": _QUESTION}, {}, {"text": "Blank page"}))

    document = DoclingPdfAdapter().convert(
        resolve_local_source(path),
        limits=replace(DEFAULT_SOURCE_LIMITS, deadline_seconds=120),
    )

    assert document.media_type == "application/pdf"
    assert document.coverage.converted_units == (1, 3)
    assert document.coverage.blank_units == (2,)
    assert [(item.code, item.unit_index) for item in document.diagnostics] == [("PDF_PAGE_OCR", 3)]
    assert any(block.provenance.page == 1 for block in document.blocks)
    assert all(block.provenance.page != 2 for block in document.blocks)


@pytest.mark.parametrize("ocr", ["always", "auto", "never"])
@pytest.mark.parametrize("customize", [False, True])
def test_docling_configuration_uses_local_pdfium_and_disables_remote_services(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ocr: str, customize: bool
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

        def __init__(self) -> None:
            self.table_structure_options = SimpleNamespace(mode="accurate")

    class FakeEasyOcrOptions:
        def __init__(self, **kwargs: object) -> None:
            captured["ocr_kwargs"] = kwargs

    class FakePdfFormatOption:
        def __init__(self, **kwargs: object) -> None:
            captured["format_kwargs"] = kwargs

    class FakeHeadingHierarchyOptions:
        def __init__(self, **kwargs: object) -> None:
            captured["heading_kwargs"] = kwargs

    class FakeDocument:
        def iterate_items(self, **kwargs: object) -> list[tuple[object, int]]:
            captured["iterate_kwargs"] = kwargs
            item = SimpleNamespace(text="Short questionnaire", prov=[SimpleNamespace(page_no=1)])
            return [(item, 0)]

    class FakeDocumentConverter:
        def __init__(self, **kwargs: object) -> None:
            captured["converter_kwargs"] = kwargs

        def convert(self, path: str, **kwargs: object) -> object:
            captured["path"] = path
            captured.setdefault("page_ranges", []).append(kwargs.get("page_range"))
            return SimpleNamespace(document=FakeDocument())

    modules = {
        "docling.backend.pypdfium2_backend": SimpleNamespace(
            PyPdfiumDocumentBackend=FakePdfiumBackend
        ),
        "docling.datamodel.base_models": SimpleNamespace(InputFormat=SimpleNamespace(PDF="pdf")),
        "docling.datamodel.pipeline_options": SimpleNamespace(
            EasyOcrOptions=FakeEasyOcrOptions,
            PdfPipelineOptions=FakePipelineOptions,
            HeadingHierarchyOptions=FakeHeadingHierarchyOptions,
            TableFormerMode={"FAST": "fast"},
        ),
        "docling.document_converter": SimpleNamespace(
            DocumentConverter=FakeDocumentConverter,
            PdfFormatOption=FakePdfFormatOption,
        ),
        "docling_core.types.doc": SimpleNamespace(
            ContentLayer=SimpleNamespace(BODY="body", FURNITURE="furniture")
        ),
    }

    def fake_import(name: str) -> object:
        return modules[name]

    monkeypatch.setattr("survey_scribe.sources.docling.import_module", fake_import)
    artifacts = tmp_path / "ocr"
    artifacts.mkdir()
    monkeypatch.setattr(docling_source, "resolve_ocr_cache", lambda path: path.resolve())
    model_root = artifacts / "validated-models"
    model_root.mkdir()
    monkeypatch.setattr(
        docling_source,
        "validated_ocr_model_snapshot",
        lambda _path: nullcontext(model_root),
    )
    # The page check finds a text layer on page 1 and too little text on page 2, so "auto"
    # reads page 1 from the text layer and page 2 with OCR.
    monkeypatch.setattr(
        docling_source,
        "_pdf_pages",
        lambda _path: (_page(1, "machine_readable"), _page(2, "needs_ocr")),
    )
    if ocr == "never":

        def unexpected_ocr_cache(_path: Path) -> object:
            pytest.fail("text-layer conversion must not access the OCR cache")

        monkeypatch.setattr(docling_source, "resolve_ocr_cache", unexpected_ocr_cache)
        monkeypatch.setattr(docling_source, "validated_ocr_model_snapshot", unexpected_ocr_cache)
    options = docling_source.PdfConversionOptions(
        ocr=ocr,
        heading_levels=customize,
        max_heading_level=4,
        include_furniture=customize,
        table_mode="fast" if customize else "accurate",
    )
    conversion = DoclingConverter(options)(str(tmp_path / "questionnaire.pdf"), str(artifacts))

    format_kwargs = captured["format_kwargs"]
    assert isinstance(format_kwargs, dict)
    pipeline = format_kwargs["pipeline_options"]
    assert pipeline.do_ocr is (ocr != "never")
    assert pipeline.do_table_structure is True
    assert pipeline.enable_remote_services is False
    assert pipeline.artifacts_path == artifacts
    assert pipeline.table_structure_options.mode == options.table_mode
    if customize:
        assert pipeline.generate_parsed_pages is True
        assert captured["heading_kwargs"] == {"enabled": True, "max_level": 4}
        assert captured["iterate_kwargs"] == {"included_content_layers": {"body", "furniture"}}
    else:
        assert "heading_kwargs" not in captured
        assert captured["iterate_kwargs"] == {}
    if ocr == "never":
        assert "ocr_kwargs" not in captured
        assert pipeline.ocr_options is None
    else:
        # Every OCR read is a read of one page. Only "always" replaces the text layer.
        assert captured["ocr_kwargs"] == {
            "lang": ["en"],
            "force_full_page_ocr": ocr == "always",
            "model_storage_directory": str(model_root),
            "download_enabled": False,
        }
    assert (
        captured["page_ranges"]
        == {
            "always": [(1, 1), (2, 2)],
            "auto": [None, (2, 2)],
            "never": [None],
        }[ocr]
    )
    assert format_kwargs["backend"] is FakePdfiumBackend
    assert conversion.blocks[0].text == "Short questionnaire"
    assert conversion.blocks[0].page == 1
    assert os.environ.get("DOCLING_ARTIFACTS_PATH") != str(artifacts)


def test_docling_converter_requires_local_artifacts_and_installed_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    converter = DoclingConverter(PdfConversionOptions(ocr="always"))

    with pytest.raises(SourceDependencyError, match="not configured"):
        converter(str(tmp_path / "questionnaire.pdf"), None)
    with pytest.raises(SourceDependencyError, match="does not exist"):
        converter(str(tmp_path / "questionnaire.pdf"), str(tmp_path / "missing"))

    artifacts = tmp_path / "ocr"
    artifacts.mkdir()
    monkeypatch.setattr(docling_source, "_pdf_pages", lambda _path: (_page(1, "machine_readable"),))
    with pytest.raises(
        SourceDependencyError,
        match=r'OCR is required for PDF page 1 \(the OCR mode is "always"\)\. Configured OCR',
    ):
        converter(str(tmp_path / "questionnaire.pdf"), str(artifacts))

    monkeypatch.setattr(docling_source, "resolve_ocr_cache", lambda path: path.resolve())
    monkeypatch.setattr(
        docling_source,
        "validated_ocr_model_snapshot",
        lambda path: nullcontext(path),
    )

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

        def convert(self, _path: str, **_kwargs: object) -> object:
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
    monkeypatch.setattr(
        docling_source,
        "_pdf_pages",
        lambda _path: (_page(1, "machine_readable"), _page(2, "machine_readable")),
    )
    artifacts = tmp_path / "ocr"
    artifacts.mkdir()
    monkeypatch.setattr(docling_source, "resolve_ocr_cache", lambda path: path.resolve())
    monkeypatch.setattr(
        docling_source,
        "validated_ocr_model_snapshot",
        lambda path: nullcontext(path),
    )

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


def test_docling_converter_prefers_structured_rows_with_embedded_newlines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Frame:
        columns = ("code", "label")

        def itertuples(self, *, index: bool, name: object) -> tuple[tuple[str, str], ...]:
            assert index is False
            assert name is None
            return (("Q1", "first\nsecond"),)

    class StructuredTable:
        label = "table"
        prov = [SimpleNamespace(page_no=1)]

        def export_to_dataframe(self, *, doc: object) -> Frame:
            del doc
            return Frame()

        def export_to_markdown(self, **_kwargs: object) -> str:
            pytest.fail("structured table unexpectedly used Markdown fallback")

    document = SimpleNamespace(
        pages={1: object()},
        iterate_items=lambda: ((StructuredTable(), 0),),
    )
    result = SimpleNamespace(document=document, errors=(), status="success")
    _install_docling_result(monkeypatch, result)
    artifacts = tmp_path / "ocr"
    artifacts.mkdir()

    conversion = DoclingConverter()(str(tmp_path / "questionnaire.pdf"), str(artifacts))

    assert conversion.blocks[0].table_rows == (
        ("code", "label"),
        ("Q1", "first\nsecond"),
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


def test_docx_traverses_supported_nested_containers_in_document_order(tmp_path: Path) -> None:
    path = tmp_path / "nested-containers.docx"
    document = f"""<w:document xmlns:w="{docling_source._WORD_NAMESPACE}"><w:body>
<w:sdt><w:sdtPr/><w:sdtContent>
<w:p><w:r><w:t>Nested first</w:t></w:r></w:p>
<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Q1</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
</w:sdtContent></w:sdt>
<w:customXml><w:p><w:r><w:t>Nested after</w:t></w:r></w:p></w:customXml>
</w:body></w:document>"""
    _write_docx_parts(path, document=document)

    converted = DocxAdapter().convert(resolve_local_source(path), limits=DEFAULT_SOURCE_LIMITS)

    assert [block.text for block in converted.blocks] == ["Nested first", "Q1", "Nested after"]
    assert converted.tables[0].rows == (("Q1",),)
    assert converted.coverage.complete is True
    assert converted.diagnostics == ()


def test_docx_accounts_for_every_unsupported_nonempty_container(tmp_path: Path) -> None:
    path = tmp_path / "unsupported-containers.docx"
    document = f"""<w:document xmlns:w="{docling_source._WORD_NAMESPACE}"><w:body>
<w:p><w:r><w:t>Visible</w:t></w:r></w:p>
<w:altChunk w:val="part-1"/>
<w:unsupported><w:t>Hidden</w:t></w:unsupported>
</w:body></w:document>"""
    _write_docx_parts(path, document=document)

    converted = DocxAdapter().convert(resolve_local_source(path), limits=DEFAULT_SOURCE_LIMITS)

    assert [block.text for block in converted.blocks] == ["Visible"]
    assert converted.coverage.converted_units == ()
    assert converted.coverage.failed_units == (1,)
    assert [diagnostic.code for diagnostic in converted.diagnostics] == [
        "DOCX_CONTAINER_UNSUPPORTED",
        "DOCX_CONTAINER_UNSUPPORTED",
    ]


@pytest.mark.parametrize(
    ("limit_changes", "expected_limit"),
    [
        ({"max_xml_part_bytes": 100}, "max_xml_part_bytes"),
        ({"max_xml_elements": 10}, "max_xml_elements"),
        ({"max_xml_depth": 4}, "max_xml_depth"),
    ],
)
def test_docx_enforces_relevant_part_byte_and_element_limits(
    tmp_path: Path,
    limit_changes: dict[str, int],
    expected_limit: str,
) -> None:
    path = tmp_path / "bounded-document.docx"
    paragraphs = "".join(f"<w:p><w:r><w:t>Question {index}</w:t></w:r></w:p>" for index in range(8))
    document = (
        f'<w:document xmlns:w="{docling_source._WORD_NAMESPACE}"><w:body>'
        f"{paragraphs}</w:body></w:document>"
    )
    _write_docx_parts(path, document=document)

    with pytest.raises(SourceLimitError) as raised:
        DocxAdapter().convert(
            resolve_local_source(path),
            limits=replace(DEFAULT_SOURCE_LIMITS, **limit_changes),
        )

    assert raised.value.limit == expected_limit


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
    monkeypatch.setattr(
        docling_source,
        "inspect_zip_archive",
        lambda _path, _limits, **_kwargs: (),
    )

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

        def __init__(self, **_kwargs: object) -> None:
            return None

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


def test_markdown_table_parser_preserves_escaped_cell_content() -> None:
    rows = docling_source._parse_markdown_table(
        [
            "| code | expression | path | note |",
            "| --- | --- | --- | --- |",
            r"| Q\|1 | `left|right` | C:\survey\forms | first" + "\n" + "second |",
        ]
    )

    assert rows == (
        ("code", "expression", "path", "note"),
        ("Q|1", "`left|right`", r"C:\survey\forms", "first\nsecond"),
    )
    rendered = docling_source._events_to_blocks("questionnaire.md", [("table", rows)])[0]
    assert rendered.table is not None
    assert rendered.table.rows == rows
    assert r"Q\|1" in rendered.text
    assert r"C:\\survey\\forms" in rendered.text
    assert r"first\nsecond" in rendered.text


@pytest.mark.parametrize("source_kind", ["docx", "html", "markdown"])
def test_document_tables_enforce_one_cumulative_cell_limit(
    tmp_path: Path,
    source_kind: str,
) -> None:
    if source_kind == "docx":
        path = tmp_path / "tables.docx"
        document = f"""<w:document xmlns:w="{docling_source._WORD_NAMESPACE}"><w:body>
<w:tbl><w:tr><w:tc><w:p><w:r><w:t>A</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>B</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
<w:tbl><w:tr><w:tc><w:p><w:r><w:t>C</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>D</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
</w:body></w:document>"""
        _write_docx_parts(path, document=document)
        adapter = DocxAdapter()
    elif source_kind == "html":
        path = tmp_path / "tables.html"
        path.write_text(
            "<table><tr><td>A</td><td>B</td></tr></table>"
            "<table><tr><td>C</td><td>D</td></tr></table>",
            encoding="utf-8",
        )
        adapter = HtmlAdapter()
    else:
        path = tmp_path / "tables.md"
        path.write_text(
            "| A | B |\n| --- | --- |\n\n| C | D |\n| --- | --- |",
            encoding="utf-8",
        )
        adapter = MarkdownAdapter()

    with pytest.raises(SourceLimitError, match="cell limit") as raised:
        adapter.convert(
            resolve_local_source(path),
            limits=replace(DEFAULT_SOURCE_LIMITS, max_cells=3),
        )

    assert raised.value.limit == "max_cells"


def test_pdf_table_cell_limit_is_checked_before_worker_transfer(tmp_path: Path) -> None:
    path = tmp_path / "questionnaire.pdf"
    _write_pdf(path)

    with pytest.raises(SourceLimitError, match="cell limit") as raised:
        DoclingPdfAdapter(converter=table_pdf_conversion).convert(
            resolve_local_source(path),
            limits=replace(DEFAULT_SOURCE_LIMITS, max_cells=1, deadline_seconds=10),
        )

    assert raised.value.limit == "max_cells"


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


def test_markdown_and_html_headings_are_preserved_as_section_provenance(tmp_path: Path) -> None:
    markdown = tmp_path / "sections.md"
    markdown.write_text("# Roster\n\nQ1. Age", encoding="utf-8")
    markdown_document = MarkdownAdapter().convert(
        resolve_local_source(markdown),
        limits=DEFAULT_SOURCE_LIMITS,
    )
    assert markdown_document.blocks[-1].provenance.section_path == ("Roster",)

    html = tmp_path / "sections.html"
    html.write_text("<h2>Employment</h2><p>Q2. Work</p>", encoding="utf-8")
    html_document = HtmlAdapter().convert(
        resolve_local_source(html),
        limits=DEFAULT_SOURCE_LIMITS,
    )
    assert html_document.blocks[-1].provenance.section_path == ("Employment",)


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
        def __init__(self, *, alive: bool = True, terminate_effective: bool = True) -> None:
            self.alive = alive
            self.terminate_effective = terminate_effective
            self.terminated = False
            self.killed = False
            self.joined = False

        def start(self) -> None:
            return None

        def is_alive(self) -> bool:
            return (
                self.alive
                and not self.killed
                and not (self.terminated and self.terminate_effective)
            )

        def terminate(self) -> None:
            self.terminated = True

        def kill(self) -> None:
            self.killed = True

        def join(self, timeout: float | None = None) -> None:
            del timeout
            self.joined = True

    class FakeContext:
        def __init__(
            self,
            payload: object,
            *,
            process_alive: bool = True,
            terminate_effective: bool = True,
        ) -> None:
            self.queue = FakeQueue(payload)
            self.process = FakeProcess(
                alive=process_alive,
                terminate_effective=terminate_effective,
            )

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

    preflight_interrupted = FakeContext(KeyboardInterrupt())
    monkeypatch.setattr(docling_source, "get_context", lambda _method: preflight_interrupted)
    with pytest.raises(KeyboardInterrupt):
        docling_source._run_pdf_preflight(
            tmp_path / "questionnaire.pdf",
            max_pages=1,
            timeout=1,
        )
    assert preflight_interrupted.process.terminated is True
    assert preflight_interrupted.process.joined is True

    finished_without_output = FakeContext(Empty(), process_alive=False)
    monkeypatch.setattr(docling_source, "get_context", lambda _method: finished_without_output)
    with pytest.raises(SourceConversionError, match="exited before returning"):
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

    stubborn = FakeContext(("ok", "", conversion), terminate_effective=False)
    monkeypatch.setattr(docling_source, "get_context", lambda _method: stubborn)
    assert (
        docling_source._run_pdf_worker(
            fake_pdf_conversion,
            tmp_path / "questionnaire.pdf",
            artifacts_path=None,
            timeout=1,
        )
        == conversion
    )
    assert stubborn.process.terminated is True
    assert stubborn.process.killed is True


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


def _page(number: int, status: str, characters: int | None = None) -> PdfPage:
    """A page check record with plausible measurements for its status."""
    measurements = {
        "blank": (0, 0.0, 0.0),
        "machine_readable": (400, 0.0, 0.05),
        "needs_ocr": (0, 1.0, 0.3),
        "unreadable": (0, 0.0, 0.0),
    }[status]
    return PdfPage(
        number=number,
        status=cast(Any, status),
        characters=measurements[0] if characters is None else characters,
        image_share=measurements[1],
        ink_share=measurements[2],
    )


def _install_docling_result(
    monkeypatch: pytest.MonkeyPatch,
    result: object,
    *,
    pages: tuple[PdfPage, ...] | None = None,
    captured: dict[str, Any] | None = None,
    ocr_mode: bool = False,
) -> None:
    """Fake Docling modules for ``DoclingConverter``.

    ``result`` is the result of every read, or a mapping from the page range of a read
    (``None`` for the text-layer read of the whole file) to its result. ``pages`` is the page
    check; by default each page of the result is machine readable. ``captured["reads"]`` lists
    each read as ``("text" | "ocr", page_range)``, and ``captured["ocr_reads"]`` lists each OCR
    read as ``(page_range, "full_page" | "default")``. ``ocr_mode`` gives the fake Docling
    the ``OcrMode`` of later releases. As in Docling, a read with the status ``"failure"``
    raises unless the call passes ``raises_on_error=False``."""
    calls: dict[str, Any] = {} if captured is None else captured
    calls.setdefault("reads", [])
    calls.setdefault("ocr_reads", [])
    calls.setdefault("converters", [])
    calls.setdefault("ocr_kwargs", [])

    class FakePipelineOptions:
        pass

    class FakeDocumentConverter:
        def __init__(self, *, format_options: dict[str, Any]) -> None:
            (self.format_option,) = format_options.values()
            calls["converters"].append(self.format_option.pipeline_options.do_ocr)

        def convert(self, _path: str, **kwargs: Any) -> object:
            page_range = kwargs.get("page_range")
            pipeline_options = self.format_option.pipeline_options
            kind = "ocr" if pipeline_options.do_ocr else "text"
            calls["reads"].append((kind, page_range))
            if pipeline_options.do_ocr:
                ocr_options = vars(pipeline_options.ocr_options)
                full_page = ocr_options.get("mode") == "full_page" or ocr_options.get(
                    "force_full_page_ocr", False
                )
                calls["ocr_reads"].append((page_range, "full_page" if full_page else "default"))
            read = (
                cast(dict[Any, object], result)[page_range] if isinstance(result, dict) else result
            )
            if kwargs.get("raises_on_error", True) and getattr(read, "status", None) == "failure":
                raise RuntimeError("Conversion failed with status: failure")
            return read

    def easy_ocr_options(**kwargs: object) -> object:
        calls["ocr_kwargs"].append(kwargs)
        return SimpleNamespace(**kwargs)

    pipeline_module = SimpleNamespace(
        EasyOcrOptions=easy_ocr_options,
        PdfPipelineOptions=FakePipelineOptions,
    )
    if ocr_mode:
        pipeline_module.OcrMode = SimpleNamespace(FULL_PAGE="full_page")
    modules = {
        "docling.backend.pypdfium2_backend": SimpleNamespace(PyPdfiumDocumentBackend=object()),
        "docling.datamodel.base_models": SimpleNamespace(InputFormat=SimpleNamespace(PDF="pdf")),
        "docling.datamodel.pipeline_options": pipeline_module,
        "docling.document_converter": SimpleNamespace(
            DocumentConverter=FakeDocumentConverter,
            PdfFormatOption=lambda **kwargs: SimpleNamespace(**kwargs),
        ),
    }
    if pages is None:
        first = next(iter(result.values())) if isinstance(result, dict) else result
        document_pages = getattr(getattr(first, "document", None), "pages", ()) or ()
        reported = getattr(getattr(first, "input", None), "page_count", 0) or 0
        pages = tuple(
            _page(number, "machine_readable")
            for number in range(1, max(len(document_pages), reported) + 1)
        )
    page_check = pages
    monkeypatch.setattr(docling_source, "import_module", modules.__getitem__)
    monkeypatch.setattr(docling_source, "_pdf_pages", lambda _path: page_check)
    monkeypatch.setattr(docling_source, "resolve_ocr_cache", lambda path: path.resolve())
    monkeypatch.setattr(
        docling_source,
        "validated_ocr_model_snapshot",
        lambda path: nullcontext(path),
    )


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
    _write_pdf(path)
    conversion = PdfConversion(page_count=0, blocks=())
    monkeypatch.setattr(docling_source, "_run_pdf_preflight", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(docling_source, "_run_pdf_worker", lambda *_args, **_kwargs: conversion)

    document = DoclingPdfAdapter(converter=fake_pdf_conversion).convert(
        resolve_local_source(path), limits=DEFAULT_SOURCE_LIMITS
    )

    assert document.coverage == SourceCoverage()


def test_pdf_options_default_to_text_layer_first_reading() -> None:
    """The defaults run English OCR only on a page that needs it, with flat headings, body text
    only and accurate tables. The environment with no variables set gives the same options."""
    options = docling_source.PdfConversionOptions()
    assert (options.ocr, options.ocr_languages) == ("auto", ("en",))
    assert (options.heading_levels, options.max_heading_level) == (False, 6)
    assert (options.include_furniture, options.table_mode) == (False, "accurate")
    assert DoclingConverter().options == options
    assert docling_source.PdfConversionOptions.from_environment({}) == options


def test_pdf_options_reject_unknown_values() -> None:
    with pytest.raises(ValueError):
        docling_source.PdfConversionOptions(ocr="sometimes")
    with pytest.raises(ValueError):
        docling_source.PdfConversionOptions(table_mode="quick")
    with pytest.raises(ValueError):
        docling_source.PdfConversionOptions(ocr_languages=())
    with pytest.raises(ValueError):
        docling_source.PdfConversionOptions(max_heading_level=7)


@pytest.mark.parametrize("level", [True, 0, 1.5, "3", None])
def test_pdf_options_require_an_integer_heading_limit(level: Any) -> None:
    with pytest.raises(ValueError, match="must be an integer from 1 to 6"):
        docling_source.PdfConversionOptions(max_heading_level=level)


def test_pdf_options_reject_a_bare_language_string() -> None:
    with pytest.raises(ValueError, match="not a string"):
        docling_source.PdfConversionOptions(ocr_languages=cast(Any, "en"))


@pytest.mark.parametrize("ocr", ["always", "auto"])
def test_pdf_options_reject_ocr_languages_without_approved_models(ocr: str) -> None:
    with pytest.raises(ValueError, match="approved language-specific model artifacts"):
        docling_source.PdfConversionOptions(ocr=ocr, ocr_languages=("ru", "en"))


def test_pdf_options_read_the_environment_and_keep_defaults_for_unset_variables() -> None:
    options = docling_source.PdfConversionOptions.from_environment(
        {
            "SURVEY_SCRIBE_PDF_OCR": "never",
            "SURVEY_SCRIBE_PDF_OCR_LANGUAGES": "ru, en",
            "SURVEY_SCRIBE_PDF_HEADING_LEVELS": "yes",
            "SURVEY_SCRIBE_PDF_MAX_HEADING_LEVEL": "5",
            "SURVEY_SCRIBE_PDF_INCLUDE_FURNITURE": "1",
        }
    )
    assert options == docling_source.PdfConversionOptions(
        ocr="never",
        ocr_languages=("ru", "en"),
        heading_levels=True,
        max_heading_level=5,
        include_furniture=True,
    )
    with pytest.raises(ValueError):
        docling_source.PdfConversionOptions.from_environment(
            {"SURVEY_SCRIBE_PDF_HEADING_LEVELS": "maybe"}
        )
    with pytest.raises(ValueError):
        docling_source.PdfConversionOptions.from_environment(
            {"SURVEY_SCRIBE_PDF_MAX_HEADING_LEVEL": "deep"}
        )


def test_text_layer_only_reading_needs_no_ocr_cache_but_an_artifacts_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ocr="never"`` reads the text layer with the layout and table models alone: the EasyOCR
    archives are not validated, the artifacts directory still has to exist."""
    converter = DoclingConverter(docling_source.PdfConversionOptions(ocr="never"))
    with pytest.raises(SourceDependencyError, match="does not exist"):
        converter(str(tmp_path / "doc.pdf"), str(tmp_path / "missing"))
    not_directory = tmp_path / "not-directory"
    not_directory.touch()
    with pytest.raises(SourceDependencyError, match="not a directory"):
        converter(str(tmp_path / "doc.pdf"), str(not_directory))
    (tmp_path / "models").mkdir()

    def missing_module(_name: str) -> object:
        raise ModuleNotFoundError

    monkeypatch.setattr(docling_source, "import_module", missing_module)
    with pytest.raises(SourceDependencyError, match="optional 'pdf' dependencies"):
        converter(str(tmp_path / "doc.pdf"), str(tmp_path / "models"))


@pytest.mark.parametrize("needs_ocr", [False, True])
def test_auto_ocr_runs_only_when_a_page_needs_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, needs_ocr: bool
) -> None:
    """With no page that needs OCR, the converter runs no OCR and leaves the OCR cache alone.
    A page that needs OCR gets one OCR read of that page alone, not forced, and a warning."""
    captured: dict[str, Any] = {}
    result = SimpleNamespace(document=EmptyDoclingDocument(2))
    second = "needs_ocr" if needs_ocr else "machine_readable"
    pages = (_page(1, "machine_readable"), _page(2, second))
    _install_docling_result(monkeypatch, result, pages=pages, captured=captured)
    if not needs_ocr:

        def unexpected_ocr_cache(_path: Path) -> object:
            pytest.fail("a PDF with no page that needs OCR must not need the OCR cache")

        monkeypatch.setattr(docling_source, "resolve_ocr_cache", unexpected_ocr_cache)
        monkeypatch.setattr(docling_source, "validated_ocr_model_snapshot", unexpected_ocr_cache)
    artifacts = tmp_path / "models"
    artifacts.mkdir()

    conversion = DoclingConverter()(str(tmp_path / "questionnaire.pdf"), str(artifacts))

    if needs_ocr:
        assert captured["reads"] == [("text", None), ("ocr", (2, 2))]
        assert [kwargs["force_full_page_ocr"] for kwargs in captured["ocr_kwargs"]] == [False]
    else:
        assert captured["reads"] == [("text", None)]
        assert captured["ocr_kwargs"] == []
    assert [(item.code, item.severity, item.unit_index) for item in conversion.diagnostics] == (
        [("PDF_PAGE_OCR", "warning", 2)] if needs_ocr else []
    )


def test_pages_without_a_text_layer_are_named_when_ocr_artifacts_are_missing(
    tmp_path: Path,
) -> None:
    path = tmp_path / "questionnaire.pdf"
    _write_text_pdf(
        path,
        (
            "B1. How old were you on your last birthday? 1. Under 15 2. 15 or older",
            "Scanned copy, page 7",
            "B2. Did you do any work for pay in the last 7 days? 1. Yes 2. No",
        ),
    )
    assert [page.status for page in docling_source._pdf_pages(str(path))] == [
        "machine_readable",
        "needs_ocr",
        "machine_readable",
    ]
    artifacts = tmp_path / "models"
    artifacts.mkdir()

    with pytest.raises(SourceDependencyError, match=r"OCR is required for PDF page 2 \("):
        DoclingConverter()(str(path), str(artifacts))


def test_page_check_marks_a_page_that_cannot_load_as_unreadable(tmp_path: Path) -> None:
    """The page check gives a page that cannot load its own status and goes on to the next
    page. A page that holds only a one-digit page number has too little ink, so it is blank."""
    path = tmp_path / "questionnaire.pdf"
    _write_text_pdf(
        path,
        ("B1. How old were you on your last birthday? 1. Under 15 2. 15 or older", None, "7"),
    )

    pages = docling_source._pdf_pages(str(path))

    assert [page.status for page in pages] == ["machine_readable", "unreadable", "blank"]
    assert pages[1] == PdfPage(number=2, status="unreadable")


def test_page_check_flags_a_scanned_page_that_carries_a_text_stamp(tmp_path: Path) -> None:
    """A logo keeps a page of questions machine readable. A scan with a text stamp needs OCR."""
    path = tmp_path / "questionnaire.pdf"
    _write_text_pdf(
        path,
        (
            "B1. How old were you on your last birthday? 1. Under 15 2. 15 or older",
            "Labour Force Survey 2024, scanned copy, page 6 of 19",
        ),
        images={1: (60, 40), 2: (612, 792)},
    )

    assert [page.status for page in docling_source._pdf_pages(str(path))] == [
        "machine_readable",
        "needs_ocr",
    ]


def test_headings_keep_their_ancestors_by_level() -> None:
    """Every heading at level 1 (the layout model's default) gives a one-title path as before;
    inferred levels nest a sub-heading under its parent instead of replacing it."""
    push = docling_source._push_heading
    assert push((), 1, "Part I") == ((1, "Part I"),)
    assert push(((1, "Part I"),), 1, "Part II") == ((1, "Part II"),)
    assert push(((1, "Part I"),), 2, "1. Pensions") == ((1, "Part I"), (2, "1. Pensions"))
    assert push(((1, "Part I"), (2, "1. Pensions")), 3, "1.1 Amounts") == (
        (1, "Part I"),
        (2, "1. Pensions"),
        (3, "1.1 Amounts"),
    )
    assert push(((1, "Part I"), (2, "1. Pensions"), (3, "1.1 Amounts")), 2, "2. Presents") == (
        (1, "Part I"),
        (2, "2. Presents"),
    )


def test_skipped_heading_levels_do_not_make_siblings_into_ancestors() -> None:
    push = docling_source._push_heading
    skipped = push(((1, "Part I"),), 3, "Income")
    assert skipped == ((1, "Part I"), (3, "Income"))
    assert push(skipped, 3, "Expenditure") == ((1, "Part I"), (3, "Expenditure"))
    assert push(push((), 3, "Income"), 3, "Expenditure") == ((3, "Expenditure"),)


def test_pdf_heading_paths_and_question_numbers_survive_conversion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    items = (
        SimpleNamespace(label="section_header", text="Part I", level=1),
        SimpleNamespace(label="section_header", text="Income", level=3),
        SimpleNamespace(label="list_item", text="How much did you earn?", marker="8."),
        SimpleNamespace(label="section_header", text="Expenditure", level=3),
        SimpleNamespace(label="text", text="How much did you spend?"),
    )
    document = SimpleNamespace(pages={1: object()}, iterate_items=lambda: ((i, 0) for i in items))
    _install_docling_result(monkeypatch, SimpleNamespace(document=document))
    artifacts = tmp_path / "models"
    artifacts.mkdir()

    conversion = DoclingConverter(docling_source.PdfConversionOptions(ocr="never"))(
        str(tmp_path / "questionnaire.pdf"), str(artifacts)
    )

    assert conversion.blocks[2].text == "8. How much did you earn?"
    assert conversion.blocks[2].section_path == ("Part I", "Income")
    assert conversion.blocks[4].section_path == ("Part I", "Expenditure")


@pytest.mark.parametrize(
    ("options", "message"),
    [
        (docling_source.PdfConversionOptions(ocr="never", table_mode="fast"), "TableFormer"),
        (
            docling_source.PdfConversionOptions(ocr="never", heading_levels=True),
            "heading-hierarchy",
        ),
    ],
)
def test_pdf_options_report_missing_docling_stages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    options: docling_source.PdfConversionOptions,
    message: str,
) -> None:
    _install_docling_result(monkeypatch, SimpleNamespace(document=EmptyDoclingDocument(1)))
    artifacts = tmp_path / "models"
    artifacts.mkdir()

    with pytest.raises(SourceDependencyError, match=message):
        DoclingConverter(options)(str(tmp_path / "questionnaire.pdf"), str(artifacts))


def test_default_registry_passes_pdf_options_to_the_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from survey_scribe.sources.registry import SourceRegistry

    options = docling_source.PdfConversionOptions(ocr="auto", heading_levels=True)
    adapter = cast(Any, SourceRegistry.default(pdf_options=options)._adapters[".pdf"])
    assert cast(DoclingConverter, adapter._converter).options == options
    monkeypatch.setenv("SURVEY_SCRIBE_PDF_OCR", "never")
    adapter = cast(Any, SourceRegistry.default()._adapters[".pdf"])
    assert cast(DoclingConverter, adapter._converter).options.ocr == "never"


def blank_page_conversion(path: str, artifacts_path: str | None) -> PdfConversion:
    """Return a conversion whose second page is blank: no block, no diagnostic."""
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
            blank_units=(2,),
        ),
        pages=(_page(1, "machine_readable"), _page(2, "blank"), _page(3, "machine_readable")),
    )


def _item(label: str, text: str, page: int | None, level: int = 1) -> SimpleNamespace:
    provenance = [SimpleNamespace(page_no=page)] if page is not None else []
    return SimpleNamespace(label=label, text=text, level=level, prov=provenance)


class _TableItem:
    label = "table"

    def __init__(self, page: int) -> None:
        self.prov = [SimpleNamespace(page_no=page)]

    def export_to_markdown(self, *, doc: object) -> str:
        del doc
        return "| code | label |\n| --- | --- |"


def _read(page_count: int, items: tuple[object, ...], *, pages: tuple[int, ...] = ()) -> object:
    """A fake Docling result: the whole file, or with ``pages`` the pages of one page range."""
    document = SimpleNamespace(
        pages={page: object() for page in (pages or range(1, page_count + 1))},
        iterate_items=lambda: tuple((item, 0) for item in items),
    )
    return SimpleNamespace(
        document=document, input=SimpleNamespace(page_count=page_count), errors=(), status="success"
    )


def test_pdf_page_records_cross_the_worker_boundary() -> None:
    import pickle

    page = PdfPage(number=3, status="needs_ocr", characters=5, image_share=1, ink_share=0.25)

    assert pickle.loads(pickle.dumps(page)) == page
    assert page.image_share == 1.0 and isinstance(page.image_share, float)
    conversion = PdfConversion(page_count=3, blocks=(), pages=(page,))
    assert pickle.loads(pickle.dumps(conversion)) == conversion
    assert PdfConversion(page_count=0, blocks=()).pages == ()


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"number": 0}, "positive integer"),
        ({"number": True}, "positive integer"),
        ({"status": "scanned"}, "status must be one of"),
        ({"characters": -1}, "non-negative integer"),
        ({"characters": True}, "non-negative integer"),
        ({"image_share": 1.5}, "from 0 to 1"),
        ({"image_share": -0.1}, "from 0 to 1"),
        ({"ink_share": float("nan")}, "from 0 to 1"),
        ({"ink_share": True}, "from 0 to 1"),
        ({"status": "unreadable", "characters": 4}, "no measurements"),
        ({"status": "unreadable", "ink_share": 0.1}, "no measurements"),
    ],
)
def test_pdf_page_rejects_invalid_values(values: dict[str, Any], message: str) -> None:
    fields: dict[str, Any] = {
        "number": 1,
        "status": "machine_readable",
        "characters": 400,
        "image_share": 0.0,
        "ink_share": 0.05,
        **values,
    }
    with pytest.raises(ValueError, match=message):
        PdfPage(**fields)


@pytest.mark.parametrize(
    ("spec", "status"),
    [
        pytest.param({}, "blank", id="empty-page-is-blank"),
        pytest.param({"text": _QUESTION}, "machine_readable", id="text-page"),
        pytest.param({"image": "noise", "box": (612, 792)}, "blank", id="white-scan-with-noise"),
        pytest.param(
            {"image": "faded", "box": (612, 792)}, "needs_ocr", id="faded-scan-with-one-line"
        ),
        pytest.param({"text": "7"}, "blank", id="page-number-only"),
        pytest.param(
            {"text": "Section C: Employment", "color": (0.7, 0.7, 0.7)},
            "needs_ocr",
            id="short-light-gray-line",
        ),
        pytest.param(
            {"text": _QUESTION, "color": (1, 1, 0)}, "machine_readable", id="yellow-text-layer"
        ),
        pytest.param(
            {"text": _QUESTION, "render": 3}, "machine_readable", id="invisible-text-layer"
        ),
        pytest.param({"text": "A" * 31, "render": 3}, "blank", id="31-invisible-characters"),
        pytest.param(
            {"text": "A" * 32, "render": 3}, "machine_readable", id="32-invisible-characters"
        ),
        pytest.param(
            {"image": "gray", "box": (612, 792), "text": _QUESTION},
            "needs_ocr",
            id="scan-with-a-long-text-stamp",
        ),
        pytest.param(
            {"image": "gray", "box": (612, 396), "text": _QUESTION},
            "needs_ocr",
            id="image-over-exactly-half",
        ),
        pytest.param(
            {"image": "gray", "box": (612, 390), "text": _QUESTION},
            "machine_readable",
            id="image-under-half",
        ),
        pytest.param({"text": "A" * 31}, "needs_ocr", id="31-characters"),
        pytest.param({"text": "A" * 32}, "machine_readable", id="32-characters"),
        pytest.param({"text": "Blank page"}, "needs_ocr", id="short-text-with-some-ink"),
        pytest.param({"lines": True}, "needs_ocr", id="vector-lines-no-text"),
        pytest.param(
            {"form_scale": (10, 13.2), "text": _QUESTION}, "needs_ocr", id="scaled-form-image"
        ),
        pytest.param(
            {"form_scale": (1, 1), "text": _QUESTION}, "machine_readable", id="small-form-image"
        ),
        pytest.param(None, "unreadable", id="page-does-not-load"),
    ],
)
def test_page_check_gives_each_status_by_its_rule(
    tmp_path: Path, spec: dict[str, Any] | None, status: str
) -> None:
    """Each rule in both directions: the blank test first, then an image over half the page,
    then fewer than 32 visible characters, else a text layer. A faded line on a white scan and a
    short line of light text have enough ink to need OCR. A text layer of 32 or more visible
    characters is never blank, also when its text is too light or invisible for the render."""
    path = tmp_path / "page.pdf"
    _write_page_pdf(path, (spec, {"text": _QUESTION}))

    pages = docling_source._pdf_pages(str(path))

    assert [page.number for page in pages] == [1, 2]
    assert pages[0].status == status
    assert pages[1].status == "machine_readable"


def test_blank_test_comes_before_the_image_rule(tmp_path: Path) -> None:
    """A scan of a white sheet covers the whole page, but it has no ink, so it is blank and not
    a page for OCR."""
    path = tmp_path / "white-scan.pdf"
    _write_page_pdf(path, ({"image": "noise", "box": (612, 792)},))

    (page,) = docling_source._pdf_pages(str(path))

    assert (page.status, page.characters, page.image_share, page.ink_share) == (
        "blank",
        0,
        1.0,
        0.0,
    )


def test_page_check_measures_an_image_in_a_scaled_form_at_its_size_on_the_page(
    tmp_path: Path,
) -> None:
    """The image is 60 points square inside the form. The page scales the form by 10 and 13.2,
    so the image covers 600 by 792 points: 98 percent of the page, not 0.7 percent."""
    path = tmp_path / "form.pdf"
    _write_page_pdf(
        path,
        ({"form_scale": (10, 13.2), "text": _QUESTION}, {"form_scale": (1, 1), "text": _QUESTION}),
    )

    scaled, unscaled = docling_source._pdf_pages(str(path))

    assert scaled.image_share == pytest.approx(600 * 792 / (612 * 792), rel=1e-4)
    assert unscaled.image_share == pytest.approx(60 * 60 / (612 * 792), rel=1e-4)


def test_reading_plan_gives_each_page_one_read_in_each_mode() -> None:
    pages = (
        _page(1, "blank"),
        _page(2, "machine_readable"),
        _page(3, "needs_ocr"),
        _page(4, "unreadable"),
    )

    assert docling_source._reading_plan(pages, "auto") == ((2,), (3,))
    assert docling_source._reading_plan(pages, "always") == ((), (2, 3))
    assert docling_source._reading_plan(pages, "never") == ((2, 3), ())


def test_blank_page_never_reaches_ocr_in_the_always_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}
    reads = {
        (1, 1): _read(3, (_item("text", "Q1. Age", 1),), pages=(1,)),
        (3, 3): _read(3, (_item("text", "Q3. Sex", 3),), pages=(3,)),
    }
    pages = (_page(1, "machine_readable"), _page(2, "blank"), _page(3, "needs_ocr"))
    _install_docling_result(monkeypatch, reads, pages=pages, captured=captured)
    artifacts = tmp_path / "models"
    artifacts.mkdir()

    conversion = DoclingConverter(PdfConversionOptions(ocr="always"))(
        str(tmp_path / "questionnaire.pdf"), str(artifacts)
    )

    assert captured["reads"] == [("ocr", (1, 1)), ("ocr", (3, 3))]
    assert [(block.text, block.page) for block in conversion.blocks] == [
        ("Q1. Age", 1),
        ("Q3. Sex", 3),
    ]
    assert conversion.coverage == SourceCoverage(
        unit="page", total_units=3, converted_units=(1, 3), blank_units=(2,)
    )
    assert [(item.code, item.unit_index, item.message) for item in conversion.diagnostics] == [
        ("PDF_PAGE_OCR", 1, 'OCR read this PDF page because the OCR mode is "always"'),
        (
            "PDF_PAGE_OCR",
            3,
            "OCR read this PDF page because one image covers half of the page or more",
        ),
    ]
    assert conversion.pages == pages


def test_ocr_page_items_merge_in_page_order_and_their_heading_reaches_later_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The text-layer read keeps pages 1 and 3 and drops its items on page 2, which OCR reads.
    The heading that OCR finds on page 2 is the section of the questions on page 3."""
    captured: dict[str, Any] = {}
    reads = {
        None: _read(
            3,
            (
                _item("section_header", "Part A", 1),
                _item("text", "Q1. Age", 1),
                _item("text", "scanner stamp", 2),
                _item("text", "Q3. Sex", 3),
            ),
        ),
        (2, 2): _read(
            3,
            (_item("section_header", "Part B", 2), _item("text", "Q2. Marital status", 2)),
            pages=(2,),
        ),
    }
    pages = (_page(1, "machine_readable"), _page(2, "needs_ocr"), _page(3, "machine_readable"))
    _install_docling_result(monkeypatch, reads, pages=pages, captured=captured)
    artifacts = tmp_path / "models"
    artifacts.mkdir()

    conversion = DoclingConverter()(str(tmp_path / "questionnaire.pdf"), str(artifacts))

    assert captured["reads"] == [("text", None), ("ocr", (2, 2))]
    assert [(block.text, block.page, block.section_path) for block in conversion.blocks] == [
        ("Part A", 1, ("Part A",)),
        ("Q1. Age", 1, ("Part A",)),
        ("Part B", 2, ("Part B",)),
        ("Q2. Marital status", 2, ("Part B",)),
        ("Q3. Sex", 3, ("Part B",)),
    ]
    assert conversion.coverage == SourceCoverage(
        unit="page", total_units=3, converted_units=(1, 2, 3)
    )


def test_merge_keeps_the_order_of_the_text_layer_read() -> None:
    """With no OCR page the merge gives the single read unchanged, even where the read is not
    in page order, and an item with no page stays where it is."""
    entry = docling_source._DoclingItem
    text_items = [
        entry(_item("text", "a", 2), None, (2,), 2),
        entry(_item("text", "b", None), None, (), None),
        entry(_item("text", "c", 1), None, (1,), 1),
    ]
    ocr_items = {3: [entry(_item("text", "d", 3), None, (3,), 3)]}

    assert docling_source._merge_page_items(text_items, {}) == text_items
    assert [item.item.text for item in docling_source._merge_page_items(text_items, ocr_items)] == [
        "a",
        "b",
        "c",
        "d",
    ]


def _joined_item(
    label: str, parts: tuple[tuple[int, str], ...], *, spans: bool = True, marker: str = ""
) -> SimpleNamespace:
    """A Docling item that joins text across page breaks: one provenance entry for each part,
    with the character span of the part in the joined text when ``spans`` is true."""
    provenance = []
    start = 0
    for page, text in parts:
        span = {"charspan": (start, start + len(text))} if spans else {}
        provenance.append(SimpleNamespace(page_no=page, **span))
        start += len(text) + 1
    text = " ".join(text for _page, text in parts)
    return SimpleNamespace(label=label, text=text, marker=marker, level=1, prov=provenance)


@pytest.mark.parametrize("spans", [True, False])
def test_item_that_runs_from_an_ocr_page_onto_a_text_page_keeps_its_text_layer_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spans: bool
) -> None:
    """Docling can join a stamp at the foot of a scanned page to the first paragraph of the next
    page. A real read of the combined probe file did this to its page 6. The item is cut at the
    page break: the stamp on the OCR page 2 goes, because OCR reads page 2, and the text of
    page 3 stays at page 3. With no character spans the item cannot be cut, so it stays whole
    after the OCR items of page 2, and the text of page 3 is not lost."""
    reads = {
        None: _read(
            3,
            (
                _item("text", "Q1. Age", 1),
                _joined_item("text", ((2, "scan stamp"), (3, "Q3. Sex")), spans=spans),
            ),
        ),
        (2, 2): _read(3, (_item("text", "Q2. Work", 2),), pages=(2,)),
    }
    pages = (_page(1, "machine_readable"), _page(2, "needs_ocr"), _page(3, "machine_readable"))
    _install_docling_result(monkeypatch, reads, pages=pages)
    artifacts = tmp_path / "models"
    artifacts.mkdir()

    conversion = DoclingConverter()(str(tmp_path / "questionnaire.pdf"), str(artifacts))

    assert [(block.text, block.pages) for block in conversion.blocks] == [
        ("Q1. Age", (1,)),
        ("Q2. Work", (2,)),
        ("Q3. Sex", (3,)) if spans else ("scan stamp Q3. Sex", (2, 3)),
    ]


def test_item_joined_across_an_ocr_page_is_cut_so_the_ocr_heading_reaches_its_later_part(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The text-layer read finds no text on the scanned page 2, so Docling joins the last list
    item of page 1 to the first paragraph of page 3. The item is cut at the page breaks. Each
    part goes to its own page, so the heading that OCR finds on page 2 is the section of the
    part on page 3. Only the first part keeps the list marker."""
    reads = {
        None: _read(
            3,
            (
                _item("section_header", "SECTION J. HEALTH", 1),
                _joined_item(
                    "list_item",
                    ((1, "Any illness? 1. Yes 2. No"), (3, "Read the text to the respondent.")),
                    marker="J4.",
                ),
                _item("text", "K1. Where were you born?", 3),
            ),
        ),
        (2, 2): _read(
            3,
            (
                _item("section_header", "SECTION K. MIGRATION", 2),
                _item("text", "Introduction to the migration questions", 2),
            ),
            pages=(2,),
        ),
    }
    pages = (_page(1, "machine_readable"), _page(2, "needs_ocr"), _page(3, "machine_readable"))
    _install_docling_result(monkeypatch, reads, pages=pages)
    artifacts = tmp_path / "models"
    artifacts.mkdir()

    conversion = DoclingConverter()(str(tmp_path / "questionnaire.pdf"), str(artifacts))

    j = ("SECTION J. HEALTH",)
    k = ("SECTION K. MIGRATION",)
    assert [(block.text, block.pages, block.section_path) for block in conversion.blocks] == [
        ("SECTION J. HEALTH", (1,), j),
        ("J4. Any illness? 1. Yes 2. No", (1,), j),
        ("SECTION K. MIGRATION", (2,), k),
        ("Introduction to the migration questions", (2,), k),
        ("Read the text to the respondent.", (3,), k),
        ("K1. Where were you born?", (3,), k),
    ]


def test_item_joined_across_text_layer_pages_stays_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An item that joins two text-layer pages crosses no page of another read. It stays one
    block over both pages, as in the single read of the base."""
    reads = {
        None: _read(
            3,
            (
                _joined_item("text", ((1, "The household roster lists"), (2, "every member."))),
                _item("text", "Q2. Age", 2),
            ),
        ),
        (3, 3): _read(3, (_item("text", "Q3. Work", 3),), pages=(3,)),
    }
    pages = (_page(1, "machine_readable"), _page(2, "machine_readable"), _page(3, "needs_ocr"))
    _install_docling_result(monkeypatch, reads, pages=pages)
    artifacts = tmp_path / "models"
    artifacts.mkdir()

    conversion = DoclingConverter()(str(tmp_path / "questionnaire.pdf"), str(artifacts))

    assert [(block.text, block.pages) for block in conversion.blocks] == [
        ("The household roster lists every member.", (1, 2)),
        ("Q2. Age", (2,)),
        ("Q3. Work", (3,)),
    ]


@pytest.mark.parametrize(
    ("item", "parts"),
    [
        pytest.param(
            _joined_item("text", ((1, "first"), (3, "third"))),
            ((1, "first"), (3, "third")),
            id="one-part-for-each-page",
        ),
        pytest.param(
            SimpleNamespace(
                label="text",
                text="left column right column next page",
                prov=[
                    SimpleNamespace(page_no=1, charspan=(0, 11)),
                    SimpleNamespace(page_no=1, charspan=(12, 24)),
                    SimpleNamespace(page_no=2, charspan=(25, 34)),
                ],
            ),
            ((1, "left column right column"), (2, "next page")),
            id="two-spans-on-one-page",
        ),
        pytest.param(
            SimpleNamespace(
                label="text",
                text="employment",
                prov=[
                    SimpleNamespace(page_no=1, charspan=(0, 7)),
                    SimpleNamespace(page_no=2, charspan=(8, 12)),
                ],
            ),
            (),
            id="hyphenated-word-span-outside-the-text",
        ),
        pytest.param(
            _joined_item("text", ((3, "third"), (1, "first"))), (), id="pages-out-of-order"
        ),
        pytest.param(
            _joined_item("text", ((1, "first"), (3, "third")), spans=False), (), id="no-spans"
        ),
        pytest.param(
            _joined_item("table", ((1, "first"), (3, "third"))), (), id="table-is-not-cut"
        ),
    ],
)
def test_page_parts_cut_an_item_only_by_valid_spans(item: object, parts: object) -> None:
    assert docling_source._page_parts(item) == parts


@pytest.mark.parametrize(("max_cells", "fails"), [("3", True), ("4", False)])
def test_table_cell_limit_carries_across_both_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, max_cells: str, fails: bool
) -> None:
    """A table of two cells on a text-layer page and one on an OCR page count together."""
    reads = {
        None: _read(2, (_TableItem(1),)),
        (2, 2): _read(2, (_TableItem(2),), pages=(2,)),
    }
    pages = (_page(1, "machine_readable"), _page(2, "needs_ocr"))
    _install_docling_result(monkeypatch, reads, pages=pages)
    monkeypatch.setenv("SURVEY_SCRIBE_PDF_MAX_CELLS", max_cells)
    artifacts = tmp_path / "models"
    artifacts.mkdir()
    converter = DoclingConverter()

    if fails:
        with pytest.raises(SourceLimitError, match="cell limit"):
            converter(str(tmp_path / "questionnaire.pdf"), str(artifacts))
    else:
        conversion = converter(str(tmp_path / "questionnaire.pdf"), str(artifacts))
        assert [block.pages for block in conversion.blocks] == [(1,), (2,)]


def test_blank_page_is_missing_from_the_blocks_with_no_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reads = {
        None: _read(
            3,
            (
                _item("text", "Q1. Age", 1),
                _item("text", "stray mark", 2),
                _item("text", "Q3. Sex", 3),
            ),
        )
    }
    pages = (_page(1, "machine_readable"), _page(2, "blank"), _page(3, "machine_readable"))
    _install_docling_result(monkeypatch, reads, pages=pages)
    artifacts = tmp_path / "models"
    artifacts.mkdir()

    conversion = DoclingConverter()(str(tmp_path / "questionnaire.pdf"), str(artifacts))

    assert [block.page for block in conversion.blocks] == [1, 3]
    assert conversion.coverage == SourceCoverage(
        unit="page", total_units=3, converted_units=(1, 3), blank_units=(2,)
    )
    assert conversion.diagnostics == ()


def test_pdf_adapter_keeps_blank_pages_in_the_coverage_with_no_failure(tmp_path: Path) -> None:
    from survey_scribe.pipeline import _source_diagnostics, _source_failures
    from survey_scribe.routing.pipeline import _coverage_failures

    path = tmp_path / "questionnaire.pdf"
    _write_pdf(path, 3)

    document = DoclingPdfAdapter(converter=blank_page_conversion).convert(
        resolve_local_source(path), limits=replace(DEFAULT_SOURCE_LIMITS, deadline_seconds=10)
    )

    assert document.coverage.blank_units == (2,)
    assert document.coverage.failed_units == ()
    assert document.coverage.complete is True
    assert document.diagnostics == ()
    assert [block.provenance.page for block in document.blocks] == [1, 3]
    assert _source_failures(document) == ()
    assert _source_diagnostics(document) == ()
    assert _coverage_failures(document) == ()


def test_never_mode_warns_once_for_a_page_that_needs_ocr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}
    reads = {None: _read(3, (_item("text", "Q1. Age", 1), _item("text", "7", 2)))}
    pages = (_page(1, "machine_readable"), _page(2, "needs_ocr", characters=5), _page(3, "blank"))
    _install_docling_result(monkeypatch, reads, pages=pages, captured=captured)

    def unexpected_ocr_cache(_path: Path) -> object:
        pytest.fail("the never mode must not need the OCR cache")

    monkeypatch.setattr(docling_source, "resolve_ocr_cache", unexpected_ocr_cache)
    monkeypatch.setattr(docling_source, "validated_ocr_model_snapshot", unexpected_ocr_cache)
    artifacts = tmp_path / "models"
    artifacts.mkdir()

    conversion = DoclingConverter(PdfConversionOptions(ocr="never"))(
        str(tmp_path / "questionnaire.pdf"), str(artifacts)
    )

    assert captured["reads"] == [("text", None)]
    assert [block.text for block in conversion.blocks] == ["Q1. Age", "7"]
    assert [(item.code, item.severity, item.unit_index) for item in conversion.diagnostics] == [
        ("PDF_PAGE_TEXT_INCOMPLETE", "warning", 2)
    ]
    assert conversion.diagnostics[0].message == (
        "The text of this PDF page can be incomplete because OCR is off and one image covers "
        "half of the page or more"
    )
    assert conversion.coverage is not None
    assert conversion.coverage.blank_units == (3,)


def test_unreadable_page_is_failed_and_gets_no_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}
    reads = {(1, 1): _read(2, (_item("text", "Q1. Age", 1),), pages=(1,))}
    pages = (_page(1, "machine_readable"), _page(2, "unreadable"))
    _install_docling_result(monkeypatch, reads, pages=pages, captured=captured)
    artifacts = tmp_path / "models"
    artifacts.mkdir()

    conversion = DoclingConverter(PdfConversionOptions(ocr="always"))(
        str(tmp_path / "questionnaire.pdf"), str(artifacts)
    )

    assert captured["reads"] == [("ocr", (1, 1))]
    assert conversion.coverage == SourceCoverage(
        unit="page", total_units=2, converted_units=(1,), failed_units=(2,)
    )
    assert [(item.code, item.severity, item.unit_index) for item in conversion.diagnostics] == [
        ("PDF_PAGE_OCR", "warning", 1),
        ("PDF_PAGE_CONVERSION_FAILED", "error", 2),
    ]


def test_a_read_failure_counts_only_on_a_page_that_the_read_keeps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The text-layer read fails on page 2, but OCR reads page 2, so page 2 converts. When the
    OCR read of page 2 fails too, page 2 fails and gets no OCR warning. As in Docling, the
    failed read of one page has the status "failure" and an empty document; page 1 stays."""
    text_read = SimpleNamespace(
        document=SimpleNamespace(pages={1: object(), 2: object()}, iterate_items=lambda: ()),
        input=SimpleNamespace(page_count=2),
        errors=(SimpleNamespace(page_no=2),),
        status="partial_success",
    )
    ocr_read = _read(2, (_item("text", "Q2. Sex", 2),), pages=(2,))
    failed_ocr_read = SimpleNamespace(
        document=SimpleNamespace(pages={}, iterate_items=lambda: ()),
        input=SimpleNamespace(page_count=2),
        errors=(SimpleNamespace(page_no=2),),
        status="failure",
    )
    pages = (_page(1, "machine_readable"), _page(2, "needs_ocr"))
    artifacts = tmp_path / "models"
    artifacts.mkdir()

    _install_docling_result(monkeypatch, {None: text_read, (2, 2): ocr_read}, pages=pages)
    converted = DoclingConverter()(str(tmp_path / "questionnaire.pdf"), str(artifacts))
    _install_docling_result(monkeypatch, {None: text_read, (2, 2): failed_ocr_read}, pages=pages)
    failed = DoclingConverter()(str(tmp_path / "questionnaire.pdf"), str(artifacts))

    assert converted.coverage == SourceCoverage(unit="page", total_units=2, converted_units=(1, 2))
    assert [item.code for item in converted.diagnostics] == ["PDF_PAGE_OCR"]
    assert failed.coverage == SourceCoverage(
        unit="page", total_units=2, converted_units=(1,), failed_units=(2,)
    )
    assert [item.code for item in failed.diagnostics] == ["PDF_PAGE_CONVERSION_FAILED"]


@pytest.mark.parametrize("ocr", ["auto", "always"])
def test_a_failed_read_of_one_page_fails_only_that_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ocr: str
) -> None:
    """Docling gives the status "failure" when every page of a read fails, so the failed OCR
    read of page 2 raises in Docling unless the call passes ``raises_on_error=False``. Page 2
    then fails alone and the blocks of page 1 stay, as in the single read of the base."""
    captured: dict[str, Any] = {}
    failed_read = SimpleNamespace(
        document=SimpleNamespace(pages={}, iterate_items=lambda: ()),
        input=SimpleNamespace(page_count=2),
        errors=(SimpleNamespace(page_no=2),),
        status="failure",
    )
    page_one = _read(2, (_item("text", "Q1. Age", 1),))
    reads = {None: page_one, (1, 1): page_one, (2, 2): failed_read}
    pages = (_page(1, "machine_readable"), _page(2, "needs_ocr"))
    _install_docling_result(monkeypatch, reads, pages=pages, captured=captured)
    artifacts = tmp_path / "models"
    artifacts.mkdir()

    conversion = DoclingConverter(PdfConversionOptions(ocr=ocr))(
        str(tmp_path / "questionnaire.pdf"), str(artifacts)
    )

    assert captured["reads"][-1] == ("ocr", (2, 2))
    assert [block.text for block in conversion.blocks] == ["Q1. Age"]
    assert conversion.coverage == SourceCoverage(
        unit="page", total_units=2, converted_units=(1,), failed_units=(2,)
    )
    assert [(item.code, item.unit_index) for item in conversion.diagnostics][-1] == (
        "PDF_PAGE_CONVERSION_FAILED",
        2,
    )


def test_a_failed_read_with_no_failed_page_still_stops_the_conversion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A read that fails with no page in its errors, such as a crash of the Docling pipeline,
    does not tell which pages it lost, so the conversion stops."""
    failed_read = SimpleNamespace(
        document=SimpleNamespace(pages={}, iterate_items=lambda: ()),
        input=SimpleNamespace(page_count=2),
        errors=(SimpleNamespace(page_no=None, page=None, prov=()),),
        status="failure",
    )
    reads = {None: _read(2, (_item("text", "Q1. Age", 1),)), (2, 2): failed_read}
    pages = (_page(1, "machine_readable"), _page(2, "needs_ocr"))
    _install_docling_result(monkeypatch, reads, pages=pages)
    artifacts = tmp_path / "models"
    artifacts.mkdir()

    with pytest.raises(SourceConversionError, match="incomplete without page coverage"):
        DoclingConverter()(str(tmp_path / "questionnaire.pdf"), str(artifacts))


@pytest.mark.parametrize(
    ("status", "error_pages", "converted", "failed"),
    [
        ("failure", (2, None), None, None),
        ("partial_success", (2, None), (1,), (2,)),
        ("failure", (1, 2), (), (1, 2)),
    ],
)
def test_a_failed_read_stops_the_conversion_unless_its_errors_name_every_page_of_the_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    error_pages: tuple[int | None, ...],
    converted: tuple[int, ...] | None,
    failed: tuple[int, ...] | None,
) -> None:
    """The text-layer read of two pages fails on page 2, and then the Docling pipeline stops
    after its page loop: the read has the status "failure" and an error with no page. The read
    lost page 1 too, so the conversion stops, as the single read did. A partial success with
    the same errors fails only page 2. A failure that names every page of the read fails those
    pages."""
    errors = tuple(SimpleNamespace(page_no=page, page=None, prov=()) for page in error_pages)
    read = SimpleNamespace(
        document=SimpleNamespace(pages={}, iterate_items=lambda: ()),
        input=SimpleNamespace(page_count=2),
        errors=errors,
        status=status,
    )
    pages = (_page(1, "machine_readable"), _page(2, "machine_readable"))
    _install_docling_result(monkeypatch, {None: read}, pages=pages)
    artifacts = tmp_path / "models"
    artifacts.mkdir()
    converter = DoclingConverter()

    if converted is None:
        with pytest.raises(SourceConversionError, match="failed on pages that it does not name"):
            converter(str(tmp_path / "questionnaire.pdf"), str(artifacts))
        return
    conversion = converter(str(tmp_path / "questionnaire.pdf"), str(artifacts))

    assert conversion.coverage == SourceCoverage(
        unit="page", total_units=2, converted_units=converted, failed_units=failed
    )


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("failure", True),
        (SimpleNamespace(value="failure"), True),
        ("skipped", True),
        ("success", False),
        ("partial", False),
        (SimpleNamespace(value="partial_success"), False),
        (None, False),
    ],
)
def test_docling_failed_read_status_detection(status: object, expected: bool) -> None:
    assert docling_source._docling_read_failed(SimpleNamespace(status=status)) is expected


def test_auto_ocr_reads_use_one_default_mode_converter_for_all_ocr_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In the "auto" mode a later Docling with ``OcrMode`` gets no ``mode``, so OCR runs in the
    Docling default mode. Docling builds one converter for the text layer and one for OCR, and
    the OCR converter reads each page alone."""
    captured: dict[str, Any] = {}
    reads = {
        None: _read(3, (_item("text", "Q3. Sex", 3),)),
        (1, 1): _read(3, (_item("text", "Q1. Age", 1),), pages=(1,)),
        (2, 2): _read(3, (_item("text", "Q2. Work", 2),), pages=(2,)),
    }
    pages = (_page(1, "needs_ocr"), _page(2, "needs_ocr"), _page(3, "machine_readable"))
    _install_docling_result(monkeypatch, reads, pages=pages, captured=captured, ocr_mode=True)
    artifacts = tmp_path / "models"
    artifacts.mkdir()

    conversion = DoclingConverter()(str(tmp_path / "questionnaire.pdf"), str(artifacts))

    assert captured["converters"] == [False, True]
    assert captured["reads"] == [("text", None), ("ocr", (1, 1)), ("ocr", (2, 2))]
    assert captured["ocr_kwargs"] == [
        {
            "lang": ["en"],
            "model_storage_directory": str(artifacts.resolve()),
            "download_enabled": False,
        }
    ]
    assert [block.text for block in conversion.blocks] == ["Q1. Age", "Q2. Work", "Q3. Sex"]


@pytest.mark.parametrize("ocr_mode", [False, True])
def test_auto_ocr_keeps_the_text_layer_of_every_page_that_needs_ocr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ocr_mode: bool
) -> None:
    """Pages 1 and 4 have a full text layer over one image of the whole page, such as a scan
    with an OCR text layer. Pages 2 and 3 have too little text. OCR reads each page in the
    Docling default mode, so a text layer stays. The message of a page with no text layer does
    not say that its text layer stays. One converter serves every OCR page."""
    captured: dict[str, Any] = {}
    reads = {
        (number, number): _read(4, (_item("text", f"Q{number}.", number),), pages=(number,))
        for number in range(1, 5)
    }
    pages = (
        _page(1, "needs_ocr", characters=400),
        _page(2, "needs_ocr"),
        PdfPage(number=3, status="needs_ocr", characters=31, image_share=0.0, ink_share=0.01),
        _page(4, "needs_ocr", characters=32),
    )
    _install_docling_result(monkeypatch, reads, pages=pages, captured=captured, ocr_mode=ocr_mode)
    artifacts = tmp_path / "models"
    artifacts.mkdir()

    conversion = DoclingConverter()(str(tmp_path / "questionnaire.pdf"), str(artifacts))

    assert captured["ocr_reads"] == [
        ((1, 1), "default"),
        ((2, 2), "default"),
        ((3, 3), "default"),
        ((4, 4), "default"),
    ]
    assert captured["converters"] == [True]
    default_mode = {} if ocr_mode else {"force_full_page_ocr": False}
    assert [
        {key: value for key, value in kwargs.items() if key in ("mode", "force_full_page_ocr")}
        for kwargs in captured["ocr_kwargs"]
    ] == [default_mode]
    assert [block.text for block in conversion.blocks] == ["Q1.", "Q2.", "Q3.", "Q4."]
    text_layer_stays = (
        "OCR read the areas of this PDF page that have no text layer because one image covers "
        "half of the page or more, and the text layer of the page stays"
    )
    assert [(item.unit_index, item.message) for item in conversion.diagnostics] == [
        (1, text_layer_stays),
        (2, "OCR read this PDF page because one image covers half of the page or more"),
        (
            3,
            "OCR read the areas of this PDF page that have no text layer because the text layer "
            "has fewer than 32 visible characters, and the text layer of the page stays",
        ),
        (4, text_layer_stays),
    ]


@pytest.mark.parametrize("ocr_mode", [False, True])
def test_always_mode_runs_full_page_ocr_on_a_page_with_a_full_text_layer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ocr_mode: bool
) -> None:
    """The "always" mode ignores the text layer, also on a scan with an OCR text layer. A later
    Docling with ``OcrMode`` gets ``mode=FULL_PAGE``, and an earlier one force_full_page_ocr."""
    captured: dict[str, Any] = {}
    reads = {
        (number, number): _read(2, (_item("text", f"Q{number}.", number),), pages=(number,))
        for number in (1, 2)
    }
    pages = (_page(1, "needs_ocr", characters=400), _page(2, "machine_readable"))
    _install_docling_result(monkeypatch, reads, pages=pages, captured=captured, ocr_mode=ocr_mode)
    artifacts = tmp_path / "models"
    artifacts.mkdir()

    conversion = DoclingConverter(PdfConversionOptions(ocr="always"))(
        str(tmp_path / "questionnaire.pdf"), str(artifacts)
    )

    assert captured["ocr_reads"] == [((1, 1), "full_page"), ((2, 2), "full_page")]
    assert captured["converters"] == [True]
    full_page = {"mode": "full_page"} if ocr_mode else {"force_full_page_ocr": True}
    assert [
        {key: value for key, value in kwargs.items() if key in ("mode", "force_full_page_ocr")}
        for kwargs in captured["ocr_kwargs"]
    ] == [full_page]
    assert [(item.unit_index, item.message) for item in conversion.diagnostics] == [
        (1, "OCR read this PDF page because one image covers half of the page or more"),
        (2, 'OCR read this PDF page because the OCR mode is "always"'),
    ]


def test_no_easyocr_files_are_needed_when_no_page_needs_ocr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real page check finds two text pages and a blank page, so the read needs only the
    layout models: the real OCR cache check of the empty directory never runs."""
    from survey_scribe.sources import ocr as ocr_source

    path = tmp_path / "questionnaire.pdf"
    _write_page_pdf(path, ({"text": _QUESTION}, {}, {"text": _QUESTION}))
    pages = docling_source._pdf_pages(str(path))
    captured: dict[str, Any] = {}
    reads = {None: _read(3, (_item("text", "Q1. Age", 1), _item("text", "Q3. Sex", 3)))}
    _install_docling_result(monkeypatch, reads, pages=pages, captured=captured)
    monkeypatch.setattr(docling_source, "resolve_ocr_cache", ocr_source.resolve_ocr_cache)
    monkeypatch.setattr(
        docling_source, "validated_ocr_model_snapshot", ocr_source.validated_ocr_model_snapshot
    )
    artifacts = tmp_path / "models"
    artifacts.mkdir()

    conversion = DoclingConverter()(str(path), str(artifacts))

    assert [page.status for page in pages] == ["machine_readable", "blank", "machine_readable"]
    assert captured["reads"] == [("text", None)]
    assert conversion.coverage == SourceCoverage(
        unit="page", total_units=3, converted_units=(1, 3), blank_units=(2,)
    )


def test_missing_easyocr_files_name_the_pages_that_need_ocr(tmp_path: Path) -> None:
    """The real page check sends pages 2 and 4 to OCR. The blank page 5 needs no OCR, so the
    error does not name it."""
    path = tmp_path / "questionnaire.pdf"
    _write_page_pdf(
        path,
        (
            {"text": _QUESTION},
            {"text": "Blank page"},
            {"text": _QUESTION},
            {"image": "gray", "box": (612, 792)},
            {},
        ),
    )
    artifacts = tmp_path / "models"
    artifacts.mkdir()

    with pytest.raises(
        SourceDependencyError,
        match=r"OCR is required for PDF pages 2, 4 \(too little text or an image over half the "
        r"page\)\. Configured OCR cache",
    ):
        DoclingConverter()(str(path), str(artifacts))


def test_docling_page_count_must_match_the_page_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_docling_result(monkeypatch, _read(2, ()), pages=(_page(1, "machine_readable"),))
    artifacts = tmp_path / "models"
    artifacts.mkdir()

    with pytest.raises(SourceConversionError, match="more pages than the page check"):
        DoclingConverter()(str(tmp_path / "questionnaire.pdf"), str(artifacts))
