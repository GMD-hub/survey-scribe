"""
Docling-based PDF Pre-processing Module
=========================================
Alternative to extractors/pdf.py that uses Docling (instead of
MarkItDown) to convert PDFs to Markdown before chunking by section.

Docling's OCR and table-structure models handle dense, image-heavy
questionnaires more robustly than MarkItDown, at the cost of being
slower. This module reuses the same DocumentChunk / chunk_markdown()
chunking logic as extractors/pdf.py, so it is a drop-in replacement
wherever process_pdf() is called (see pipeline_docling.py).

Reuses the PyPdfiumDocumentBackend fix already applied in fallback.py
and recognition/extractors/docling_convert.py: the default docling-parse
PDF backend has a known unresolved bug (docling-project/docling#3671)
that silently drops all pages after a native std::bad_alloc crash
partway through longer/denser PDFs, with no exception raised.
PyPdfiumDocumentBackend avoids the crash entirely.
"""
from __future__ import annotations

from pathlib import Path

from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption

from extractors.pdf import DocumentChunk, chunk_markdown, is_scanned_pdf

__all__ = ["DocumentChunk", "pdf_to_markdown", "process_pdf"]


# ── Conversion ────────────────────────────────────────────────────────────────

def pdf_to_markdown(pdf_path: Path) -> str:
    """
    Converts a PDF to Markdown using Docling.

    OCR and table-structure recognition are both enabled so scanned or
    image-only pages still yield extractable text, and answer-code
    tables are modeled as proper Markdown tables (same reason
    extractors/pdf.py uses MarkItDown rather than raw text extraction).

    Uses PyPdfiumDocumentBackend instead of Docling's default backend
    to avoid the std::bad_alloc page-loss bug described above.
    """
    pipeline_options = PdfPipelineOptions(
        do_ocr=True,
        do_table_structure=True,
        generate_page_images=False,
        generate_picture_images=False,
    )

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=pipeline_options,
                backend=PyPdfiumDocumentBackend,
            ),
        }
    )

    result = converter.convert(str(pdf_path))
    return result.document.export_to_markdown()


# ── Public entry point ────────────────────────────────────────────────────────

def process_pdf(pdf_path: Path) -> tuple[bool, list[DocumentChunk]]:
    """
    Full Docling-based pre-processing pipeline for one PDF questionnaire.

    Same contract as extractors.pdf.process_pdf(): returns
    (is_scanned, chunks). Scan detection still uses the cheap PyMuPDF
    text-layer check from extractors/pdf.py — Docling's OCR is capable
    of reading scanned pages, but OCR output quality remains out of
    scope for this pipeline, so scanned PDFs are still skipped here.
    """
    pdf_path = Path(pdf_path)

    if is_scanned_pdf(pdf_path):
        print(f"[SKIP] {pdf_path.name}  --  scanned PDF, OCR required.")
        return True, []

    try:
        markdown = pdf_to_markdown(pdf_path)
    except Exception as exc:
        print(f"[ERROR] {pdf_path.name}  --  Docling conversion failed: {exc}")
        return False, []

    chunks = chunk_markdown(markdown)
    print(f"[OK]   {pdf_path.name}  --  {len(chunks)} section(s) extracted.")
    return False, chunks
