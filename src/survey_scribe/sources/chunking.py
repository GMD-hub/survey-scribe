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
    """One typed whole block or deterministic text-block segment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    block_id: str
    part_index: int = Field(ge=1)
    part_count: int = Field(ge=1)
    kind: Literal["text", "table"]
    text: str
    provenance: SourceProvenance
    table: SourceTable | None = None

    @model_validator(mode="after")
    def validate_part(self) -> SourceChunkPart:
        if self.part_index > self.part_count:
            raise ValueError("part_index must not exceed part_count")
        if (self.kind == "table") != (self.table is not None):
            raise ValueError("table chunk parts must retain their typed table")
        if self.table is not None and self.table.provenance != self.provenance:
            raise ValueError("chunk-part table provenance must match its part provenance")
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


class ChunkedDocument(BaseModel):
    """Deterministic chunks and completeness inventory for one source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_name: str
    chunks: tuple[SourceChunk, ...]
    repeated_rows: tuple[RepeatedRow, ...]


def chunk_document(
    document: SourceDocument,
    *,
    max_tokens: int,
    overlap_tokens: int = 0,
    estimator: TokenEstimator | None = None,
) -> ChunkedDocument:
    """Chunk without dropping preamble, complete tables, or source order.

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
    """
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
                provenance=tuple(part.block.provenance for part in all_parts),
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


def _split_blocks(
    blocks: tuple[SourceBlock, ...],
    *,
    max_tokens: int,
    text_budget: int,
    estimator: TokenEstimator,
) -> tuple[_BlockPart, ...]:
    parts: list[_BlockPart] = []
    for block in blocks:
        if block.kind == "table":
            if estimator.estimate(block.text) > max_tokens:
                raise SourceLimitError(
                    "max_tokens",
                    "A source table exceeds the token limit and cannot be split safely",
                )
            parts.append(
                _BlockPart(
                    block=block,
                    id=f"{block.id}:part-000001",
                    part_index=1,
                    part_count=1,
                    text=block.text,
                )
            )
            continue
        text_parts = _split_text(block.text, max_tokens=text_budget, estimator=estimator)
        part_count = len(text_parts)
        parts.extend(
            _BlockPart(
                block=block,
                id=f"{block.id}:part-{index:06d}",
                part_index=index,
                part_count=part_count,
                text=text,
            )
            for index, text in enumerate(text_parts, start=1)
        )
    return tuple(parts)


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
        if part.block.kind == "table":
            if current:
                groups.append(tuple(current))
                current = []
                current_tokens = 0
            groups.append((part,))
            continue
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
        provenance=part.block.provenance,
        table=part.block.table,
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
