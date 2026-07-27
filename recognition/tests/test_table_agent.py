"""
Tests for the Table Agent (agents/table_agent.py).

Builds a small DoclingDocument programmatically (no PDF/Docling
conversion involved) so these tests are fast and exercise only the
grid-copying logic in extract_tables().
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docling_core.types.doc import (
    BoundingBox,
    DoclingDocument,
    ProvenanceItem,
    TableCell,
    TableData,
)

from agents.table_agent import extract_tables


def _prov(page_no: int) -> ProvenanceItem:
    return ProvenanceItem(
        page_no=page_no,
        bbox=BoundingBox(l=0, t=0, r=10, b=10),
        charspan=(0, 0),
    )


def _cell(text, r0, r1, c0, c1, column_header=False, row_header=False) -> TableCell:
    return TableCell(
        text=text,
        start_row_offset_idx=r0,
        end_row_offset_idx=r1,
        start_col_offset_idx=c0,
        end_col_offset_idx=c1,
        row_span=r1 - r0,
        col_span=c1 - c0,
        column_header=column_header,
        row_header=row_header,
    )


def _simple_table_data() -> TableData:
    """A plain 2x2 table, no merged cells."""
    return TableData(
        num_rows=2,
        num_cols=2,
        table_cells=[
            _cell("Name", 0, 1, 0, 1, column_header=True),
            _cell("Age", 0, 1, 1, 2, column_header=True),
            _cell("Amara", 1, 2, 0, 1),
            _cell("34", 1, 2, 1, 2),
        ],
    )


def _merged_table_data() -> TableData:
    """A 2x2 table where the top-left cell spans both columns (a title row)."""
    return TableData(
        num_rows=2,
        num_cols=2,
        table_cells=[
            _cell("Household roster", 0, 1, 0, 2, column_header=True),
            _cell("A", 1, 2, 0, 1),
            _cell("B", 1, 2, 1, 2),
        ],
    )


def _sample_doc() -> DoclingDocument:
    doc = DoclingDocument(name="sample")
    doc.add_table(data=_simple_table_data(), prov=_prov(page_no=2))
    doc.add_table(data=_merged_table_data(), prov=_prov(page_no=4))
    return doc


def test_extracts_one_block_per_table():
    doc = _sample_doc()
    structure = extract_tables(doc, source_file="sample.pdf")
    assert len(structure.tables) == 2


def test_table_dimensions_and_page_are_recorded():
    doc = _sample_doc()
    structure = extract_tables(doc, source_file="sample.pdf")
    first = structure.tables[0]
    assert first.page == 2
    assert first.num_rows == 2
    assert first.num_cols == 2


def test_grid_preserves_row_and_column_order():
    doc = _sample_doc()
    structure = extract_tables(doc, source_file="sample.pdf")
    grid = structure.tables[0].cells
    assert [c.text for c in grid[0]] == ["Name", "Age"]
    assert [c.text for c in grid[1]] == ["Amara", "34"]


def test_column_header_flag_is_preserved():
    doc = _sample_doc()
    structure = extract_tables(doc, source_file="sample.pdf")
    grid = structure.tables[0].cells
    assert grid[0][0].column_header is True
    assert grid[1][0].column_header is False


def test_merged_cell_repeats_across_every_position_it_spans():
    doc = _sample_doc()
    structure = extract_tables(doc, source_file="sample.pdf")
    grid = structure.tables[1].cells
    # The title cell spans both columns of row 0 -- it must appear at
    # both (0,0) and (0,1) with the same text, matching how the table
    # visually reads.
    assert grid[0][0].text == "Household roster"
    assert grid[0][1].text == "Household roster"
    assert grid[0][0].col_span == 2


def test_grid_shape_matches_num_rows_and_num_cols():
    doc = _sample_doc()
    structure = extract_tables(doc, source_file="sample.pdf")
    for table in structure.tables:
        assert len(table.cells) == table.num_rows
        for row in table.cells:
            assert len(row) == table.num_cols


def test_source_file_and_page_count_are_recorded():
    doc = _sample_doc()
    structure = extract_tables(doc, source_file="sample.pdf")
    assert structure.source_file == "sample.pdf"
    assert structure.page_count == len(doc.pages)
