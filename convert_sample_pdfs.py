from pathlib import Path

from extractors.pdf import pdf_to_markdown


def main() -> None:
    repo_root = Path(__file__).resolve().parent
    samples_dir = repo_root / "tests" / "samples"

    for pdf in sorted(samples_dir.glob("*.pdf")):
        markdown = pdf_to_markdown(pdf)
        output_file = pdf.with_name(f"{pdf.stem}_converted.md")
        output_file.write_text(markdown, encoding="utf-8")
        print(f"Saved to {output_file}")


if __name__ == "__main__":
    main()
