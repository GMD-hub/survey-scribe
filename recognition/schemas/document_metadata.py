"""
Document Metadata Schema
==========================
Pydantic model for the combined output of recognition/pipeline.py --
merges the Text Structure, Image, and Table Agents' output into one
JSON file per PDF, instead of three separate files.

This is purely a merge/convenience layer: each nested structure
(`text`, `images`, `tables`) is exactly what its own agent already
produces and validates (schemas/text_structure.py,
schemas/image_structure.py, schemas/table_structure.py) -- nothing is
recomputed or reshaped here.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel

from schemas.image_structure import DocumentImageStructure
from schemas.table_structure import DocumentTableStructure
from schemas.text_structure import DocumentTextStructure


class DocumentMetadata(BaseModel):
    """
    Full document-metadata extraction result for one PDF: text
    structure, images, and tables in a single object.
    """

    source_file: str
    # Filename of the source PDF (not the full path).

    page_count: int
    # Total number of pages Docling parsed.

    extraction_date: date

    primary_language: Optional[str] = None
    # Convenience copy of text.primary_language, promoted to the top
    # level since it's the single most commonly needed summary field.

    text: DocumentTextStructure
    # Output of the Text Structure Agent + Language Agent
    # (agents/text_agent.py, agents/language_agent.py).

    images: DocumentImageStructure
    # Output of the Image Agent (agents/image_agent.py).

    tables: DocumentTableStructure
    # Output of the Table Agent (agents/table_agent.py).
