"""
PDF -> DoclingDocument conversion
===================================
Converts a PDF into a Docling `DoclingDocument` object -- not Markdown.

Unlike extractors/pdf.py at the repo root (which exports straight to
Markdown for the SVIS pipeline), the recognition sub-project needs the
structured DoclingDocument itself: its `.texts` / `.tables` / `.pictures`
collections carry per-item page number (via `.prov`) and heading level
that Markdown export throws away.

Reuses the PyPdfiumDocumentBackend fix already applied in fallback.py
at the repo root: the default `docling-parse` PDF backend has a known
unresolved bug (docling-project/docling#3671) where it silently drops
all pages after a native std::bad_alloc crash partway through longer or
denser PDFs, with no exception raised. PyPdfiumDocumentBackend avoids
the crash entirely.
"""
from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF -- only for a cheap page-count lookup, not text extraction
from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc.document import DoclingDocument

# Default character budget for convert_pdf(). Full OCR + table-structure
# conversion of the survey PDFs in tests/samples/surveys (14-28+ pages)
# takes 1-2+ minutes. During development/testing of new agents, converting
# the whole document on every run is wasteful -- capping at a small
# character budget keeps iteration fast. Pass max_chars=None to convert the
# entire document (real pipeline runs should do this).
DEFAULT_MAX_CHARS = 4000


def convert_pdf(
    pdf_path: Path,
    do_ocr: bool = True,
    max_chars: int | None = DEFAULT_MAX_CHARS,
) -> DoclingDocument:
    """
    Converts a PDF into a DoclingDocument.

    do_ocr=True by default so scanned or image-only pages still yield
    extractable text items (mirrors the fallback.py default at the repo
    root). Table structure recognition is left on so table regions are
    correctly modeled as TableItem instances and excluded from the text
    walk in agents/text_agent.py, rather than leaking into text blocks.
    generate_picture_images is left on so each PictureItem carries a
    rendered image (as an in-memory PNG) for the Image Agent
    (agents/image_agent.py) to save to disk; generate_page_images stays
    off since nothing in this sub-project needs full-page renders.

    max_chars caps how much of the document gets converted:
      - None converts the entire PDF (use for real runs).
      - Otherwise (default 4000), pages are converted one at a time,
        starting from page 1, stopping as soon as the cumulative text
        length across all text items reaches max_chars or the document
        ends -- whichever comes first. This avoids paying Docling's full
        OCR/table-structure cost on a 100+ page document just to exercise
        the first few thousand characters of it.

    Raises whatever exception Docling raises on unrecoverable conversion
    failure (e.g. a corrupt file); callers should catch and log.
    """
    pdf_path = Path(pdf_path)

    pipeline_options = PdfPipelineOptions(
        do_ocr=do_ocr,
        do_table_structure=True,
        generate_page_images=False,
        generate_picture_images=True,
    )

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=pipeline_options,
                backend=PyPdfiumDocumentBackend,
            ),
        }
    )

    if max_chars is None:
        result = converter.convert(str(pdf_path))
        return result.document

    with fitz.open(str(pdf_path)) as pdf:
        total_pages = pdf.page_count

    end_page = 1
    while True:
        result = converter.convert(str(pdf_path), page_range=(1, end_page))
        doc = result.document
        total_chars = sum(len(item.text) for item in doc.texts)
        if total_chars >= max_chars or end_page >= total_pages:
            return doc
        end_page += 1
