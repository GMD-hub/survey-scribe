"""Tests for the documented top-level package API."""

from __future__ import annotations

from importlib.metadata import version

import survey_scribe
from survey_scribe import models


def test_public_api_exports_models_and_version() -> None:
    expected = {
        "AnswerCategory",
        "DataType",
        "NumericRange",
        "StudyType",
        "SurveySVIS",
        "SurveyVariable",
        "UnitLevel",
        "__version__",
    }

    assert set(survey_scribe.__all__) == expected
    assert set(models.__all__) == expected - {"__version__"}
    assert all(hasattr(survey_scribe, name) for name in expected)


def test_runtime_version_comes_from_distribution_metadata() -> None:
    assert survey_scribe.__version__ == version("survey-scribe")
