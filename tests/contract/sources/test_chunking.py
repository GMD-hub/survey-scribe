"""Deterministic token, table, overlap, and repeated-row chunk contracts."""

from __future__ import annotations

import pytest

from survey_scribe.sources.base import (
    SourceBlock,
    SourceDocument,
    SourceProvenance,
    SourceTable,
)
from survey_scribe.sources.chunking import ConservativeTokenEstimator, chunk_document


class WordEstimator:
    def estimate(self, text: str) -> int:
        return len(text.split())


def _document() -> SourceDocument:
    source = "questionnaire.md"
    text_provenance = SourceProvenance(source_name=source)
    table = SourceTable(
        id="table-000001",
        rows=(("code", "label"), ("Q1", "Age"), ("Q1", "Age"), ("Q2", "Name")),
        provenance=SourceProvenance(source_name=source, row_start=1, row_end=4),
    )
    return SourceDocument(
        source_name=source,
        media_type="text/markdown",
        blocks=(
            SourceBlock(
                id="block-000001",
                order=0,
                kind="text",
                text="Survey preamble",
                provenance=text_provenance,
            ),
            SourceBlock(
                id="block-000002",
                order=1,
                kind="text",
                text="Short content",
                provenance=text_provenance,
            ),
            SourceBlock(
                id="block-000003",
                order=2,
                kind="table",
                text="code | label\nQ1 | Age\nQ1 | Age\nQ2 | Name",
                provenance=table.provenance,
                table=table,
            ),
            SourceBlock(
                id="block-000004",
                order=3,
                kind="text",
                text="Closing note",
                provenance=text_provenance,
            ),
        ),
    )


def test_conservative_fallback_never_returns_zero_for_content() -> None:
    estimator = ConservativeTokenEstimator()
    assert estimator.estimate("") == 0
    assert estimator.estimate("1234567") == 3


def test_chunking_preserves_preamble_short_content_table_and_stable_order() -> None:
    result = chunk_document(_document(), max_tokens=8, overlap_tokens=2, estimator=WordEstimator())

    assert result.chunks[0].text.startswith("Survey preamble")
    assert "Short content" in result.chunks[0].text
    assert [chunk.order for chunk in result.chunks] == list(range(len(result.chunks)))
    assert [block_id for chunk in result.chunks for block_id in chunk.new_block_ids] == [
        "block-000001",
        "block-000002",
        "block-000003",
        "block-000004",
    ]
    table_chunks = [chunk for chunk in result.chunks if "block-000003" in chunk.block_ids]
    assert len(table_chunks) == 1
    assert "Q1 | Age\nQ1 | Age" in table_chunks[0].text


def test_overlap_provenance_is_explicit_and_deterministic() -> None:
    first = chunk_document(_document(), max_tokens=5, overlap_tokens=2, estimator=WordEstimator())
    second = chunk_document(_document(), max_tokens=5, overlap_tokens=2, estimator=WordEstimator())

    assert first == second
    assert any(chunk.overlap_block_ids for chunk in first.chunks[1:])
    assert all(set(chunk.overlap_block_ids).issubset(chunk.block_ids) for chunk in first.chunks)


def test_repeated_row_inventory_tracks_each_actual_row_origin() -> None:
    result = chunk_document(
        _document(), max_tokens=100, overlap_tokens=0, estimator=WordEstimator()
    )

    assert len(result.repeated_rows) == 1
    repeated = result.repeated_rows[0]
    assert repeated.row == ("Q1", "Age")
    assert repeated.count == 2
    assert [(origin.table_id, origin.row) for origin in repeated.origins] == [
        ("table-000001", 2),
        ("table-000001", 3),
    ]


@pytest.mark.parametrize(
    ("max_tokens", "overlap_tokens"),
    [(0, 0), (5, -1), (5, 5)],
)
def test_chunking_rejects_invalid_token_budgets(max_tokens: int, overlap_tokens: int) -> None:
    with pytest.raises(ValueError):
        chunk_document(
            _document(),
            max_tokens=max_tokens,
            overlap_tokens=overlap_tokens,
            estimator=WordEstimator(),
        )


def test_text_groups_split_at_budget_and_empty_documents_stay_empty() -> None:
    provenance = SourceProvenance(source_name="questionnaire.txt")
    document = SourceDocument(
        source_name="questionnaire.txt",
        media_type="text/plain",
        blocks=tuple(
            SourceBlock(
                id=f"block-{index}",
                order=index,
                kind="text",
                text=text,
                provenance=provenance,
            )
            for index, text in enumerate(("one two", "three four", "five six"))
        ),
    )

    result = chunk_document(document, max_tokens=3, estimator=WordEstimator())
    empty = chunk_document(
        SourceDocument(source_name="empty.txt", media_type="text/plain", blocks=()),
        max_tokens=3,
        estimator=WordEstimator(),
    )

    assert [chunk.new_block_ids for chunk in result.chunks] == [
        ("block-0",),
        ("block-1",),
        ("block-2",),
    ]
    assert empty.chunks == ()


def test_table_first_and_table_overlap_paths_keep_tables_atomic() -> None:
    source = "questionnaire.csv"
    provenance = SourceProvenance(source_name=source, row_start=1, row_end=1)
    table = SourceTable(id="table-1", rows=(("Q1",),), provenance=provenance)
    document = SourceDocument(
        source_name=source,
        media_type="text/csv",
        blocks=(
            SourceBlock(
                id="table-block",
                order=0,
                kind="table",
                text="Q1",
                provenance=provenance,
                table=table,
            ),
            SourceBlock(
                id="text-block",
                order=1,
                kind="text",
                text="closing",
                provenance=SourceProvenance(source_name=source),
            ),
        ),
    )

    result = chunk_document(document, max_tokens=3, overlap_tokens=2, estimator=WordEstimator())

    assert result.chunks[0].new_block_ids == ("table-block",)
    assert result.chunks[1].overlap_block_ids == ()


def test_repeated_rows_normalize_whitespace_before_comparison() -> None:
    source = "questionnaire.csv"
    provenance = SourceProvenance(source_name=source, row_start=4, row_end=5)
    table = SourceTable(
        id="table-1",
        rows=(("Q1", "Age"), (" Q1 ", "Age\n")),
        provenance=provenance,
    )
    document = SourceDocument(
        source_name=source,
        media_type="text/csv",
        blocks=(
            SourceBlock(
                id="block-1",
                order=0,
                kind="table",
                text="Q1 | Age",
                provenance=provenance,
                table=table,
            ),
        ),
    )

    repeated = chunk_document(document, max_tokens=10).repeated_rows[0]

    assert repeated.row == ("Q1", "Age")
    assert [origin.row for origin in repeated.origins] == [4, 5]
