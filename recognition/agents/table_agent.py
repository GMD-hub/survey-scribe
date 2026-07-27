"""
Table Agent
=======================
Extracts every table from a DoclingDocument, preserving its full row x
column grid structure (including merged cells and header flags).
Deterministic -- no LLM call, no API key needed.

Docling's table-structure model already resolves each table into a
TableData object with a `.grid` property: a full row x column matrix of
TableCell objects (merged cells repeated across every position they
span, exactly as the table visually reads). This agent's job is purely
to walk doc.tables and copy that grid into our own schema -- a
mechanical structure-preserving copy, not a reasoning task.

Consumed by the eventual document-metadata orchestrator, which merges
this agent's output with the text/language/image agents' output into
one JSON file.

Known limitation (inherited from Docling, see repo memory notes and
recognition/README.md): dense multi-column "roster grid" tables in
these questionnaires are not always reconstructed well by Docling's
table-structure model -- expect occasional flattened/misaligned cells
on those tables even though this agent copies Docling's grid exactly.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from docling_core.types.doc.document import DoclingDocument

from schemas.table_structure import DocumentTableStructure, TableBlock, TableCellBlock


def extract_tables(doc: DoclingDocument, source_file: str) -> DocumentTableStructure:
    """
    Walks a DoclingDocument's tables and copies each one's full row x
    column cell grid (as resolved by Docling's TableData.grid) into a
    TableBlock, preserving merged-cell spans and header flags exactly.
    """
    tables: list[TableBlock] = []
    for table_id, item in enumerate(doc.tables):
        page = item.prov[0].page_no if item.prov else 0
        caption = item.caption_text(doc).strip() or None

        cell_rows = [
            [
                TableCellBlock(
                    text=cell.text,
                    row_span=cell.row_span,
                    col_span=cell.col_span,
                    column_header=cell.column_header,
                    row_header=cell.row_header,
                )
                for cell in row
            ]
            for row in item.data.grid
        ]

        tables.append(TableBlock(
            table_id=table_id,
            page=page,
            num_rows=item.data.num_rows,
            num_cols=item.data.num_cols,
            cells=cell_rows,
            caption=caption,
        ))

    return DocumentTableStructure(
        source_file=Path(source_file).name,
        page_count=len(doc.pages),
        tables=tables,
        extraction_date=date.today(),
    )
