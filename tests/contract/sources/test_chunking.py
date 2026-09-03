"""Deterministic token, table, overlap, and repeated-row chunk contracts."""

from __future__ import annotations

import pytest

from survey_scribe.sources.base import (
    SourceBlock,
    SourceDocument,
    SourceLimitError,
    SourceProvenance,
    SourceTable,
    render_table,
)
from survey_scribe.sources.chunking import (
    ConservativeTokenEstimator,
    SourceChunkPart,
    chunk_document,
)


class WordEstimator:
    def estimate(self, text: str) -> int:
        return len(text.split())


class CharacterEstimator:
    def estimate(self, text: str) -> int:
        return len(text)


class NeverFitsEstimator:
    def estimate(self, text: str) -> int:
        return 2 if text else 0


class FinalGrowthEstimator:
    def __init__(self) -> None:
        self.calls = 0

    def estimate(self, text: str) -> int:
        if text != "a":
            return len(text)
        self.calls += 1
        return 2 if self.calls == 3 else 1


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
    assert estimator.estimate("1234567") == 7
    assert estimator.estimate("é") == 2


def test_chunking_preserves_preamble_short_content_table_and_stable_order() -> None:
    result = chunk_document(_document(), max_tokens=20, overlap_tokens=2, estimator=WordEstimator())

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
    first = chunk_document(_document(), max_tokens=20, overlap_tokens=2, estimator=WordEstimator())
    second = chunk_document(_document(), max_tokens=20, overlap_tokens=2, estimator=WordEstimator())

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
    [(0, 0), (5, -1), (5, 5), (True, 0), (5, False), (1.5, 0), (5, 1.5)],
)
def test_chunking_rejects_invalid_token_budgets(
    max_tokens: object,
    overlap_tokens: object,
) -> None:
    with pytest.raises(ValueError):
        chunk_document(
            _document(),
            max_tokens=max_tokens,  # type: ignore[arg-type]
            overlap_tokens=overlap_tokens,  # type: ignore[arg-type]
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


def test_oversized_text_is_split_without_exceeding_the_final_token_limit() -> None:
    source = "questionnaire.txt"
    text = "abcdefghijk"
    provenance = SourceProvenance(source_name=source)
    document = SourceDocument(
        source_name=source,
        media_type="text/plain",
        blocks=(
            SourceBlock(
                id="block-1",
                order=0,
                kind="text",
                text=text,
                provenance=provenance,
            ),
        ),
    )

    result = chunk_document(document, max_tokens=4, estimator=CharacterEstimator())
    new_parts = [
        part for chunk in result.chunks for part in chunk.parts if part.id in chunk.new_part_ids
    ]

    assert len(result.chunks) == 3
    assert "".join(part.text for part in new_parts) == text
    assert all(chunk.token_count <= 4 for chunk in result.chunks)
    assert all(CharacterEstimator().estimate(chunk.text) <= 4 for chunk in result.chunks)


def test_overlap_is_reserved_inside_the_hard_final_token_limit() -> None:
    source = "questionnaire.txt"
    provenance = SourceProvenance(source_name=source)
    document = SourceDocument(
        source_name=source,
        media_type="text/plain",
        blocks=tuple(
            SourceBlock(
                id=f"block-{index}",
                order=index,
                kind="text",
                text=text,
                provenance=provenance,
            )
            for index, text in enumerate(("aaaaa", "bbbbb"))
        ),
    )

    result = chunk_document(
        document,
        max_tokens=6,
        overlap_tokens=5,
        estimator=CharacterEstimator(),
    )

    assert any(chunk.overlap_part_ids for chunk in result.chunks[1:])
    assert all(chunk.token_count <= 6 for chunk in result.chunks)
    assert all(CharacterEstimator().estimate(chunk.text) <= 6 for chunk in result.chunks)


def test_oversized_table_is_rejected_instead_of_exceeding_the_limit() -> None:
    source = "questionnaire.csv"
    rows = (("x" * 20,),)
    provenance = SourceProvenance(source_name=source, row_start=1, row_end=1)
    table = SourceTable(id="table-1", rows=rows, provenance=provenance)
    document = SourceDocument(
        source_name=source,
        media_type="text/csv",
        blocks=(
            SourceBlock(
                id="block-1",
                order=0,
                kind="table",
                text=render_table(rows),
                provenance=provenance,
                table=table,
            ),
        ),
    )

    with pytest.raises(SourceLimitError) as raised:
        chunk_document(document, max_tokens=10, estimator=CharacterEstimator())

    assert raised.value.limit == "max_tokens"


def test_chunk_parts_transport_table_cells_without_flattening() -> None:
    source = "questionnaire.csv"
    rows = (("code|value", "line one\nline two\\tail"),)
    provenance = SourceProvenance(source_name=source, row_start=1, row_end=1)
    table = SourceTable(id="table-1", rows=rows, provenance=provenance)
    document = SourceDocument(
        source_name=source,
        media_type="text/csv",
        blocks=(
            SourceBlock(
                id="block-1",
                order=0,
                kind="table",
                text=render_table(rows),
                provenance=provenance,
                table=table,
            ),
        ),
    )

    chunk = chunk_document(document, max_tokens=100, estimator=CharacterEstimator()).chunks[0]

    assert chunk.parts[0].table is not None
    assert chunk.parts[0].table.rows == rows
    assert chunk.model_dump()["parts"][0]["table"]["rows"] == rows
    assert chunk.text == r"code\|value | line one\nline two\\tail"


@pytest.mark.parametrize("kind", ["text", "table"])
def test_content_at_the_exact_token_boundary_is_accepted(kind: str) -> None:
    source = "questionnaire.txt"
    provenance = SourceProvenance(source_name=source, row_start=1, row_end=1)
    table = SourceTable(id="table-1", rows=(("abcd",),), provenance=provenance)
    block = SourceBlock(
        id="block-1",
        order=0,
        kind=kind,  # type: ignore[arg-type]
        text="abcd",
        provenance=provenance,
        table=table if kind == "table" else None,
    )
    document = SourceDocument(source_name=source, media_type="text/plain", blocks=(block,))

    result = chunk_document(document, max_tokens=4, estimator=CharacterEstimator())

    assert len(result.chunks) == 1
    assert result.chunks[0].token_count == 4
    assert result.chunks[0].text == "abcd"


@pytest.mark.parametrize(
    ("estimator", "message"),
    [
        (NeverFitsEstimator(), "cannot be split"),
        (FinalGrowthEstimator(), "Final source chunk"),
    ],
)
def test_estimator_failures_raise_typed_token_limits(estimator: object, message: str) -> None:
    provenance = SourceProvenance(source_name="questionnaire.txt")
    document = SourceDocument(
        source_name="questionnaire.txt",
        media_type="text/plain",
        blocks=(
            SourceBlock(
                id="block-1",
                order=0,
                kind="text",
                text="a",
                provenance=provenance,
            ),
        ),
    )

    with pytest.raises(SourceLimitError, match=message) as raised:
        chunk_document(document, max_tokens=1, estimator=estimator)  # type: ignore[arg-type]

    assert raised.value.limit == "max_tokens"


def test_text_split_prefers_the_last_whitespace_inside_the_budget() -> None:
    provenance = SourceProvenance(source_name="questionnaire.txt")
    document = SourceDocument(
        source_name="questionnaire.txt",
        media_type="text/plain",
        blocks=(
            SourceBlock(
                id="block-1",
                order=0,
                kind="text",
                text="abc def",
                provenance=provenance,
            ),
        ),
    )

    result = chunk_document(document, max_tokens=4, estimator=CharacterEstimator())

    assert [part.text for chunk in result.chunks for part in chunk.parts] == ["abc ", "def"]


def test_overlap_is_omitted_when_separators_would_cross_the_final_boundary() -> None:
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
            for index, text in enumerate(("aa", "bbb"))
        ),
    )

    result = chunk_document(
        document,
        max_tokens=5,
        overlap_tokens=2,
        estimator=CharacterEstimator(),
    )

    assert len(result.chunks) == 2
    assert result.chunks[1].overlap_part_ids == ()
    assert result.chunks[1].text == "bbb"


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"part_index": 2, "part_count": 1}, "must not exceed"),
        ({"kind": "table"}, "must retain"),
        ({"table": "matching"}, "must retain"),
        ({"kind": "table", "table": "other"}, "provenance must match"),
    ],
)
def test_chunk_parts_reject_invalid_index_table_and_provenance_states(
    updates: dict[str, object], message: str
) -> None:
    provenance = SourceProvenance(source_name="questionnaire.csv", row_start=1, row_end=1)
    matching = SourceTable(id="table-1", rows=(("Q1",),), provenance=provenance)
    other_provenance = SourceProvenance(source_name="questionnaire.csv", row_start=2, row_end=2)
    other = SourceTable(id="table-2", rows=(("Q2",),), provenance=other_provenance)
    table_value = updates.get("table")
    values: dict[str, object] = {
        "id": "block-1:part-000001",
        "block_id": "block-1",
        "part_index": 1,
        "part_count": 1,
        "kind": "text",
        "text": "Q1",
        "provenance": provenance,
        "table": matching
        if table_value == "matching"
        else other
        if table_value == "other"
        else None,
    }
    values.update({key: value for key, value in updates.items() if key != "table"})

    with pytest.raises(ValueError, match=message):
        SourceChunkPart.model_validate(values)
