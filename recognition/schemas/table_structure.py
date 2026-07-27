"""
Table Structure Schema
=========================
Pydantic models for the output of the Table Agent
(agents/table_agent.py).

Separate from schemas/text_structure.py and schemas/image_structure.py:
this describes tables (page, dimensions, cell grid) in the PDF.

Design goal: preserve table structure as faithfully as possible rather
than flattening to a single string (Markdown/HTML). A `TableBlock`
stores the full row x column grid of cells exactly as Docling resolved
it -- including merged cells (row_span/col_span > 1, repeated across
every grid position they cover, matching how the table visually reads)
and header flags -- so downstream consumers can reconstruct the table
layout exactly, not just its raw text content.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel


class TableCellBlock(BaseModel):
    """One cell in a table's row x column grid -- one Docling TableCell."""

    text: str
    # Cell text content, exactly as Docling extracted it.

    row_span: int = 1
    col_span: int = 1
    # How many grid rows/columns this cell spans. > 1 for merged cells.
    # A merged cell appears at every (row, col) position it covers in
    # TableBlock.cells, matching how the table visually reads -- this is
    # the same repetition Docling's own TableData.grid produces.

    column_header: bool = False
    row_header: bool = False
    # Whether Docling identified this cell as a column or row header.


class TableBlock(BaseModel):
    """One table -- one Docling TableItem."""

    table_id: int
    # Stable position of this table within the document's reading order.

    page: int
    # 1-indexed PDF page number this table appears on.
    # 0 if Docling could not determine provenance for this table.

    num_rows: int
    num_cols: int
    # Table dimensions, as resolved by Docling's table-structure model.

    cells: list[list[TableCellBlock]]
    # Full row x column grid of cells, outer list = rows, inner list =
    # columns within that row. len(cells) == num_rows,
    # len(cells[i]) == num_cols for every row.

    caption: Optional[str] = None
    # Caption text associated with this table, if Docling detected one.
    # None if there is no caption.


class DocumentTableStructure(BaseModel):
    """
    Full table-structure extraction result for one PDF.
    Written as JSON by recognition/pipeline.py.
    """

    source_file: str
    # Filename of the source PDF (not the full path).

    page_count: int
    # Total number of pages Docling parsed.

    tables: list[TableBlock]
    # All tables, in reading order.

    extraction_date: date

    extraction_notes: Optional[str] = None
    # Free-text notes, e.g. known fidelity limitations for a given table.
