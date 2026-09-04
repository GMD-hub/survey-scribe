"""Deprecated root compatibility shim for the packaged Survey Scribe API."""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

_WARNED = False


def _warn_deprecated() -> None:
    global _WARNED
    if _WARNED:
        return
    warnings.warn(
        "docling_pipeline.py is deprecated; use survey_scribe.SurveyScribe instead",
        DeprecationWarning,
        stacklevel=2,
    )
    _WARNED = True


def run(pdf_path: Path, output_dir: Path) -> None:
    """Convert one PDF and write its legacy-named SVIS projection."""
    _run(pdf_path, output_dir, config_path=None)


def _run(pdf_path: Path, output_dir: Path, *, config_path: Path | None) -> None:
    _warn_deprecated()
    from survey_scribe import ConversionFailedError, ResultStatus, SurveyScribe

    with SurveyScribe.from_config(config_path, resolve_environment=True) as client:
        result = client.convert(pdf_path)
        if result.output is None:
            code = result.diagnostics[0].code if result.diagnostics else "CONVERSION_FAILED"
            raise ConversionFailedError(f"Legacy conversion failed ({code})")
        result.write(
            output_dir,
            sidecar=result.status is ResultStatus.partial,
            overwrite=True,
        )


def build_parser() -> argparse.ArgumentParser:
    """Build the preserved root command shape without loading runtime adapters."""
    parser = argparse.ArgumentParser(
        description="Extract structured variable information from a questionnaire PDF using Docling.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python docling_pipeline.py questionnaire.pdf\n"
            "  python docling_pipeline.py questionnaire.pdf --output-dir ./output\n"
        ),
    )
    parser.add_argument("pdf", type=Path, help="Path to the questionnaire PDF.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="Directory for SVIS JSON output. Created if it does not exist. Default: ./output",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Exact Survey Scribe TOML configuration path.",
    )
    return parser


def main() -> None:
    """Run the deprecated root CLI with explicit local validation."""
    args = build_parser().parse_args()
    if not args.pdf.exists():
        sys.stderr.write(f"Error: file not found: {args.pdf}\n")
        raise SystemExit(1)
    if args.pdf.suffix.lower() != ".pdf":
        sys.stderr.write(f"Error: expected a .pdf file, got: {args.pdf.suffix}\n")
        raise SystemExit(1)
    try:
        _run(args.pdf, args.output_dir, config_path=args.config)
    except Exception as error:
        sys.stderr.write(f"Error: {error}\n")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
