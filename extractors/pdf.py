"""
PDF Pre-processing Module
==========================
Three responsibilities:
  1. Detect whether a PDF has a text layer (digital-native) or is a
     scanned image (requires OCR — out of scope for PoC).
  2. Convert digital PDFs to structured Markdown using MarkItDown.
  3. Split the Markdown into one chunk per questionnaire section/module.

Why MarkItDown rather than raw PyMuPDF text extraction?
  Raw PyMuPDF returns positional text that scrambles tables.
  Tables of answer codes and labels are the most important piece
  of information for mapping categorical variables. MarkItDown
  preserves them as Markdown tables, which the LLM handles well.
  It also preserves section headings, which drive chunking.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF — used only for scan detection
from markitdown import MarkItDown


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class DocumentChunk:
    """
    One semantic section of a questionnaire, ready for LLM processing.
    Produced by chunk_markdown() and consumed by the extraction agents.
    """
    module_name: str      # section/module title from the Markdown heading
    text: str             # Markdown text of this section
    page_start: int       # PDF page where this section begins (0-indexed)
    chunk_index: int      # position of this chunk in the document (0-indexed)


# ── Scan detection ────────────────────────────────────────────────────────────

_MIN_TEXT_CHARS = 50
# A page with fewer than this many characters is treated as image-only.
# Adjust downward if some text-bearing pages are being wrongly flagged.


def is_scanned_pdf(pdf_path: Path, sample_pages: int = 5) -> bool:
    """
    Returns True if the PDF appears to be a scanned image document
    with no extractable text layer.

    Checks the first `sample_pages` pages. If at least one page yields
    more than _MIN_TEXT_CHARS characters, the document is treated as
    digital-native. This handles the common case where the cover page
    is a logo image but subsequent pages have text.

    A fully scanned PDF cannot be processed without OCR, which is
    out of scope for the current PoC.
    """
    doc = fitz.open(str(pdf_path))
    pages_to_check = min(sample_pages, len(doc))

    for i in range(pages_to_check):
        text = doc[i].get_text().strip()
        if len(text) > _MIN_TEXT_CHARS:
            return False

    return True


# ── Conversion ────────────────────────────────────────────────────────────────

def pdf_to_markdown(pdf_path: Path) -> str:
    """
    Converts a PDF to Markdown using MarkItDown.

    MarkItDown attempts to preserve document structure including:
      - Headings (## Section 3: Education)
      - Tables (answer codes and labels)
      - Numbered and bulleted lists
      - Bold and italic text (question text is often bold)

    Returns the full Markdown string for the entire document.
    Raises an exception if conversion fails entirely.
    """
    converter = MarkItDown()
    result = converter.convert(str(pdf_path))
    return result.text_content


# ── Chunking ──────────────────────────────────────────────────────────────────

# Matches Markdown headings at levels 1, 2, or 3 (# ## ###)
_HEADING_RE = re.compile(r'^#{1,3}\s+(.+)$', re.MULTILINE)

# Sections shorter than this (in characters) are skipped.
# Covers blank sections, image-only pages that extracted as whitespace, etc.
_MIN_CHUNK_CHARS = 100


def chunk_markdown(markdown_text: str) -> list[DocumentChunk]:
    """
    Splits a Markdown document into one chunk per section heading.

    Strategy:
      Primary: detect ## or ### headings and split at each one.
      Fallback: if no headings found, return the whole document as one chunk.

    Each chunk's module_name is the heading text. This is important:
    the module name travels with the chunk through the pipeline and
    becomes the `module` field in each extracted SurveyVariable.
    It provides semantic context that improves harmonization accuracy
    (a variable named 'educ' inside an "Education" module is more
    clearly mappable than an unnamed variable in an "Other" module).

    Note on page tracking: MarkItDown does not reliably report which
    page each heading came from. page_start is therefore set to 0
    for all chunks in this version. This is a known limitation.
    """
    matches = list(_HEADING_RE.finditer(markdown_text))

    if not matches:
        # Fallback: no headings detected — treat whole document as one chunk
        text = markdown_text.strip()
        if len(text) < _MIN_CHUNK_CHARS:
            return []
        return [DocumentChunk(
            module_name="full_document",
            text=text,
            page_start=0,
            chunk_index=0,
        )]

    chunks: list[DocumentChunk] = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown_text)
        section_text = markdown_text[start:end].strip()

        if len(section_text) < _MIN_CHUNK_CHARS:
            continue   # skip trivially short sections

        chunks.append(DocumentChunk(
            module_name=match.group(1).strip(),
            text=section_text,
            page_start=0,            # page tracking: future improvement
            chunk_index=len(chunks),
        ))

    return chunks


# ── Public entry point ────────────────────────────────────────────────────────

def process_pdf(pdf_path: Path) -> tuple[bool, list[DocumentChunk]]:
    """
    Full pre-processing pipeline for one PDF questionnaire.

    Returns:
        (is_scanned, chunks)

        is_scanned  True if the PDF cannot be processed without OCR.
                    The pipeline should log this and skip the file.

        chunks      List of DocumentChunk objects, one per questionnaire
                    section, ready for the LLM extraction agent.
                    Empty list if is_scanned is True.

    Usage:
        is_scanned, chunks = process_pdf(Path("questionnaire.pdf"))
        if is_scanned:
            print("Cannot process — OCR required")
        else:
            for chunk in chunks:
                variables = extract_variables_from_chunk(chunk)
    """
    pdf_path = Path(pdf_path)

    if is_scanned_pdf(pdf_path):
        print(f"[SKIP] {pdf_path.name}  —  scanned PDF, OCR required.")
        return True, []

    try:
        markdown = pdf_to_markdown(pdf_path)
    except Exception as exc:
        print(f"[ERROR] {pdf_path.name}  —  MarkItDown conversion failed: {exc}")
        return False, []

    chunks = chunk_markdown(markdown)
    print(f"[OK]   {pdf_path.name}  —  {len(chunks)} section(s) extracted.")
    return False, chunks
