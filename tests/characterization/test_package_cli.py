"""Verify package imports and CLI help are independent of provider extras."""

from __future__ import annotations

import sys

import pytest

from survey_scribe import SurveySVIS, __version__
from survey_scribe.cli import main


def test_import_does_not_load_provider_or_legacy_modules() -> None:
    assert SurveySVIS.__name__ == "SurveySVIS"
    assert "itsai" not in sys.modules
    assert "openai" not in sys.modules
    assert "docling" not in sys.modules


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
