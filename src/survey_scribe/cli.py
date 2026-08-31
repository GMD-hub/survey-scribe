"""Command-line bootstrap for Survey Scribe."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from survey_scribe import __version__


def build_parser() -> argparse.ArgumentParser:
    """Build the package command parser without loading optional providers.

    Returns:
        Parser that supports standard help output and ``--version``.
    """
    parser = argparse.ArgumentParser(
        prog="survey-scribe",
        description="Extract questionnaire metadata into the SVIS format.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Run the package bootstrap command.

    Args:
        argv: Arguments without the executable name. Process arguments are used
            when omitted.

    Raises:
        SystemExit: Help and version exit with status 0; invalid arguments exit
            with status 2.
    """
    parser = build_parser()
    parser.parse_args(argv)
    parser.print_help()
