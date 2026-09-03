"""Unit tests for the dependency-free command-line surface."""

from __future__ import annotations

import pytest

from survey_scribe.cli import build_parser, main
from survey_scribe.models.routing import canonical_routing_schema_json


def test_parser_has_stable_program_name_and_description() -> None:
    parser = build_parser()

    assert parser.prog == "survey-scribe"
    assert parser.description == "Inspect Survey Scribe and export public JSON schemas."


def test_no_arguments_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    main([])

    output = capsys.readouterr().out
    assert output.startswith("usage: survey-scribe")
    assert "--version" in output


def test_unknown_argument_exits_with_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit, match="2"):
        main(["--unknown"])

    captured = capsys.readouterr()
    assert "unrecognized arguments: --unknown" in captured.err


def test_incomplete_schema_command_exits_with_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit, match="2"):
        main(["schema"])

    captured = capsys.readouterr()
    assert "the following arguments are required: schema_command" in captured.err


def test_schema_export_routing_writes_the_exact_canonical_schema(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["schema", "export", "routing"])

    captured = capsys.readouterr()
    assert captured.out == canonical_routing_schema_json()
    assert captured.err == ""
