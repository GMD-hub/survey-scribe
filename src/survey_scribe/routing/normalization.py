"""Cycle-safe Unicode identity normalization shared across routing layers."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

_ALIAS_SEPARATORS_RE = re.compile(r"[\s._-]+")
_QUESTION_NUMBER_RE = re.compile(r"^(?:q|question)0*([0-9]+)$")
_NUMBER_RE = re.compile(r"^0*([0-9]+)$")
_TABLE_REFERENCE_RE = re.compile(r"^(?:col|column)[\s._-]+(.+)$")


def identity_slug(value: str) -> str:
    """Return a Unicode-aware stable slug without semantic matching."""
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    parts: list[str] = []
    separator = False
    for character in normalized:
        if character.isalnum():
            if separator and parts:
                parts.append("-")
            parts.append(character)
            separator = False
        else:
            separator = True
    return "".join(parts).strip("-")


def normalized_alias_value(value: str) -> str:
    """Return the canonical exact-alias value or reject empty identities."""
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    table_match = _TABLE_REFERENCE_RE.fullmatch(normalized)
    if table_match is not None:
        normalized = table_match.group(1).strip()
    compact = _ALIAS_SEPARATORS_RE.sub("", normalized)
    question_match = _QUESTION_NUMBER_RE.fullmatch(compact)
    if question_match is not None:
        return f"q{int(question_match.group(1))}"
    number_match = _NUMBER_RE.fullmatch(compact)
    if number_match is not None:
        return f"q{int(number_match.group(1))}"
    alias = identity_slug(normalized)
    if not alias:
        raise ValueError("item reference must contain identity characters")
    return alias


def normalize_section_path_value(section_path: Iterable[str]) -> tuple[str, ...]:
    """Normalize one section path without discarding Unicode hierarchy."""
    normalized = tuple(identity_slug(part) for part in section_path)
    if any(not part for part in normalized):
        raise ValueError("section path parts must contain identity characters")
    return normalized


__all__ = ["identity_slug", "normalize_section_path_value", "normalized_alias_value"]
