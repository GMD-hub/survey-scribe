"""Deterministic token-aware chunking with table and overlap provenance."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from survey_scribe.sources.base import (
    SourceBlock,
    SourceDocument,
    SourceLimitError,
    SourceProvenance,
    SourceTable,
    render_table,
)


class SourceTableLimitError(SourceLimitError):
    """One cell of a source table cannot fit within the token limit, even alone.

    A table is split by rows, and a row too wide for the limit by columns (bands that repeat the
    header's cells of the same columns); what is left is a single column of a single row — its
    header cell and its value — that alone exceeds the limit.
    """

    def __init__(self, *, table_id: str, block_id: str) -> None:
        self.table_id = table_id
        self.block_id = block_id
        super().__init__(
            "max_tokens",
            f"A cell of source table {table_id!r} cannot fit within the token limit, even "
            "with its row split by columns",
        )


class TokenEstimator(Protocol):
    """Minimal tokenizer-independent estimation port."""

    def estimate(self, text: str) -> int:
        """Return a deterministic non-negative token estimate."""
        ...


class ConservativeTokenEstimator:
    """Dependency-free fallback that budgets one token per UTF-8 byte."""

    def estimate(self, text: str) -> int:
        return len(text.encode("utf-8"))


class RepeatedRowOrigin(BaseModel):
    """Physical table and one-based source row for repeated content."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    table_id: str
    row: int = Field(ge=1)
    provenance: SourceProvenance


class RepeatedRow(BaseModel):
    """Inventory entry for an exact normalized row occurring more than once."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    row: tuple[str, ...]
    count: int = Field(ge=2)
    origins: tuple[RepeatedRowOrigin, ...]


class SourceChunkPart(BaseModel):
    """One typed whole block, deterministic text-block segment, or table row group.

    A table that exceeds the token limit is split into row groups. Each group's
    ``table`` repeats the physical table's first (header) row followed by the
    group's rows, keeps the physical table ``id``, and its ``provenance`` row
    range names only the group's own source rows. A table whose header plus a
    single row exceeds the limit is first split into column bands: ``columns``
    is the band's ``(start, end)`` zero-based, end-exclusive column range, and
    every row of the part (the header included) holds only those cells.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    block_id: str
    part_index: int = Field(ge=1)
    part_count: int = Field(ge=1)
    kind: Literal["text", "table"]
    text: str
    provenance: SourceProvenance
    table: SourceTable | None = None
    columns: tuple[int, int] | None = None

    @model_validator(mode="after")
    def validate_part(self) -> SourceChunkPart:
        if self.part_index > self.part_count:
            raise ValueError("part_index must not exceed part_count")
        if (self.kind == "table") != (self.table is not None):
            raise ValueError("table chunk parts must retain their typed table")
        if self.table is not None and self.table.provenance != self.provenance:
            raise ValueError("chunk-part table provenance must match its part provenance")
        if self.columns is not None:
            if self.table is None:
                raise ValueError("only a table part may carry a column range")
            start, end = self.columns
            if start < 0 or end <= start:
                raise ValueError("a column range is (start, end) with 0 <= start < end")
        return self


class SourceChunk(BaseModel):
    """One stable source-order chunk with explicit overlap ownership."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    order: int = Field(ge=0)
    text: str
    block_ids: tuple[str, ...]
    new_block_ids: tuple[str, ...]
    overlap_block_ids: tuple[str, ...] = ()
    provenance: tuple[SourceProvenance, ...]
    parts: tuple[SourceChunkPart, ...]
    new_part_ids: tuple[str, ...]
    overlap_part_ids: tuple[str, ...] = ()
    token_count: int = Field(ge=0)


class TableSplit(BaseModel):
    """One physical table delivered as more than one part (row groups, and column bands when a
    row is too wide for the limit)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    table_id: str
    block_id: str
    part_count: int = Field(ge=2)
    column_bands: int = Field(default=1, ge=1)


class ChunkedDocument(BaseModel):
    """Deterministic chunks and completeness inventory for one source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_name: str
    chunks: tuple[SourceChunk, ...]
    repeated_rows: tuple[RepeatedRow, ...]

    @property
    def split_tables(self) -> tuple[TableSplit, ...]:
        """Return tables split into row groups (and column bands), in source order."""
        splits: dict[str, TableSplit] = {}
        bands: dict[str, set[tuple[int, int] | None]] = defaultdict(set)
        for chunk in self.chunks:
            for part in chunk.parts:
                if part.table is None or part.part_count < 2 or part.id not in chunk.new_part_ids:
                    continue
                bands[part.block_id].add(part.columns)
                if part.block_id in splits:
                    continue
                splits[part.block_id] = TableSplit(
                    table_id=part.table.id,
                    block_id=part.block_id,
                    part_count=part.part_count,
                )
        return tuple(
            split.model_copy(update={"column_bands": len(bands[block_id])})
            if len(bands[block_id]) > 1
            else split
            for block_id, split in splits.items()
        )


def chunk_document(
    document: SourceDocument,
    *,
    max_tokens: int,
    overlap_tokens: int = 0,
    estimator: TokenEstimator | None = None,
) -> ChunkedDocument:
    """Chunk without dropping preamble, table rows, or source order.

    A table that fits ``max_tokens`` stays whole. A larger table is split into
    row groups that each repeat the table's first (header) row; a table whose
    header plus a single row does not fit is first split into column bands (each
    repeating the header's cells of its columns), then each band by rows; see
    ``ChunkedDocument.split_tables``.

    Args:
        document: Normalized source document to chunk.
        max_tokens: Hard maximum for every final chunk, including overlap.
        overlap_tokens: Target budget for complete prior text blocks copied into
            the next chunk.
        estimator: Token estimator. The conservative dependency-free estimator is
            used when omitted.

    Returns:
        Stable chunks plus an inventory of exact repeated table rows.

    Raises:
        ValueError: ``max_tokens`` is below one, or ``overlap_tokens`` is negative
            or not smaller than ``max_tokens``.
        SourceTableLimitError: One column of a table's header plus one of its rows
            cannot fit within ``max_tokens``.
        SourceLimitError: Content cannot otherwise fit within ``max_tokens``.
    """
    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int):
        raise ValueError("max_tokens must be an integer")
    if isinstance(overlap_tokens, bool) or not isinstance(overlap_tokens, int):
        raise ValueError("overlap_tokens must be an integer")
    if max_tokens < 1:
        raise ValueError("max_tokens must be at least 1")
    if overlap_tokens < 0 or overlap_tokens >= max_tokens:
        raise ValueError("overlap_tokens must be non-negative and less than max_tokens")
    token_estimator = estimator or ConservativeTokenEstimator()
    new_content_budget = max_tokens - overlap_tokens if overlap_tokens else max_tokens
    parts = _split_blocks(
        document.blocks,
        max_tokens=max_tokens,
        text_budget=new_content_budget,
        estimator=token_estimator,
    )
    groups = _group_parts(parts, max_tokens=new_content_budget, estimator=token_estimator)
    chunks: list[SourceChunk] = []
    previous_new: tuple[_BlockPart, ...] = ()
    for new_parts in groups:
        overlap = _overlap_tail(
            previous_new,
            overlap_tokens,
            token_estimator,
            new_parts=new_parts,
            max_tokens=max_tokens,
        )
        all_parts = overlap + new_parts
        text = _join_parts(all_parts)
        token_count = token_estimator.estimate(text)
        if token_count > max_tokens:
            raise SourceLimitError("max_tokens", "Final source chunk exceeds the token limit")
        chunks.append(
            SourceChunk(
                id=f"chunk-{len(chunks) + 1:06d}",
                order=len(chunks),
                text=text,
                block_ids=tuple(part.block.id for part in all_parts),
                new_block_ids=tuple(part.block.id for part in new_parts),
                overlap_block_ids=tuple(part.block.id for part in overlap),
                provenance=tuple(part.provenance for part in all_parts),
                parts=tuple(_to_chunk_part(part) for part in all_parts),
                new_part_ids=tuple(part.id for part in new_parts),
                overlap_part_ids=tuple(part.id for part in overlap),
                token_count=token_count,
            )
        )
        previous_new = new_parts
    return ChunkedDocument(
        source_name=document.source_name,
        chunks=tuple(chunks),
        repeated_rows=_repeated_rows(document),
    )


@dataclass(frozen=True, slots=True)
class _BlockPart:
    block: SourceBlock
    id: str
    part_index: int
    part_count: int
    text: str
    provenance: SourceProvenance
    table: SourceTable | None = None
    columns: tuple[int, int] | None = None


def _split_blocks(
    blocks: tuple[SourceBlock, ...],
    *,
    max_tokens: int,
    text_budget: int,
    estimator: TokenEstimator,
) -> tuple[_BlockPart, ...]:
    parts: list[_BlockPart] = []
    for block in blocks:
        pieces: tuple[tuple[str, SourceProvenance, SourceTable | None, tuple[int, int] | None], ...]
        if block.table is not None:
            if estimator.estimate(block.text) <= max_tokens:
                pieces = ((block.text, block.provenance, block.table, None),)
            else:
                pieces = _split_table(
                    block,
                    block.table,
                    max_tokens=max_tokens,
                    group_budget=text_budget,
                    estimator=estimator,
                )
        else:
            pieces = tuple(
                (text, block.provenance, None, None)
                for text in _split_text(block.text, max_tokens=text_budget, estimator=estimator)
            )
        part_count = len(pieces)
        parts.extend(
            _BlockPart(
                block=block,
                id=f"{block.id}:part-{index:06d}",
                part_index=index,
                part_count=part_count,
                text=text,
                provenance=provenance,
                table=table,
                columns=columns,
            )
            for index, (text, provenance, table, columns) in enumerate(pieces, start=1)
        )
    return tuple(parts)


def _table_width(table: SourceTable) -> int:
    return max((len(row) for row in table.rows), default=0)


def _band(row: tuple[str, ...], columns: tuple[int, int] | None) -> tuple[str, ...]:
    return row if columns is None else row[columns[0] : columns[1]]


def _split_table(
    block: SourceBlock,
    table: SourceTable,
    *,
    max_tokens: int,
    group_budget: int,
    estimator: TokenEstimator,
) -> tuple[tuple[str, SourceProvenance, SourceTable, tuple[int, int] | None], ...]:
    """Split a table into header-repeating row groups in source order.

    Rows are packed greedily up to ``group_budget`` so a part leaves room for
    overlap context; a group holding a single row may use up to ``max_tokens``.
    When the header plus a single row exceeds ``max_tokens`` — a header row of
    long question texts — the table is first cut into column bands, each as wide
    as every row allows, and each band is split by rows; the parts run band by
    band, rows in source order within each.
    """
    try:
        return _row_groups(
            block,
            table,
            None,
            max_tokens=max_tokens,
            group_budget=group_budget,
            estimator=estimator,
        )
    except SourceTableLimitError:
        pass
    pieces: list[tuple[str, SourceProvenance, SourceTable, tuple[int, int] | None]] = []
    for columns in _column_bands(block, table, max_tokens=max_tokens, estimator=estimator):
        pieces.extend(
            _row_groups(
                block,
                table,
                columns,
                max_tokens=max_tokens,
                group_budget=group_budget,
                estimator=estimator,
            )
        )
    return tuple(pieces)


def _row_groups(
    block: SourceBlock,
    table: SourceTable,
    columns: tuple[int, int] | None,
    *,
    max_tokens: int,
    group_budget: int,
    estimator: TokenEstimator,
) -> tuple[tuple[str, SourceProvenance, SourceTable, tuple[int, int] | None], ...]:
    """The header-repeating row groups of the table (of one column band of it)."""
    header = _band(table.rows[0], columns) if table.rows else ()
    body = table.rows[1:]
    if not body:
        raise SourceTableLimitError(table_id=table.id, block_id=block.id)
    groups: list[tuple[int, int]] = []
    start = 1
    end = 1
    while end <= len(body):
        band_rows = (_band(row, columns) for row in table.rows[start : end + 1])
        candidate = render_table((header, *band_rows))
        limit = max_tokens if end == start else group_budget
        if estimator.estimate(candidate) <= limit:
            end += 1
            continue
        if end == start:
            raise SourceTableLimitError(table_id=table.id, block_id=block.id)
        groups.append((start, end))
        start = end
    groups.append((start, end))
    return tuple(
        (*_table_row_group(table, first, last, columns), columns) for first, last in groups
    )


def _column_bands(
    block: SourceBlock,
    table: SourceTable,
    *,
    max_tokens: int,
    estimator: TokenEstimator,
) -> tuple[tuple[int, int], ...]:
    """Consecutive column ranges, each as wide as the header plus ANY single row allows within
    ``max_tokens`` (so every band can then be split by rows)."""
    width = _table_width(table)
    header = table.rows[0] if table.rows else ()
    body = table.rows[1:] or ((),)

    def fits(first: int, last: int) -> bool:
        head = header[first:last]
        return all(
            estimator.estimate(render_table((head, row[first:last]))) <= max_tokens for row in body
        )

    bands: list[tuple[int, int]] = []
    start = 0
    while start < width:
        if not fits(start, start + 1):
            raise SourceTableLimitError(table_id=table.id, block_id=block.id)
        end = start + 1
        while end < width and fits(start, end + 1):
            end += 1
        bands.append((start, end))
        start = end
    if len(bands) < 2:
        raise SourceTableLimitError(table_id=table.id, block_id=block.id)
    return tuple(bands)


def _table_row_group(
    table: SourceTable, first: int, last: int, columns: tuple[int, int] | None = None
) -> tuple[str, SourceProvenance, SourceTable]:
    """Build the part for ``table.rows[first:last]`` with the header row repeated (only the cells of
    ``columns`` in every row, when a column band)."""
    rows = tuple(_band(row, columns) for row in (table.rows[0], *table.rows[first:last]))
    base = table.provenance.row_start or 1
    provenance = SourceProvenance.model_validate(
        {
            **table.provenance.model_dump(),
            "row_start": base + first,
            "row_end": base + last - 1,
        }
    )
    return (
        render_table(rows),
        provenance,
        SourceTable(id=table.id, rows=rows, provenance=provenance),
    )


def split_table_part(
    part: SourceChunkPart, block: SourceBlock
) -> tuple[SourceChunkPart, SourceChunkPart]:
    """Halve one table part, repeating the header row in both halves: by rows, or — a part of a
    single row — by columns (each half repeats the header's cells of its own columns).

    The halves keep ``part``'s identifiers and indexes; callers renumber them.

    Raises:
        SourceTableLimitError: ``part`` holds one row of one column.
    """
    if part.table is None or block.table is None or part.block_id != block.id:
        raise ValueError("split_table_part requires a table part and its source block")
    table = block.table
    if part.table == table:
        first, last = 1, len(table.rows)
    else:
        base = table.provenance.row_start or 1
        row_start = part.provenance.row_start
        row_end = part.provenance.row_end
        if row_start is None or row_end is None:
            raise ValueError("a split table part must carry its source row range")
        first, last = row_start - base, row_end - base + 1
    columns = part.columns or (0, _table_width(table))
    if last - first >= 2:
        middle = first + (last - first) // 2
        ranges = (((first, middle), part.columns), ((middle, last), part.columns))
    elif columns[1] - columns[0] >= 2:
        middle = columns[0] + (columns[1] - columns[0]) // 2
        ranges = (((first, last), (columns[0], middle)), ((first, last), (middle, columns[1])))
    else:
        raise SourceTableLimitError(table_id=table.id, block_id=block.id)
    halves: list[SourceChunkPart] = []
    for (start, end), band in ranges:
        text, provenance, group_table = _table_row_group(table, start, end, band)
        halves.append(
            part.model_copy(
                update={
                    "text": text,
                    "provenance": provenance,
                    "table": group_table,
                    "columns": band,
                }
            )
        )
    return halves[0], halves[1]


def _group_parts(
    parts: tuple[_BlockPart, ...],
    *,
    max_tokens: int,
    estimator: TokenEstimator,
) -> tuple[tuple[_BlockPart, ...], ...]:
    groups: list[tuple[_BlockPart, ...]] = []
    current: list[_BlockPart] = []
    current_tokens = 0
    for part in parts:
        part_tokens = estimator.estimate(part.text)
        # A table (or table row group) is not isolated: the text printed above a grid is the
        # question it answers, and a reader shown the grid alone cannot know that. The table
        # joins the current group when it fits the budget and opens a new one only when it does not.
        separator_tokens = estimator.estimate("\n\n") if current else 0
        if current and current_tokens + separator_tokens + part_tokens > max_tokens:
            groups.append(tuple(current))
            current = []
            current_tokens = 0
            separator_tokens = 0
        current.append(part)
        current_tokens += separator_tokens + part_tokens
    if current:
        groups.append(tuple(current))
    return tuple(groups)


def _overlap_tail(
    previous: tuple[_BlockPart, ...],
    overlap_tokens: int,
    estimator: TokenEstimator,
    *,
    new_parts: tuple[_BlockPart, ...],
    max_tokens: int,
) -> tuple[_BlockPart, ...]:
    if overlap_tokens == 0:
        return ()
    selected: list[_BlockPart] = []
    for part in reversed(previous):
        if part.block.kind == "table":
            continue
        candidate = tuple(reversed([*selected, part]))
        if estimator.estimate(_join_parts(candidate)) > overlap_tokens:
            break
        if estimator.estimate(_join_parts(candidate + new_parts)) > max_tokens:
            break
        selected.append(part)
    return tuple(reversed(selected))


def _split_text(
    text: str,
    *,
    max_tokens: int,
    estimator: TokenEstimator,
) -> tuple[str, ...]:
    if estimator.estimate(text) <= max_tokens:
        return (text,)
    remaining = text
    parts: list[str] = []
    while remaining:
        low = 1
        high = len(remaining)
        split = 0
        while low <= high:
            middle = (low + high) // 2
            if estimator.estimate(remaining[:middle]) <= max_tokens:
                split = middle
                low = middle + 1
            else:
                high = middle - 1
        if split == 0:
            raise SourceLimitError(
                "max_tokens",
                "A source text unit cannot be split within the token limit",
            )
        if split < len(remaining):
            whitespace_split = max(
                remaining.rfind(" ", 0, split),
                remaining.rfind("\n", 0, split),
                remaining.rfind("\t", 0, split),
            )
            if whitespace_split >= 0:
                split = whitespace_split + 1
        parts.append(remaining[:split])
        remaining = remaining[split:]
    return tuple(parts)


def _join_parts(parts: tuple[_BlockPart, ...]) -> str:
    return "\n\n".join(part.text for part in parts)


def _to_chunk_part(part: _BlockPart) -> SourceChunkPart:
    return SourceChunkPart(
        id=part.id,
        block_id=part.block.id,
        part_index=part.part_index,
        part_count=part.part_count,
        kind=part.block.kind,
        text=part.text,
        provenance=part.provenance,
        table=part.table,
        columns=part.columns,
    )


def _repeated_rows(document: SourceDocument) -> tuple[RepeatedRow, ...]:
    inventories: dict[tuple[str, ...], list[RepeatedRowOrigin]] = defaultdict(list)
    display_rows: dict[tuple[str, ...], tuple[str, ...]] = {}
    first_order: dict[tuple[str, ...], int] = {}
    ordinal = 0
    for table in document.tables:
        row_start = table.provenance.row_start or 1
        for offset, row in enumerate(table.rows):
            normalized = tuple(re.sub(r"\s+", " ", cell).strip() for cell in row)
            first_order.setdefault(normalized, ordinal)
            display_rows.setdefault(normalized, normalized)
            inventories[normalized].append(
                RepeatedRowOrigin(
                    table_id=table.id,
                    row=row_start + offset,
                    provenance=table.provenance,
                )
            )
            ordinal += 1
    repeated = [
        RepeatedRow(row=display_rows[row], count=len(origins), origins=tuple(origins))
        for row, origins in inventories.items()
        if len(origins) > 1
    ]
    repeated.sort(key=lambda item: first_order[item.row])
    return tuple(repeated)
