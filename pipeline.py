"""
Pipeline Orchestrator
======================
Main entry point for the GMD survey parser.

Given a questionnaire PDF, runs the full extraction pipeline
and writes a validated SVIS JSON file.

Usage (command line):
    python pipeline.py path/to/questionnaire.pdf
    python pipeline.py path/to/questionnaire.pdf --output-dir ./output

Usage (from Python):
    from pathlib import Path
    from pipeline import run
    run(Path("questionnaire.pdf"), Path("output"))
"""
from __future__ import annotations

import argparse
from pathlib import Path

import instructor

from agents.svis_agent import extract_survey_metadata, extract_variables_from_chunk
from extractors.pdf import process_pdf


# ── Configuration ─────────────────────────────────────────────────────────────

# Number of characters from the first chunk to send for metadata extraction.
# The first chunk is typically the cover page. Sending the full first chunk
# avoids truncating mid-sentence in case the cover page has a lot of text.
METADATA_CHAR_LIMIT = 3000

# Confidence threshold below which a variable is flagged for human review.
# This mirrors the threshold described in the schema and the prompts.
# Change here if you want to adjust the sensitivity of the quality gate.
REVIEW_THRESHOLD = 0.70


# ── Pipeline ──────────────────────────────────────────────────────────────────

def run(pdf_path: Path, output_dir: Path) -> None:
    """
    Full extraction pipeline for one PDF questionnaire.

    Steps:
      1.  Pre-process: detect scan, convert to Markdown, chunk by section
      2.  Extract survey metadata from the document opening
      3.  Extract variables from each section chunk (loop)
      4.  Apply quality gate: flag low-confidence variables
      5.  Write SVIS JSON to output_dir/{survey_id}_svis.json

    Scanned PDFs are logged and skipped (OCR out of scope).
    Chunks that fail after instructor's automatic retries are caught,
    logged, and skipped with a note in the output.
    """
    print(f"\n{'=' * 60}")
    print(f"  Processing: {pdf_path.name}")
    print(f"{'=' * 60}")

    # ── Step 1: Pre-process ───────────────────────────────────────────────────
    is_scanned, chunks = process_pdf(pdf_path)

    if is_scanned:
        print("  [SKIP] Scanned PDF — cannot extract without OCR.\n")
        return

    if not chunks:
        print("  [SKIP] No content chunks produced after conversion.\n")
        return

    print(f"  {len(chunks)} section(s) to process.\n")

    # ── Step 2: Survey metadata ───────────────────────────────────────────────
    print("  [1/3] Extracting survey metadata ...")
    opening_text = chunks[0].text[:METADATA_CHAR_LIMIT]
    try:
        questionnaire = extract_survey_metadata(
            opening_text=opening_text,
            source_file=pdf_path.name,
            source_format="pdf",
        )
        print(f"        Survey  : {questionnaire.survey_name}")
        print(f"        Country : {questionnaire.country_code}  |  Year: {questionnaire.year}")
        print(f"        Type    : {questionnaire.study_type}")
    except instructor.exceptions.InstructorRetryException as exc:
        print(f"  [ERROR] Metadata extraction failed after retries: {exc}")
        print("          Using placeholder metadata. Manually correct the output file.\n")
        from schemas.svis import SurveySVIS
        from datetime import date
        questionnaire = SurveySVIS(
            survey_id=pdf_path.stem,
            country_code="UNK",
            year=0,
            survey_name=pdf_path.stem,
            variables=[],
            source_file=pdf_path.name,
            source_format="pdf",
            extraction_date=date.today(),
            extraction_notes="Metadata extraction failed — fill in manually.",
        )

    # ── Step 3: Variable extraction ───────────────────────────────────────────
    print(f"\n  [2/3] Extracting variables from {len(chunks)} section(s) ...")
    all_variables = []
    skipped_chunks = []

    for chunk in chunks:
        label = chunk.module_name[:55]
        try:
            variables = extract_variables_from_chunk(chunk)
            all_variables.extend(variables)
            flagged = sum(1 for v in variables if v.needs_review)
            print(f"        [{chunk.chunk_index:02d}] {label:<55}  "
                  f"{len(variables):3d} vars  ({flagged} flagged)")
        except instructor.exceptions.InstructorRetryException as exc:
            print(f"        [{chunk.chunk_index:02d}] {label:<55}  "
                  f"ERROR — {exc}")
            skipped_chunks.append(chunk.module_name)

    questionnaire.variables = all_variables

    if skipped_chunks:
        note = f"Sections that failed extraction after retries: {skipped_chunks}"
        questionnaire.extraction_notes = (
            (questionnaire.extraction_notes or "") + " " + note
        ).strip()

    # ── Step 4: Quality gate summary ─────────────────────────────────────────
    flagged_vars = [v for v in all_variables if v.needs_review]
    print(f"\n  [3/3] Quality gate (threshold = {REVIEW_THRESHOLD}):")
    print(f"        Total variables extracted : {len(all_variables)}")
    print(f"        Flagged for human review  : {len(flagged_vars)}")
    if flagged_vars:
        names = ", ".join(v.raw_name for v in flagged_vars[:10])
        if len(flagged_vars) > 10:
            names += f" ... and {len(flagged_vars) - 10} more"
        print(f"        Flagged names             : {names}")

    # ── Step 5: Write output ──────────────────────────────────────────────────
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{questionnaire.survey_id}_svis.json"
    output_file.write_text(
        questionnaire.model_dump_json(indent=2),
        encoding="utf-8",
    )
    print(f"\n  [DONE] Output → {output_file}")
    print(f"{'=' * 60}\n")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract structured variable information from a questionnaire PDF.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python pipeline.py questionnaire.pdf\n"
            "  python pipeline.py questionnaire.pdf --output-dir ./output\n"
        ),
    )
    parser.add_argument(
        "pdf",
        type=Path,
        help="Path to the questionnaire PDF.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="Directory for SVIS JSON output. Created if it does not exist. Default: ./output",
    )
    args = parser.parse_args()

    if not args.pdf.exists():
        print(f"Error: file not found: {args.pdf}")
        raise SystemExit(1)

    if args.pdf.suffix.lower() != ".pdf":
        print(f"Error: expected a .pdf file, got: {args.pdf.suffix}")
        raise SystemExit(1)

    run(args.pdf, args.output_dir)


if __name__ == "__main__":
    main()
