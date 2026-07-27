"""
Language Agent
=======================
Fills in the `language` / `language_confidence` fields on TextBlock
records already produced by the Text Structure Agent
(agents/text_agent.py). Deterministic -- no LLM call, no API key needed.

Uses the `lingua` library (statistical n-gram language detection)
rather than an LLM because language identification is a closed
classification task, not a reasoning task:
  - it reports a real per-call confidence value (0.0-1.0), matching
    TextBlock.language_confidence exactly
  - it is explicitly designed to handle short strings and mixed-language
    documents -- both common in these survey questionnaires (bilingual
    instructions, short answer-option labels like "Yes"/"Oui", etc.)
  - it is free and instant compared to an LLM call per block

Consumed by the eventual document-metadata orchestrator, which merges
this agent's output with the Text Structure Agent's output (they
operate on and mutate the same TextBlock records, keyed by block_id)
and the future table/image agents into one JSON file.
"""
from __future__ import annotations

from lingua import Language, LanguageDetectorBuilder

from schemas.text_structure import TextBlock

# Below this many characters, statistical language detection is
# unreliable -- a heading like "3.2" or a short label like "Yes/No"
# gives the detector almost nothing to work with. Blocks shorter than
# this are left with language=None rather than guessing.
_MIN_CHARS_FOR_DETECTION = 12

# Built once per process and reused across calls -- constructing the
# detector loads n-gram language models, which is the expensive part.
_detector = (
    LanguageDetectorBuilder.from_all_languages()
    .with_preloaded_language_models()
    .build()
)


def _iso_code(language: Language) -> str:
    """Lowercase ISO 639-1 code, e.g. Language.ENGLISH -> "en"."""
    return language.iso_code_639_1.name.lower()


def tag_languages(blocks: list[TextBlock]) -> list[TextBlock]:
    """
    Detects the language of each block's text and fills in
    TextBlock.language / TextBlock.language_confidence in place.

    Blocks shorter than _MIN_CHARS_FOR_DETECTION, or blocks where the
    detector cannot confidently identify any language, are left with
    language=None / language_confidence=None.

    Mutates and returns the same list passed in, so callers can chain
    this directly onto the Text Structure Agent's output:

        structure = build_text_structure(doc, source_file=pdf_path.name)
        tag_languages(structure.blocks)
    """
    for block in blocks:
        if block.char_count < _MIN_CHARS_FOR_DETECTION:
            continue

        detected = _detector.detect_language_of(block.text)
        if detected is None:
            continue

        block.language = _iso_code(detected)
        block.language_confidence = _detector.compute_language_confidence(
            block.text, detected,
        )

    return blocks


def compute_primary_language(blocks: list[TextBlock]) -> tuple[str, float] | None:
    """
    Summarizes the per-block language tags set by tag_languages() into a
    single document-level "main language": the ISO 639-1 code accounting
    for the most tagged characters across all blocks, weighted by
    char_count rather than a simple block count (so one long paragraph
    outweighs many short headings/labels in a different language).

    Returns (language, share) where share is that language's fraction
    (0.0-1.0) of all tagged characters, or None if no blocks were
    confidently tagged with a language (e.g. tag_languages() was never
    called, or every block was too short to classify).
    """
    char_totals: dict[str, int] = {}
    for block in blocks:
        if block.language is None:
            continue
        char_totals[block.language] = char_totals.get(block.language, 0) + block.char_count

    if not char_totals:
        return None

    total_chars = sum(char_totals.values())
    primary_language = max(char_totals, key=char_totals.get)
    return primary_language, char_totals[primary_language] / total_chars
