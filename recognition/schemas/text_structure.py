"""
Text Structure Schema
=======================
Pydantic models for the output of the Text Structure Agent
(agents/text_agent.py).

This is a deliberately separate schema from schemas/svis.py at the
repo root. That schema describes *survey variables*; this one describes
*document structure* (pages, headings, language) and is not specific to
questionnaires at all.

The `language` / `language_confidence` fields on TextBlock are reserved
for the planned Language Agent (not built yet). They are always None
until that agent runs and fills them in on the same TextBlock records
produced here.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class TextBlock(BaseModel):
    """
    One text unit from the document (a paragraph, list item, heading,
    caption, footnote, etc.) — one Docling TextItem.
    """

    block_id: int
    # Stable position of this block within the document's reading order.
    # Used to re-merge this record with output from other agents
    # (e.g. the Language Agent) that process the same block list.

    page: int
    # 1-indexed PDF page number this block appears on.
    # 0 if Docling could not determine provenance for this block.

    label: str
    # Docling's item label, e.g. "text", "section_header", "list_item",
    # "caption", "footnote", "page_header", "page_footer".

    heading_level: Optional[int] = None
    # Heading depth if this block is a heading (0 = document title,
    # 1 = top-level section header, 2 = subsection, ...).
    # None for body text (paragraphs, list items, etc.).

    parent_path: list[str] = Field(default_factory=list)
    # Text of every ancestor heading currently "open" at this point in
    # the document, shallowest first.
    # Example: ["Section 3: Education", "3.2 School attendance"]
    # Empty list if this block appears before any heading.

    text: str
    # The block's text content, stripped of leading/trailing whitespace.

    char_count: int
    # len(text) — convenience field for filtering very short/noisy blocks
    # without re-parsing text downstream.

    language: Optional[str] = None
    # Reserved for the planned Language Agent. ISO 639-1 code
    # (e.g. "en", "fr") once populated. Always None for now.

    language_confidence: Optional[float] = None
    # Reserved for the planned Language Agent. 0.0-1.0. Always None for now.


class DocumentTextStructure(BaseModel):
    """
    Full text-structure extraction result for one PDF.
    Written as JSON by recognition/pipeline.py.
    """

    source_file: str
    # Filename of the source PDF (not the full path).

    page_count: int
    # Total number of pages Docling parsed.

    blocks: list[TextBlock]
    # All text blocks in reading order. See TextBlock above.

    primary_language: Optional[str] = None
    # ISO 639-1 code of the language accounting for the most tagged
    # characters across all blocks (a document-level summary of the
    # per-block TextBlock.language tags). Set by the Language Agent's
    # compute_primary_language(). None if no blocks were confidently
    # tagged with a language.

    extraction_date: date

    extraction_notes: Optional[str] = None
    # Free-text notes, e.g. if OCR was required or a page failed to parse.
