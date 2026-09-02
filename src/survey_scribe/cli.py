"""Dependency-light command line for Survey Scribe."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from survey_scribe import __version__


def _export_routing_schema() -> None:
    from survey_scribe.models.routing import canonical_routing_schema_json

    sys.stdout.write(canonical_routing_schema_json())


def build_parser() -> argparse.ArgumentParser:
    """Build the package command parser without loading optional providers.

    Returns:
        Parser for help, version, and canonical routing-schema export.
    """
    parser = argparse.ArgumentParser(
        prog="survey-scribe",
        description="Inspect Survey Scribe and export public JSON schemas.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command")
    schema = commands.add_parser("schema", help="Work with public JSON schemas.")
    schema_commands = schema.add_subparsers(dest="schema_command", required=True)
    export = schema_commands.add_parser("export", help="Export a public JSON schema.")
    export.add_argument("schema_name", choices=("routing",))
    export.set_defaults(exporter=_export_routing_schema)
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
    args = parser.parse_args(argv)
    if args.command == "schema":
        args.exporter()
        return
    parser.print_help()
