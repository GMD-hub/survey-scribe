"""What a model request carries: text as UTF-8 with invisible characters escaped, and tables
without each row's trailing empty cells."""

from __future__ import annotations

import json

from survey_scribe import pipeline
from survey_scribe.sources.base import SourceProvenance, SourceTable, render_table
from survey_scribe.sources.chunking import SourceChunk, SourceChunkPart


def _chunk(*parts: SourceChunkPart) -> SourceChunk:
    return SourceChunk(
        id="chunk-000001",
        order=0,
        text="\n\n".join(part.text for part in parts),
        block_ids=tuple(part.block_id for part in parts),
        new_block_ids=tuple(part.block_id for part in parts),
        provenance=tuple(part.provenance for part in parts),
        parts=parts,
        new_part_ids=tuple(part.id for part in parts),
        token_count=1,
    )


def _text_part(text: str) -> SourceChunkPart:
    return SourceChunkPart(
        id="block-1:part-000001",
        block_id="block-1",
        part_index=1,
        part_count=1,
        kind="text",
        text=text,
        provenance=SourceProvenance(source_name="q.pdf", page=1),
    )


def test_non_latin_text_is_sent_as_utf8_and_round_trips() -> None:
    text = "Ваш возраст? عمرك؟ আপনার বয়স? Q1. Age"
    payload = pipeline._chunk_payload(_chunk(_text_part(text)))

    assert "Ваш возраст" in payload and "\\u" not in payload
    assert json.loads(payload)[0]["text"] == text
    assert len(payload.encode("utf-8")) < len(json.dumps(text, ensure_ascii=True))


def test_invisible_characters_stay_escaped() -> None:
    hidden = "a\u200bb\u202ec\u2028d\u00ade\ufeff\U000e0041\x85"
    payload = pipeline._chunk_payload(_chunk(_text_part(hidden)))

    codes = ("\\u200b", "\\u202e", "\\u2028", "\\u00ad", "\\ufeff", "\\udb40\\udc41", "\\u0085")
    for code in codes:
        assert code in payload
    assert all(ch.isascii() for ch in payload)
    assert json.loads(payload)[0]["text"] == hidden


def test_a_table_is_sent_without_each_rows_trailing_empty_cells() -> None:
    rows = (
        ("Item", "Bought? (1 yes, 2 no)", "Quantity", "Value"),
        ("01 Bread", "", "", ""),
        ("02 Milk", "", "", " "),
        ("03 Other (specify)", "", "", "10"),
    )
    provenance = SourceProvenance(source_name="q.pdf", page=1, row_start=1, row_end=4)
    table = SourceTable(id="table-1", rows=rows, provenance=provenance)
    part = SourceChunkPart(
        id="block-1:part-000001",
        block_id="block-1",
        part_index=1,
        part_count=1,
        kind="table",
        text=render_table(rows),
        provenance=provenance,
        table=table,
    )
    sent = json.loads(pipeline._chunk_payload(_chunk(part)))[0]["text"]

    assert sent == (
        "Item | Bought? (1 yes, 2 no) | Quantity | Value\n"
        "01 Bread\n"
        "02 Milk\n"
        "03 Other (specify) |  |  | 10"
    )
    assert part.text == render_table(rows)  # the part itself is unchanged
