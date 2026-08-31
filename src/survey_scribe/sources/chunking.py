"""Deterministic token-aware chunking with table and overlap provenance."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from survey_scribe.sources.base import SourceBlock, SourceDocument, SourceProvenance


class TokenEstimator(Protocol):
    """Minimal tokenizer-independent estimation port."""

    def estimate(self, text: str) -> int:
        """Return a deterministic non-negative token estimate."""
        ...


class ConservativeTokenEstimator:
    """Dependency-free fallback that budgets one token per three characters."""

    def estimate(self, text: str) -> int:
        if not text:
            return 0
        return max(1, math.ceil(len(text) / 3))


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
        max_tokens: Target maximum for grouped text blocks. A complete table or
            one large block can exceed this value.
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
    groups = _group_blocks(document.blocks, max_tokens=max_tokens, estimator=token_estimator)
    chunks: list[SourceChunk] = []
    previous_new: tuple[SourceBlock, ...] = ()
    for new_blocks in groups:
        overlap = _overlap_tail(previous_new, overlap_tokens, token_estimator)
        all_blocks = overlap + new_blocks
        chunks.append(
            SourceChunk(
                id=f"chunk-{len(chunks) + 1:06d}",
                order=len(chunks),
                text="\n\n".join(block.text for block in all_blocks),
                block_ids=tuple(block.id for block in all_blocks),
                new_block_ids=tuple(block.id for block in new_blocks),
                overlap_block_ids=tuple(block.id for block in overlap),
                provenance=tuple(block.provenance for block in all_blocks),
            )
        )
        previous_new = new_blocks
    return ChunkedDocument(
        source_name=document.source_name,
        chunks=tuple(chunks),
        repeated_rows=_repeated_rows(document),
    )


def _group_blocks(
    blocks: tuple[SourceBlock, ...],
    *,
    max_tokens: int,
    estimator: TokenEstimator,
) -> tuple[tuple[SourceBlock, ...], ...]:
    groups: list[tuple[SourceBlock, ...]] = []
    current: list[SourceBlock] = []
    current_tokens = 0
    for block in blocks:
        block_tokens = estimator.estimate(block.text)
        if block.kind == "table":
            if current:
                groups.append(tuple(current))
                current = []
                current_tokens = 0
            groups.append((block,))
            continue
        separator_tokens = estimator.estimate("\n\n") if current else 0
        if current and current_tokens + separator_tokens + block_tokens > max_tokens:
            groups.append(tuple(current))
            current = []
            current_tokens = 0
            separator_tokens = 0
        current.append(block)
        current_tokens += separator_tokens + block_tokens
    if current:
        groups.append(tuple(current))
    return tuple(groups)


def _overlap_tail(
    previous: tuple[SourceBlock, ...],
    overlap_tokens: int,
    estimator: TokenEstimator,
) -> tuple[SourceBlock, ...]:
    if overlap_tokens == 0:
        return ()
    selected: list[SourceBlock] = []
    used = 0
    for block in reversed(previous):
        if block.kind == "table":
            continue
        tokens = estimator.estimate(block.text)
        separator = estimator.estimate("\n\n") if selected else 0
        if used + separator + tokens > overlap_tokens:
            break
        selected.append(block)
        used += separator + tokens
    return tuple(reversed(selected))


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
