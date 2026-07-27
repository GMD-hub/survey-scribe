"""
Tests for the Language Agent (agents/language_agent.py).

Builds plain TextBlock records directly (no PDF/Docling conversion
involved) so these tests are fast and exercise only the language
detection + confidence logic.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.language_agent import compute_primary_language, tag_languages
from schemas.text_structure import TextBlock


def _block(block_id: int, text: str) -> TextBlock:
    return TextBlock(
        block_id=block_id,
        page=1,
        label="text",
        heading_level=None,
        parent_path=[],
        text=text,
        char_count=len(text),
    )


def test_english_paragraph_detected_as_en():
    blocks = [_block(0, "How many people currently live in this household?")]
    tag_languages(blocks)
    assert blocks[0].language == "en"
    assert blocks[0].language_confidence is not None
    assert 0.0 <= blocks[0].language_confidence <= 1.0


def test_french_paragraph_detected_as_fr():
    blocks = [_block(0, "Combien de personnes vivent actuellement dans ce ménage ?")]
    tag_languages(blocks)
    assert blocks[0].language == "fr"


def test_short_block_below_threshold_is_left_untagged():
    blocks = [_block(0, "Yes/No")]
    tag_languages(blocks)
    assert blocks[0].language is None
    assert blocks[0].language_confidence is None


def test_empty_text_is_left_untagged():
    blocks = [_block(0, "")]
    tag_languages(blocks)
    assert blocks[0].language is None
    assert blocks[0].language_confidence is None


def test_mutates_and_returns_same_list():
    blocks = [_block(0, "How many people currently live in this household?")]
    result = tag_languages(blocks)
    assert result is blocks


def test_mixed_language_document_tags_each_block_independently():
    blocks = [
        _block(0, "How many people currently live in this household?"),
        _block(1, "Combien de personnes vivent actuellement dans ce ménage ?"),
    ]
    tag_languages(blocks)
    assert blocks[0].language == "en"
    assert blocks[1].language == "fr"


def test_primary_language_picks_language_with_most_tagged_characters():
    blocks = [
        _block(0, "How many people currently live in this household?"),
        _block(1, "How many rooms does this dwelling have in total?"),
        _block(2, "Combien de personnes vivent actuellement dans ce ménage ?"),
    ]
    tag_languages(blocks)
    result = compute_primary_language(blocks)
    assert result is not None
    language, share = result
    assert language == "en"
    assert 0.0 < share <= 1.0


def test_primary_language_is_none_when_nothing_tagged():
    blocks = [_block(0, "Yes/No")]  # below detection threshold
    tag_languages(blocks)
    assert compute_primary_language(blocks) is None
