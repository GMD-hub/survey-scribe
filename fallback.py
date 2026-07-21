"""
Fallback Pipeline (No LLM)
==========================
Mirrors the steps of the original pipeline (pipeline.py) but replaces every
LLM/Anthropic API call with deterministic, regex-based heuristics so the
pipeline can run without an API key:

  1.  Pre-process: convert PDF -> Markdown with Docling (OCR-enabled, using
      the PyPdfiumDocumentBackend to avoid the docling-parse std::bad_alloc
      bug — see docs/), then chunk by section heading.
  2.  Extract survey metadata heuristically from the document opening
      (regex/keyword matching instead of an LLM call).
  3.  Extract variables from each section chunk using regex heuristics
      (instead of an LLM call). To keep runtime/manual-review effort bounded
      and to make the "no LLM" limitation obvious in the output, only the
      FIRST HALF of the document's sections are processed; this is called
      out explicitly in the console output and in extraction_notes.
  4.  Apply the same quality gate as the original pipeline (flag low
      confidence variables for human review).
  5.  Write SVIS JSON to output_dir/{survey_id}_fallback_svis.json

Usage:
  python fallback.py path/to/questionnaire.pdf
  python fallback.py path/to/questionnaire.md
"""
from __future__ import annotations

import argparse
import math
import re
from datetime import date
from pathlib import Path

from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption

from extractors.pdf import DocumentChunk, chunk_markdown
from schemas.svis import (
    AnswerCategory,
    DataType,
    NumericRange,
    StudyType,
    SurveySVIS,
    SurveyVariable,
    UnitLevel,
)


# Confidence threshold below which a variable is flagged for human review.
# Mirrors REVIEW_THRESHOLD in pipeline.py so the quality gate reads the same way.
REVIEW_THRESHOLD = 0.70

# Number of characters from the first chunk used for metadata heuristics.
# Mirrors METADATA_CHAR_LIMIT in pipeline.py.
METADATA_CHAR_LIMIT = 3000


# Matches two common question-labeling conventions seen in these questionnaires:
#   1. Literal wording, e.g. "Question 14"
#   2. Coded question IDs at the start of a line, e.g. "B05a", "A.01", "HH04"
# Group 1 captures the literal-wording id, group 2 captures the coded id.
QUESTION_RE = re.compile(
    r"\bQuestion\s+([0-9]+[A-Za-z]?)\b"
    r"|^\s*([A-Z]{1,3}\.?[0-9]{1,3}[a-z]?)\b",
    re.IGNORECASE | re.MULTILINE,
)


def _process_pdf_with_docling(pdf_path: Path) -> list[DocumentChunk]:
    try:
        pipeline_options = PdfPipelineOptions(
            do_ocr=True,
            do_table_structure=True,
            generate_page_images=False,
            generate_picture_images=False,
        )
        # The default Docling PDF backend (docling-parse) has a known bug
        # that accumulates native memory across pages and crashes with
        # `std::bad_alloc` partway through longer/denser documents, silently
        # dropping every subsequent page with no exception raised.
        # See: https://github.com/docling-project/docling/issues/3671
        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_options=pipeline_options,
                    backend=PyPdfiumDocumentBackend,
                ),
            }
        )
        result = converter.convert(pdf_path)
        markdown = result.document.export_to_markdown()
    except Exception as exc:
        print(f"[ERROR] {pdf_path.name}  --  Docling conversion failed: {exc}")
        return []

    chunks = chunk_markdown(markdown)
    print(f"[OK]   {pdf_path.name}  --  {len(chunks)} section(s) extracted.")
    return chunks


def _process_markdown(markdown_path: Path) -> list[DocumentChunk]:
    markdown_text = markdown_path.read_text(encoding="utf-8")
    chunks = chunk_markdown(markdown_text)
    print(f"[OK]   {markdown_path.name}  --  {len(chunks)} section(s) extracted.")
    return chunks


# ── Survey metadata heuristics ────────────────────────────────────────────────

# Not exhaustive — covers the countries seen in the sample questionnaires plus
# other common LSMS/DHS survey countries. Falls back to "UNK" if no match.
_COUNTRY_NAME_TO_ISO3 = {
    "burkina faso": "BFA", "bangladesh": "BGD", "ethiopia": "ETH",
    "kenya": "KEN", "nigeria": "NGA", "vietnam": "VNM", "viet nam": "VNM",
    "colombia": "COL", "india": "IND", "pakistan": "PAK", "ghana": "GHA",
    "uganda": "UGA", "tanzania": "TZA", "rwanda": "RWA", "malawi": "MWI",
    "zambia": "ZMB", "mozambique": "MOZ", "senegal": "SEN", "mali": "MLI",
    "niger": "NER", "chad": "TCD", "cameroon": "CMR",
    "cote d'ivoire": "CIV", "ivory coast": "CIV", "morocco": "MAR",
    "tunisia": "TUN", "egypt": "EGY", "nepal": "NPL", "philippines": "PHL",
    "indonesia": "IDN", "cambodia": "KHM", "myanmar": "MMR",
    "sri lanka": "LKA",
}

_STUDY_TYPE_KEYWORDS: dict[str, StudyType] = {
    "income and expenditure": StudyType.lsms,
    "living standards": StudyType.lsms,
    "lsms": StudyType.lsms,
    "demographic and health": StudyType.dhs,
    "labour force": StudyType.lfs,
    "labor force": StudyType.lfs,
    "health survey": StudyType.hhs,
    "multiple indicator cluster": StudyType.mics,
    "core welfare": StudyType.cwiq,
    "census": StudyType.census,
}

_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


def _guess_survey_metadata(opening_text: str, filename: str) -> dict:
    """
    Heuristic replacement for extract_survey_metadata() in agents/svis_agent.py.
    Uses filename conventions and keyword/regex matching over the document
    opening instead of an LLM call. Results are best-effort and should be
    reviewed — see extraction_notes on the resulting SurveySVIS.
    """
    stem = Path(filename).stem
    text_lower = opening_text.lower()

    # Country code: prefer an ISO3 prefix in the filename (e.g. "BFA_..."),
    # else search the document opening for a known country name.
    country_code = "UNK"
    filename_match = re.match(r"^([A-Z]{3})[_\-]", Path(filename).name)
    if filename_match:
        country_code = filename_match.group(1)
    else:
        for name, iso3 in _COUNTRY_NAME_TO_ISO3.items():
            if name in text_lower:
                country_code = iso3
                break

    # Year: prefer the filename, fall back to the document opening.
    year = 0
    year_search = _YEAR_RE.search(Path(filename).name) or _YEAR_RE.search(opening_text)
    if year_search:
        year = int(year_search.group(0))

    # Study type: first keyword match wins.
    study_type = StudyType.other
    for keyword, stype in _STUDY_TYPE_KEYWORDS.items():
        if keyword in text_lower:
            study_type = stype
            break

    # Survey name: look for a plausible title line in the opening text,
    # else fall back to a humanized filename.
    survey_name = None
    for line in opening_text.splitlines():
        stripped = line.strip().strip("#").strip()
        if not (8 <= len(stripped) <= 120):
            continue
        if re.search(r"\b(survey|questionnaire|enquête|enquete|census|recensement)\b", stripped, re.IGNORECASE):
            survey_name = stripped
            break
    if not survey_name:
        survey_name = stem.replace("_", " ").replace("-", " ").strip()

    # Survey id: COUNTRYISO3_YEAR_ACRONYM when both are known, else sanitized filename stem.
    stem_no_country = stem
    if country_code != "UNK":
        stem_no_country = re.sub(rf"^{country_code}[_\-]?", "", stem, flags=re.IGNORECASE)
    caps_tokens = re.findall(r"\b[A-Z]{2,8}\b", stem_no_country)
    letters_tokens = re.findall(r"[A-Za-z]+", stem_no_country)
    if caps_tokens:
        acronym = caps_tokens[0]
    elif letters_tokens:
        acronym = letters_tokens[0][:8].upper()
    else:
        acronym = "SVY"

    if country_code != "UNK" and year:
        survey_id = f"{country_code}_{year}_{acronym}"
    else:
        survey_id = re.sub(r"[^A-Za-z0-9_]+", "_", stem).strip("_") or "unknown_survey"

    return {
        "survey_name": survey_name,
        "country_code": country_code,
        "year": year,
        "study_type": study_type,
        "survey_id": survey_id,
    }


# ── Variable extraction heuristics ────────────────────────────────────────────

def _guess_question_text(chunk_text: str) -> str | None:
    for line in chunk_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        if stripped.startswith("|"):
            continue
        if stripped.startswith("-"):
            continue
        return stripped[:500]
    return None


_MISSING_KEYWORDS = (
    "ne sait pas", "nsp", "don't know", "dont know", "dk", "refused", "refus",
    "not stated", "non déclaré", "non declare", "not applicable", "n/a",
    "no information", "missing",
)

_NUMERIC_KEYWORDS = (
    "age", "âge", "combien", "nombre", "montant", "revenu", "income", "amount",
    "quantity", "quantité", "number of", "how many", "years", "années", "size",
    "superficie", "distance", "prix", "price", "cost", "coût",
)

_DATE_KEYWORDS = ("date", "naissance", "born", "birth")

_ROSTER_KEYWORDS = ("membre", "member", "roster", "[nom]", "[name]")

_NUMBERED_OPTION_RE = re.compile(r"^\s*(\d{1,3})\s*[-.\)]+\s*(.+?)\s*$")

_RANGE_RE = re.compile(
    r"(?:entre|between)\s+(\d+)\s+(?:et|and)\s+(\d+)"
    r"|\((\d+)\s*[-–]\s*(\d+)\)",
    re.IGNORECASE,
)


def _looks_like_option_line(line: str) -> bool:
    if not line or len(line) > 40:
        return False
    if QUESTION_RE.search(line):
        return False
    if line.startswith(("#", "|", "-", "*")):
        return False
    if "?" in line:
        return False
    word_count = len(line.split())
    return 1 <= word_count <= 6


def _parse_categories(body_lines: list[str]) -> tuple[list[AnswerCategory] | None, bool]:
    """
    Scans the lines following a question for an answer-option list.
    Returns (categories, explicit_codes) where explicit_codes is True if
    numeric codes were printed in the source (more reliable) rather than
    inferred from a bare list of option labels.
    """
    categories: list[AnswerCategory] = []
    explicit_codes = False

    for raw_line in body_lines:
        stripped = raw_line.strip()
        if not stripped:
            continue
        numbered = _NUMBERED_OPTION_RE.match(stripped)
        if numbered:
            code = int(numbered.group(1))
            label = numbered.group(2).strip(" -")
            is_missing = any(k in label.lower() for k in _MISSING_KEYWORDS)
            categories.append(AnswerCategory(code=code, label=label, is_missing=is_missing))
            explicit_codes = True
        elif _looks_like_option_line(stripped):
            code = len(categories) + 1
            is_missing = any(k in stripped.lower() for k in _MISSING_KEYWORDS)
            categories.append(AnswerCategory(code=code, label=stripped, is_missing=is_missing))

        if len(categories) >= 12:
            break

    if len(categories) < 2:
        return None, False
    return categories, explicit_codes


def _guess_data_type(question_text: str | None, categories: list[AnswerCategory] | None) -> DataType:
    text = (question_text or "").lower()
    if categories:
        return DataType.categorical_single
    if any(k in text for k in _DATE_KEYWORDS):
        return DataType.date
    if any(k in text for k in _NUMERIC_KEYWORDS):
        return DataType.numeric
    return DataType.text


def _guess_numeric_range(segment: str) -> NumericRange | None:
    match = _RANGE_RE.search(segment)
    if not match:
        return None
    values = [g for g in match.groups() if g is not None]
    if len(values) != 2:
        return None
    lo, hi = sorted(int(v) for v in values)
    return NumericRange(
        min_value=lo,
        max_value=hi,
        notes="Extracted heuristically from a range pattern near the question text.",
    )


def _guess_universe(chunk_text_lower: str, question_text: str | None) -> str | None:
    text = (question_text or "").lower()
    if "chef de ménage" in text or "household head" in text or "head of household" in text:
        return "Household head only"
    if any(k in chunk_text_lower for k in _ROSTER_KEYWORDS) or any(k in text for k in _ROSTER_KEYWORDS):
        return "All household members"
    return None


def _guess_unit_of_analysis(module_name: str, universe: str | None) -> UnitLevel:
    module_lower = module_name.lower()
    if universe and "household" in universe.lower() and "head" not in universe.lower():
        return UnitLevel.household
    if any(k in module_lower for k in ("dwelling", "housing", "logement", "habitat")) and "member" not in module_lower:
        return UnitLevel.household
    return UnitLevel.individual


def _build_label(question_text: str | None, qid: str) -> str:
    if not question_text:
        return f"Question {qid}"
    label = re.sub(r"\[.*?\]", "", question_text).strip(" ?:")
    label = re.sub(r"\s+", " ", label)
    return label[:80] if label else f"Question {qid}"


def _extract_variables_from_chunk(chunk: DocumentChunk) -> list[SurveyVariable]:
    """
    Heuristic replacement for extract_variables_from_chunk() in
    agents/svis_agent.py. Splits the chunk text at each detected question
    marker and parses the following lines for an answer-option list,
    instead of calling an LLM.
    """
    variables: list[SurveyVariable] = []
    seen_names: set[str] = set()
    chunk_text_lower = chunk.text.lower()

    match_positions = [
        (m.start(), m.group(1) or m.group(2))
        for m in QUESTION_RE.finditer(chunk.text)
    ]
    if not match_positions:
        return []

    for i, (offset, qid) in enumerate(match_positions):
        end_offset = match_positions[i + 1][0] if i + 1 < len(match_positions) else len(chunk.text)
        segment = chunk.text[offset:end_offset]

        raw_name = f"q{qid.lower().replace('.', '')}"
        if raw_name in seen_names:
            continue
        seen_names.add(raw_name)

        question_text = _guess_question_text(segment)
        if question_text:
            question_text = re.sub(rf"^\s*{re.escape(qid)}\.?\s*", "", question_text, flags=re.IGNORECASE).strip()
            question_text = question_text or None

        body_lines = segment.splitlines()[1:]
        categories, explicit_codes = _parse_categories(body_lines)
        data_type = _guess_data_type(question_text, categories)
        numeric_range = _guess_numeric_range(segment) if data_type == DataType.numeric else None
        universe = _guess_universe(chunk_text_lower, question_text)
        unit_of_analysis = _guess_unit_of_analysis(chunk.module_name, universe)
        label = _build_label(question_text, qid)

        # Confidence is built up from how much structure was reliably recovered.
        # This is a heuristic, non-LLM pipeline, so scores are conservative —
        # only very complete records (explicit codes + question text + universe)
        # clear the review threshold.
        confidence = 0.4
        if question_text and len(question_text) > 10:
            confidence += 0.15
        if categories:
            confidence += 0.20 if explicit_codes else 0.10
        if data_type != DataType.text:
            confidence += 0.10
        if universe:
            confidence += 0.05
        if numeric_range:
            confidence += 0.05
        confidence = round(min(confidence, 0.95), 2)

        needs_review = (
            confidence < REVIEW_THRESHOLD
            or question_text is None
            or (data_type == DataType.categorical_single and not categories)
        )

        variables.append(
            SurveyVariable(
                raw_name=raw_name,
                label=label,
                question_text=question_text,
                data_type=data_type,
                categories=categories,
                numeric_range=numeric_range,
                universe=universe,
                module=chunk.module_name,
                unit_of_analysis=unit_of_analysis,
                source_page=chunk.page_start,
                extraction_confidence=confidence,
                needs_review=needs_review,
                notes=(
                    None if not needs_review else
                    "Heuristic fallback extraction (no LLM) — verify all fields against the source PDF."
                ),
            )
        )

    return variables


def run(input_path: Path, output_dir: Path) -> None:
    print(f"\n{'=' * 60}")
    print(f"  Processing: {input_path.name}")
    print(f"{'=' * 60}")

    if input_path.suffix.lower() == ".pdf":
        chunks = _process_pdf_with_docling(input_path)
    elif input_path.suffix.lower() in {".md", ".markdown"}:
        chunks = _process_markdown(input_path)
    else:
        print(f"  [SKIP] Unsupported file type: {input_path.suffix}\n")
        return

    if not chunks:
        print("  [SKIP] No content chunks produced after conversion.\n")
        return

    # ── Step 1: Survey metadata (heuristic, no LLM) ───────────────────────────
    print("\n  [1/3] Extracting survey metadata ...")
    opening_text = chunks[0].text[:METADATA_CHAR_LIMIT]
    meta = _guess_survey_metadata(opening_text, input_path.name)
    print(f"        Survey  : {meta['survey_name']}")
    print(f"        Country : {meta['country_code']}  |  Year: {meta['year']}")
    print(f"        Type    : {meta['study_type'].value}")

    # ── Step 2: Variable extraction — first half of sections only ─────────────
    # No LLM is available, so instead of guessing at every section with low
    # confidence, we deliberately limit heuristic extraction to the first
    # half of the document's sections and make that explicit here.
    half_count = max(1, math.ceil(len(chunks) / 2))
    chunks_to_process = chunks[:half_count]
    print(
        f"\n  [2/3] Extracting variables from {half_count} of {len(chunks)} section(s) "
        "(fallback heuristics, no LLM — first half of the PDF only) ..."
    )

    all_variables: list[SurveyVariable] = []
    for chunk in chunks_to_process:
        label = chunk.module_name[:55]
        variables = _extract_variables_from_chunk(chunk)
        all_variables.extend(variables)
        flagged = sum(1 for v in variables if v.needs_review)
        print(f"        [{chunk.chunk_index:02d}] {label:<55}  "
              f"{len(variables):3d} vars  ({flagged} flagged)")

    # ── Step 3: Quality gate summary ──────────────────────────────────────────
    flagged_vars = [v for v in all_variables if v.needs_review]
    print(f"\n  [3/3] Quality gate (threshold = {REVIEW_THRESHOLD}):")
    print(f"        Total variables extracted : {len(all_variables):3d}")
    print(f"        Flagged for human review  : {len(flagged_vars):3d}")
    if flagged_vars:
        names = ", ".join(v.raw_name for v in flagged_vars[:10])
        if len(flagged_vars) > 10:
            names += f" ... and {len(flagged_vars) - 10} more"
        print(f"        Flagged names             : {names}")

    questionnaire = SurveySVIS(
        survey_id=meta["survey_id"],
        country_code=meta["country_code"],
        year=meta["year"],
        survey_name=meta["survey_name"],
        study_type=meta["study_type"],
        variables=all_variables,
        source_file=input_path.name,
        source_format=input_path.suffix.lstrip(".").lower(),
        extraction_date=date.today(),
        extraction_notes=(
            "Fallback pipeline output (no LLM/API calls; heuristic regex-based extraction). "
            f"Variables extracted from the first {half_count} of {len(chunks)} section(s) "
            "(roughly half of the document); remaining sections were not processed. "
            "All metadata and variables require human review."
        ),
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{questionnaire.survey_id}_fallback_svis.json"
    output_file.write_text(questionnaire.model_dump_json(indent=2), encoding="utf-8")

    print(f"\n  [DONE] Output --> {output_file}")
    print(f"{'=' * 60}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run SVIS fallback pipeline without LLM/API calls.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python fallback.py questionnaire.pdf\n"
            "  python fallback.py questionnaire.md\n"
            "  python fallback.py questionnaire.pdf --output-dir ./output\n"
        ),
    )
    parser.add_argument("input_file", type=Path, help="Path to questionnaire PDF or Markdown file.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="Directory for fallback SVIS JSON output. Default: ./output",
    )
    args = parser.parse_args()

    if not args.input_file.exists():
        print(f"Error: file not found: {args.input_file}")
        raise SystemExit(1)

    if args.input_file.suffix.lower() not in {".pdf", ".md", ".markdown"}:
        print(f"Error: expected a .pdf or .md file, got: {args.input_file.suffix}")
        raise SystemExit(1)

    run(args.input_file, args.output_dir)


if __name__ == "__main__":
    main()
