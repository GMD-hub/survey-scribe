"""Verify package imports and CLI help are independent of provider extras."""

from __future__ import annotations

import subprocess
import sys

import pytest

from survey_scribe import __version__
from survey_scribe.cli import main


def test_import_does_not_load_provider_or_legacy_modules(repository_root) -> None:
    script = """
import sys
from survey_scribe import SurveySVIS
assert SurveySVIS.__name__ == 'SurveySVIS'
assert {'itsai', 'openai', 'instructor', 'anthropic', 'docling'}.isdisjoint(sys.modules)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_help_is_available_without_provider_extras(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit, match="0"):
        main(["--help"])
    output = capsys.readouterr().out
    assert "survey-scribe" in output


def test_version_is_available_without_provider_extras(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit, match="0"):
        main(["--version"])
    assert __version__ in capsys.readouterr().out
