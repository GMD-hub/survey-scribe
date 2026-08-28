"""Focused validation and serialization tests for the public SVIS models."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from survey_scribe import DataType, StudyType, SurveySVIS, SurveyVariable, UnitLevel


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("data_type", "spreadsheet"),
        ("unit_of_analysis", "organization"),
    ],
)
def test_variable_rejects_unknown_enum_values(field: str, value: str) -> None:
    values: dict[str, object] = {
        "raw_name": "q1",
        "data_type": DataType.text,
        "extraction_confidence": 1.0,
        field: value,
    }

    with pytest.raises(ValidationError) as error:
        SurveyVariable.model_validate(values)

    assert error.value.errors()[0]["type"] == "enum"


@pytest.mark.parametrize("missing", ["raw_name", "data_type", "extraction_confidence"])
def test_variable_rejects_missing_required_fields(missing: str) -> None:
    values: dict[str, object] = {
        "raw_name": "q1",
        "data_type": DataType.text,
        "extraction_confidence": 1.0,
    }
    del values[missing]

    with pytest.raises(ValidationError) as error:
        SurveyVariable.model_validate(values)

    assert error.value.errors()[0]["loc"] == (missing,)
    assert error.value.errors()[0]["type"] == "missing"


def test_survey_rejects_invalid_date_and_study_type() -> None:
    values = {
        "survey_id": "TST_2024_SYNTH",
        "country_code": "TST",
        "year": 2024,
        "survey_name": "Synthetic Survey",
        "study_type": "panel",
        "variables": [],
        "source_file": "questionnaire.pdf",
        "source_format": "pdf",
        "extraction_date": "not-a-date",
    }

    with pytest.raises(ValidationError) as error:
        SurveySVIS.model_validate(values)

    locations = {item["loc"] for item in error.value.errors()}
    assert locations == {("study_type",), ("extraction_date",)}


def test_json_mode_serializes_enums_and_dates() -> None:
    variable = SurveyVariable(
        raw_name="q1",
        data_type=DataType.text,
        unit_of_analysis=UnitLevel.household,
        extraction_confidence=1.0,
    )
    survey = SurveySVIS(
        survey_id="TST_2024_SYNTH",
        country_code="TST",
        year=2024,
        survey_name="Synthetic Survey",
        study_type=StudyType.other,
        variables=[variable],
        source_file="questionnaire.pdf",
        source_format="pdf",
        extraction_date=date(2024, 6, 1),
    )

    serialized = survey.model_dump(mode="json")

    assert serialized["study_type"] == "other"
    assert serialized["extraction_date"] == "2024-06-01"
    assert serialized["variables"][0]["data_type"] == "text"
    assert serialized["variables"][0]["unit_of_analysis"] == "household"
