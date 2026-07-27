"""
Text Structure Pipeline
==========================
Entry point for the recognition sub-project's text extraction stage.

Usage:
    python recognition/pipeline.py path/to/questionnaire.pdf
    python recognition/pipeline.py path/to/questionnaire.pdf --output-dir recognition/output

Run this file directly (not with -m from the repo root) -- see the
"Important: import isolation" section in recognition/README.md for why.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Puts this file's own directory (recognition/) at the front of sys.path
# so its local schemas/agents/extractors packages resolve first, rather
# than colliding with the repo root's identically-named packages.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agents.language_agent import compute_primary_language, tag_languages  # noqa: E402
from agents.image_agent import extract_images  # noqa: E402
from agents.table_agent import extract_tables  # noqa: E402
from agents.text_agent import build_text_structure  # noqa: E402
from extractors.docling_convert import DEFAULT_MAX_CHARS, convert_pdf  # noqa: E402
from schemas.document_metadata import DocumentMetadata  # noqa: E402


def run(pdf_path: Path, output_dir: Path, max_chars: int | None = DEFAULT_MAX_CHARS) -> None:
    print(f"\n{'=' * 60}")
    print(f"  [recognition] Text structure: {pdf_path.name}")
    print(f"{'=' * 60}")

    if max_chars is None:
        print("  [1/5] Converting PDF with Docling (full document) ...")
    else:
        print(f"  [1/5] Converting PDF with Docling (capped at {max_chars} chars) ...")
    doc = convert_pdf(pdf_path, max_chars=max_chars)
    print(f"        {len(doc.pages)} page(s) parsed.")

    print("  [2/5] Building text structure ...")
    structure = build_text_structure(doc, source_file=pdf_path.name)
    print(f"        {len(structure.blocks)} text block(s) extracted.")

    print("  [3/5] Detecting language of each block ...")
    tag_languages(structure.blocks)
    tagged = sum(1 for b in structure.blocks if b.language)
    print(f"        {tagged}/{len(structure.blocks)} block(s) tagged with a language.")

    primary = compute_primary_language(structure.blocks)
    if primary is not None:
        language, share = primary
        structure.primary_language = language
        print(f"        Main language: {language} ({share:.0%} of tagged text by character count)")
    else:
        print("        Main language: unknown -- no blocks were confidently tagged.")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{pdf_path.stem}_text_structure.json"
    output_file.write_text(structure.model_dump_json(indent=2), encoding="utf-8")
    print(f"\n  [DONE] Output -> {output_file}")

    print("  [4/5] Extracting images ...")
    image_structure = extract_images(doc, source_file=pdf_path.name, output_dir=output_dir)
    saved = sum(1 for img in image_structure.images if img.file_path)
    print(f"        {saved}/{len(image_structure.images)} image(s) saved.")
    image_output_file = output_dir / f"{pdf_path.stem}_image_structure.json"
    image_output_file.write_text(image_structure.model_dump_json(indent=2), encoding="utf-8")
    print(f"  [DONE] Output -> {image_output_file}")

    print("  [5/5] Extracting tables ...")
    table_structure = extract_tables(doc, source_file=pdf_path.name)
    total_cells = sum(t.num_rows * t.num_cols for t in table_structure.tables)
    print(f"        {len(table_structure.tables)} table(s) extracted ({total_cells} cell(s) total).")
    table_output_file = output_dir / f"{pdf_path.stem}_table_structure.json"
    table_output_file.write_text(table_structure.model_dump_json(indent=2), encoding="utf-8")
    print(f"  [DONE] Output -> {table_output_file}")

    metadata = DocumentMetadata(
        source_file=pdf_path.name,
        page_count=len(doc.pages),
        extraction_date=structure.extraction_date,
        primary_language=structure.primary_language,
        text=structure,
        images=image_structure,
        tables=table_structure,
    )
    metadata_file = output_dir / f"{pdf_path.stem}_metadata.json"
    metadata_file.write_text(metadata.model_dump_json(indent=2), encoding="utf-8")
    print(f"  [DONE] Combined output -> {metadata_file}")

    # The three per-agent files above are only intermediate artifacts --
    # everything they contain is now nested inside metadata_file. Remove
    # them once the combined file has been written successfully so
    # output_dir doesn't accumulate duplicate copies of the same data.
    for intermediate_file in (output_file, image_output_file, table_output_file):
        intermediate_file.unlink(missing_ok=True)
    print("  [CLEANUP] Removed intermediate per-agent JSON files.")
    print(f"{'=' * 60}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract page- and heading-aware text structure from a PDF.",
    )
    parser.add_argument("pdf", type=Path, help="Path to the PDF.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "output",
        help="Directory for output JSON. Default: recognition/output",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=DEFAULT_MAX_CHARS,
        help=(
            "Stop converting once this many characters of text have been "
            f"extracted (default: {DEFAULT_MAX_CHARS}). Ignored if --full is set."
        ),
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Convert the entire PDF, ignoring --max-chars.",
    )
    args = parser.parse_args()

    if not args.pdf.exists():
        print(f"Error: file not found: {args.pdf}")
        raise SystemExit(1)

    if args.pdf.suffix.lower() != ".pdf":
        print(f"Error: expected a .pdf file, got: {args.pdf.suffix}")
        raise SystemExit(1)

    max_chars = None if args.full else args.max_chars
    run(args.pdf, args.output_dir, max_chars=max_chars)


if __name__ == "__main__":
    main()
