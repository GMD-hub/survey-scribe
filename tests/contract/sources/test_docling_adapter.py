"""PDF adapter contracts for local Docling configuration and worker isolation."""

from __future__ import annotations

import os
import socket
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from survey_scribe.sources.base import (
    DEFAULT_SOURCE_LIMITS,
    SourceConversionError,
    SourceLimitError,
    SourceSecurityError,
    SourceTimeoutError,
    resolve_local_source,
)
from survey_scribe.sources.docling import (
    DoclingConverter,
    DoclingPdfAdapter,
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
