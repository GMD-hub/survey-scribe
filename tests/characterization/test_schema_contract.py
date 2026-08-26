"""Characterize the exact legacy SVIS serialization contract."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import tomli

from schemas import svis as legacy_svis
from survey_scribe.models.svis import (
    AnswerCategory,
    DataType,
    NumericRange,
    StudyType,
    SurveySVIS,
    SurveyVariable,
    UnitLevel,
)


def _contract_model() -> SurveySVIS:
    return SurveySVIS(
        survey_id="TST_2024_SYNTH",
        country_code="TST",
        year=2024,
        survey_name="Synthetic Questionnaire 2024",
        study_type=StudyType.other,
        data_collection_mode=None,
        language="English",
        variables=[
            SurveyVariable(
                raw_name="q_age",
                label="Age in completed years",
                question_text="How old is [NAME]?",
                data_type=DataType.numeric,
                categories=None,
                numeric_range=NumericRange(min_value=0, max_value=120),
                universe="All household members",
                skip_condition_raw=None,
                module="Roster",
                unit_of_analysis=UnitLevel.individual,
                source_page=0,
                extraction_confidence=1.0,
                needs_review=False,
                notes=None,
            )
        ],
        source_file="synthetic-questionnaire.pdf",
        source_format="pdf",
        extraction_date=date(2024, 6, 1),
        extraction_notes=None,
    )


def test_exact_fixed_clock_serialization(repository_root: Path) -> None:
    expected = json.loads(
        (repository_root / "tests/fixtures/legacy/schema-contract-v1.json").read_text(
            encoding="utf-8"
        )
    )
    actual = json.loads(_contract_model().model_dump_json())
    assert actual == expected
    assert list(actual) == list(expected)
    assert list(actual["variables"][0]) == list(expected["variables"][0])
    assert list(actual["variables"][0]["numeric_range"]) == list(
        expected["variables"][0]["numeric_range"]
    )


def test_round_trip_preserves_complete_model() -> None:
    expected = _contract_model()
    assert SurveySVIS.model_validate_json(expected.model_dump_json()) == expected


def test_legacy_import_reexports_packaged_models() -> None:
    assert legacy_svis.SurveySVIS is SurveySVIS
    assert legacy_svis.SurveyVariable is SurveyVariable


def test_current_quality_rules_are_not_automatic() -> None:
    low_confidence = SurveyVariable(
        raw_name="q_low",
        data_type=DataType.categorical_single,
        categories=None,
        extraction_confidence=0.69,
    )
    boundary = SurveyVariable(
        raw_name="q_boundary",
        data_type=DataType.numeric,
        numeric_range=NumericRange(min_value=10, max_value=1),
        extraction_confidence=0.70,
    )
    assert low_confidence.needs_review is False
    assert boundary.needs_review is False
    assert boundary.numeric_range == NumericRange(min_value=10, max_value=1)


def test_all_legacy_enum_values_and_field_orders_are_frozen() -> None:
    assert [value.value for value in DataType] == [
        "numeric",
        "categorical_single",
        "categorical_multi",
        "text",
        "date",
        "other",
    ]
    assert [value.value for value in StudyType] == [
        "lsms",
        "dhs",
        "lfs",
        "hhs",
        "mics",
        "cwiq",
        "census",
        "other",
    ]
    assert [value.value for value in UnitLevel] == ["individual", "household", "other"]
    assert list(AnswerCategory.model_fields) == ["code", "label", "is_missing"]
    assert list(NumericRange.model_fields) == ["min_value", "max_value", "notes"]
    assert list(SurveyVariable.model_fields) == [
        "raw_name",
        "label",
        "question_text",
        "data_type",
        "categories",
        "numeric_range",
        "universe",
        "skip_condition_raw",
        "module",
        "unit_of_analysis",
        "source_page",
        "extraction_confidence",
        "needs_review",
        "notes",
    ]


def test_category_union_types_and_defaults_are_frozen() -> None:
    integer = AnswerCategory(code=1, label="Yes")
    string = AnswerCategory(code="A", label="Agriculture")
    assert integer.model_dump() == {"code": 1, "label": "Yes", "is_missing": False}
    assert string.model_dump() == {"code": "A", "label": "Agriculture", "is_missing": False}
    assert SurveyVariable(
        raw_name="q1", data_type=DataType.text, extraction_confidence=1.0
    ).model_dump() == {
        "raw_name": "q1",
        "label": None,
        "question_text": None,
        "data_type": DataType.text,
        "categories": None,
        "numeric_range": None,
        "universe": None,
        "skip_condition_raw": None,
        "module": None,
        "unit_of_analysis": UnitLevel.individual,
        "source_page": None,
        "extraction_confidence": 1.0,
        "needs_review": False,
        "notes": None,
    }


def test_intentional_corrections_have_bounded_executable_metadata(
    repository_root: Path,
) -> None:
    with (repository_root / "tests/fixtures/legacy/intentional-corrections.toml").open(
        "rb"
    ) as stream:
        corrections = tomli.load(stream)["corrections"]
    assert [correction["id"] for correction in corrections] == [
        "deterministic-needs-review",
        "real-page-provenance",
        "process-scanned-input",
        "explicit-partial-diagnostics",
    ]
    for correction in corrections:
        assert correction["affected_paths"]
        assert correction["baseline_behavior"]
        assert correction["corrected_behavior"]
        assert correction["rationale"]
        assert correction["approval_reference"]
