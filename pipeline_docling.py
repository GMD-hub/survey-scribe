"""
Docling Pipeline Orchestrator
==============================
Alternative entry point for the GMD survey parser that converts PDFs to
Markdown with Docling (extractors/docling_pdf.py) instead of MarkItDown
(extractors/pdf.py). Everything downstream — survey metadata extraction,
variable extraction, the quality gate, and SVIS JSON output — is
identical to pipeline.py and uses the same Azure OpenAI-backed agents
(agents/svis_agent.py).

Use this instead of pipeline.py when a questionnaire's tables or
scanned/image-heavy pages need Docling's OCR and table-structure model
rather than MarkItDown's lighter-weight conversion.

Usage (command line):
    python pipeline_docling.py path/to/questionnaire.pdf
    python pipeline_docling.py path/to/questionnaire.pdf --output-dir ./output

Usage (from Python):
    from pathlib import Path
    from pipeline_docling import run
    run(Path("questionnaire.pdf"), Path("output"))
"""
from __future__ import annotations

import argparse
from pathlib import Path

from instructor.v2.core.errors import InstructorError

from agents.svis_agent import extract_survey_metadata, extract_variables_from_chunk
from extractors.docling_pdf import process_pdf


# ── Configuration ─────────────────────────────────────────────────────────────

# Total character budget for the text sent to the metadata extraction call.
METADATA_CHAR_LIMIT = 3000

# Docling produces much finer-grained heading chunks than MarkItDown (one
# per sub-question block, not just per top-level section) -- so the actual
# cover-page/survey-title heading is often several chunks in rather than
# being chunk 0 (e.g. preceded by "INTERVIEWER", "TO BE FILLED BY THE
# SUPERVISOR", etc.). Metadata extraction therefore samples a bounded
# excerpt from each of the first MAX_CHUNKS_FOR_METADATA chunks instead of
# relying on chunk 0 alone, so the title heading isn't missed and one large
# early chunk (e.g. a household roster table) can't crowd out everything
# after it.
MAX_CHUNKS_FOR_METADATA = 15
MAX_CHARS_PER_CHUNK_FOR_METADATA = 400

# Confidence threshold below which a variable is flagged for human review.
# This mirrors the threshold described in the schema and the prompts.
# Change here if you want to adjust the sensitivity of the quality gate.
REVIEW_THRESHOLD = 0.70


# ── Pipeline ──────────────────────────────────────────────────────────────────

def run(pdf_path: Path, output_dir: Path) -> None:
    """
    Full extraction pipeline for one PDF questionnaire, using Docling
    for PDF -> Markdown conversion.

    Steps:
      1.  Pre-process: detect scan, convert to Markdown with Docling, chunk by section
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
        print("[SKIP] Scanned PDF -- cannot extract without OCR.\n")
        return

    if not chunks:
        print("[SKIP] No content chunks produced after conversion.\n")
        return

    # ── Step 2: Survey metadata ───────────────────────────────────────────────
    print("\n  [1/3] Extracting survey metadata ...")
    opening_text = "\n\n".join(
        chunk.text[:MAX_CHARS_PER_CHUNK_FOR_METADATA]
        for chunk in chunks[:MAX_CHUNKS_FOR_METADATA]
    )[:METADATA_CHAR_LIMIT]
    try:
        questionnaire = extract_survey_metadata(
            opening_text=opening_text,
            source_file=pdf_path.name,
            source_format="pdf",
        )
        study_type = questionnaire.study_type.value if questionnaire.study_type else "unknown"
        print(f"        Survey  : {questionnaire.survey_name}")
        print(f"        Country : {questionnaire.country_code}  |  Year: {questionnaire.year}")
        print(f"        Type    : {study_type}")
    except InstructorError as exc:
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
        except InstructorError as exc:
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
    print(f"\n  [3/3] Quality gate (threshold = {REVIEW_THRESHOLD:.2f}):")
    print(f"        Total variables extracted : {len(all_variables):3d}")
    print(f"        Flagged for human review  : {len(flagged_vars):3d}")
    if flagged_vars:
        names = ", ".join(v.raw_name for v in flagged_vars[:10])
        if len(flagged_vars) > 10:
            names += f" ... and {len(flagged_vars) - 10} more"
        print(f"        Flagged names             : {names}")

    # ── Step 5: Write output ──────────────────────────────────────────────────
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{questionnaire.survey_id}_svis.json"
    if output_file.exists():
        print(f"  [INFO] Existing output for {questionnaire.survey_id} found -- replacing it.")
        output_file.unlink()
    output_file.write_text(
        questionnaire.model_dump_json(indent=2),
        encoding="utf-8",
    )
    print(f"\n  [DONE] Output --> {output_file}")
    print(f"{'=' * 60}\n")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract structured variable information from a questionnaire PDF using Docling.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python pipeline_docling.py questionnaire.pdf\n"
            "  python pipeline_docling.py questionnaire.pdf --output-dir ./output\n"
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
