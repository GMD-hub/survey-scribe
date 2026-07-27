"""
Text Structure Agent
=======================
Builds a page- and heading-aware structure of every text block in a
DoclingDocument. Deterministic -- no LLM call, no API key needed.

Docling already reports, per text item:
  - page number (via item.prov[0].page_no)
  - heading level (via SectionHeaderItem.level / TitleItem)
  - reading order (via DoclingDocument.iterate_items())

This agent's job is purely to walk the document in reading order and
stitch that into a heading hierarchy (parent_path) per block -- a tree
walk, not a reasoning task.

Consumed downstream by:
  - the planned Language Agent, which will fill in TextBlock.language /
    language_confidence on the same records produced here
  - the eventual document-metadata orchestrator, which merges this
    output with the future table/image agents into one JSON file
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from docling_core.types.doc.document import (
    DoclingDocument,
    SectionHeaderItem,
    TextItem,
    TitleItem,
)

from schemas.text_structure import DocumentTextStructure, TextBlock

# TitleItem has no explicit .level attribute (it's always the outermost
# heading) so it is treated as heading_level 0; SectionHeaderItem carries
# its own .level (1, 2, 3, ... deeper as sections nest).
_TITLE_LEVEL = 0


def build_text_structure(doc: DoclingDocument, source_file: str) -> DocumentTextStructure:
    """
    Walks a DoclingDocument in reading order and produces one TextBlock
    per text item (paragraphs, list items, headings, captions, footnotes,
    etc.). Tables and pictures are separate DocItem subtypes (TableItem,
    PictureItem) and are naturally skipped by the isinstance check below
    -- they belong to the future Table Agent and Image Agent.

    Heading hierarchy is tracked with a stack keyed by heading level:
    each block's parent_path is the text of every heading currently
    "open" at a shallower level, shallowest first. Encountering a new
    heading closes any previously open heading at the same or a deeper
    level before registering itself as open.
    """
    blocks: list[TextBlock] = []
    heading_stack: dict[int, str] = {}   # level -> heading text open at that level

    block_id = 0
    for item, _tree_level in doc.iterate_items():
        if not isinstance(item, TextItem):
            continue   # skips TableItem, PictureItem, GroupItem, etc.

        text = item.text.strip()
        if not text:
            continue

        page = item.prov[0].page_no if item.prov else 0

        if isinstance(item, TitleItem):
            heading_level: int | None = _TITLE_LEVEL
        elif isinstance(item, SectionHeaderItem):
            heading_level = item.level
        else:
            heading_level = None

        if heading_level is not None:
            # Close any open heading at the same or a deeper level, then
            # compute parent_path from what remains, then open this one.
            for level in [lvl for lvl in heading_stack if lvl >= heading_level]:
                del heading_stack[level]
            parent_path = [heading_stack[lvl] for lvl in sorted(heading_stack)]
            heading_stack[heading_level] = text
        else:
            parent_path = [heading_stack[lvl] for lvl in sorted(heading_stack)]

        blocks.append(TextBlock(
            block_id=block_id,
            page=page,
            label=str(item.label),
            heading_level=heading_level,
            parent_path=parent_path,
            text=text,
            char_count=len(text),
        ))
        block_id += 1

    return DocumentTextStructure(
        source_file=Path(source_file).name,
        page_count=len(doc.pages),
        blocks=blocks,
        extraction_date=date.today(),
    )
