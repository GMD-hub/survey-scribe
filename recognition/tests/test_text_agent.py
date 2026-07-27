"""
Tests for the Text Structure Agent (agents/text_agent.py).

Builds a small DoclingDocument programmatically (no PDF/Docling
conversion involved) so these tests are fast and exercise only the
heading-hierarchy logic in build_text_structure().
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docling_core.types.doc.document import DoclingDocument
from docling_core.types.doc.labels import DocItemLabel

from agents.text_agent import build_text_structure


def _sample_doc() -> DoclingDocument:
    doc = DoclingDocument(name="sample")
    doc.add_title("Sample Questionnaire")
    doc.add_heading("Section 1: Household Roster", level=1)
    doc.add_text(DocItemLabel.TEXT, "How many people live in this household?")
    doc.add_heading("Section 2: Education", level=1)
    doc.add_heading("2.1 School attendance", level=2)
    doc.add_text(DocItemLabel.TEXT, "Is [NAME] currently attending school?")
    doc.add_heading("Section 3: Health", level=1)
    doc.add_text(DocItemLabel.TEXT, "Has [NAME] been ill in the past 4 weeks?")
    return doc


def test_title_gets_level_zero_and_no_parent():
    structure = build_text_structure(_sample_doc(), source_file="sample.pdf")
    title_block = structure.blocks[0]
    assert title_block.heading_level == 0
    assert title_block.parent_path == []
    assert title_block.text == "Sample Questionnaire"


def test_body_text_inherits_open_heading_as_parent():
    structure = build_text_structure(_sample_doc(), source_file="sample.pdf")
    body_blocks = [b for b in structure.blocks if b.heading_level is None]
    assert len(body_blocks) == 3
    assert body_blocks[0].parent_path == [
        "Sample Questionnaire", "Section 1: Household Roster",
    ]


def test_nested_heading_builds_two_level_parent_path():
    structure = build_text_structure(_sample_doc(), source_file="sample.pdf")
    body_blocks = [b for b in structure.blocks if b.heading_level is None]
    # "Is [NAME] currently attending school?" sits under Section 2 > 2.1
    assert body_blocks[1].parent_path == [
        "Sample Questionnaire", "Section 2: Education", "2.1 School attendance",
    ]


def test_sibling_heading_closes_previous_subsection():
    structure = build_text_structure(_sample_doc(), source_file="sample.pdf")
    body_blocks = [b for b in structure.blocks if b.heading_level is None]
    # "Has [NAME] been ill..." sits under Section 3, NOT under 2.1
    # (level-1 "Section 3" must have closed the level-2 "2.1" heading)
    assert body_blocks[2].parent_path == [
        "Sample Questionnaire", "Section 3: Health",
    ]


def test_char_count_matches_text_length():
    structure = build_text_structure(_sample_doc(), source_file="sample.pdf")
    for block in structure.blocks:
        assert block.char_count == len(block.text)


def test_page_defaults_to_zero_without_provenance():
    structure = build_text_structure(_sample_doc(), source_file="sample.pdf")
    assert all(block.page == 0 for block in structure.blocks)


def test_language_fields_are_unset_placeholders():
    structure = build_text_structure(_sample_doc(), source_file="sample.pdf")
    assert all(block.language is None for block in structure.blocks)
    assert all(block.language_confidence is None for block in structure.blocks)
