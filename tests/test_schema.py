"""
SVIS Schema Tests
==================
Run these before touching any questionnaire PDF.

    pytest tests/test_schema.py -v

These tests use the canonical working examples from the GMD project:
  - `male` (sex variable — canonical categorical example)
  - `age` (canonical numeric example)
  - `educy` / `educat4` (education examples, Situation A and B)

If all tests pass, the Pydantic schema is correctly installed
and the models work as expected.
"""

from datetime import date

import pytest
from pydantic import ValidationError

from survey_scribe.models.svis import (
    AnswerCategory,
    DataType,
    NumericRange,
    StudyType,
    SurveySVIS,
    SurveyVariable,
    UnitLevel,
)

# ── AnswerCategory ────────────────────────────────────────────────────────────


class TestAnswerCategory:
    def test_substantive_code(self):
        cat = AnswerCategory(code=1, label="Male")
        assert cat.is_missing is False

    def test_missing_code_dont_know(self):
        cat = AnswerCategory(code=98, label="Don't know", is_missing=True)
        assert cat.is_missing is True

    def test_missing_code_refused(self):
        cat = AnswerCategory(code=99, label="Refused", is_missing=True)
        assert cat.is_missing is True

    def test_string_code(self):
        """Some surveys use string codes, not integers."""
        cat = AnswerCategory(code="A", label="Agriculture")
        assert cat.code == "A"


# ── NumericRange ──────────────────────────────────────────────────────────────


class TestNumericRange:
    def test_age_range(self):
        rng = NumericRange(min_value=0, max_value=120)
        assert rng.min_value == 0
        assert rng.max_value == 120

    def test_years_of_education(self):
        rng = NumericRange(
            min_value=0,
            max_value=25,
            notes="Codes 98 and 99 in the data represent 'don't know' and 'refused'.",
        )
        assert rng.notes is not None

    def test_partial_range(self):
        """min_value or max_value can be null individually."""
        rng = NumericRange(min_value=0)
        assert rng.max_value is None


# ── SurveyVariable: canonical examples ───────────────────────────────────────


class TestSurveyVariableMale:
    """Canonical example: the GMD 'male' variable."""

    def setup_method(self):
        self.var = SurveyVariable(
            raw_name="q_sex",
            label="Sex of household member",
            question_text="What is the sex of [NAME]?",
            data_type=DataType.categorical_single,
            categories=[
                AnswerCategory(code=1, label="Male"),
                AnswerCategory(code=2, label="Female"),
                AnswerCategory(code=9, label="Not stated", is_missing=True),
            ],
            unit_of_analysis=UnitLevel.individual,
            module="Section 1: Household Roster",
            extraction_confidence=1.0,
        )

    def test_categories_count(self):
        assert self.var.categories is not None
        assert len(self.var.categories) == 3

    def test_missing_flag(self):
        assert self.var.categories is not None
        missing = [c for c in self.var.categories if c.is_missing]
        assert len(missing) == 1
        assert missing[0].code == 9

    def test_unit_of_analysis(self):
        assert self.var.unit_of_analysis == UnitLevel.individual

    def test_no_numeric_range(self):
        """Categorical variables should not have a numeric range."""
        assert self.var.numeric_range is None


class TestSurveyVariableAge:
    """Canonical example: the GMD 'age' variable (numeric, continuous)."""

    def setup_method(self):
        self.var = SurveyVariable(
            raw_name="q_age",
            label="Age of household member in completed years",
            question_text="How old is [NAME] in completed years?",
            data_type=DataType.numeric,
            numeric_range=NumericRange(
                min_value=0,
                max_value=120,
                notes="Codes 98 and 99 in the raw data mean 'don't know' "
                "and 'refused'. They appear as numeric values but should "
                "be treated as missing.",
            ),
            universe="All household members",
            unit_of_analysis=UnitLevel.individual,
            extraction_confidence=0.95,
        )

    def test_data_type(self):
        assert self.var.data_type == DataType.numeric

    def test_numeric_range_set(self):
        assert self.var.numeric_range is not None
        assert self.var.numeric_range.min_value == 0
        assert self.var.numeric_range.max_value == 120

    def test_range_notes(self):
        assert self.var.numeric_range is not None
        assert self.var.numeric_range.notes is not None
        assert "98" in self.var.numeric_range.notes

    def test_no_categories(self):
        """Numeric variables should not have a categories list."""
        assert self.var.categories is None


class TestSurveyVariableEducation:
    """
    Canonical example: education level (categorical_single).
    This is a Situation B mapping target — the survey has national
    education levels that need to be converted to GMD's educat4/5/7.
    """

    def setup_method(self):
        self.var = SurveyVariable(
            raw_name="q_educ",
            label="Highest level of education completed",
            question_text="What is the highest level of schooling [NAME] has completed?",
            data_type=DataType.categorical_single,
            categories=[
                AnswerCategory(code=0, label="No schooling"),
                AnswerCategory(code=1, label="Primary, incomplete"),
                AnswerCategory(code=2, label="Primary, complete"),
                AnswerCategory(code=3, label="Secondary, incomplete"),
                AnswerCategory(code=4, label="Secondary, complete"),
                AnswerCategory(code=5, label="Higher education, incomplete"),
                AnswerCategory(code=6, label="Higher education, complete"),
                AnswerCategory(code=98, label="Don't know", is_missing=True),
                AnswerCategory(code=99, label="Not stated", is_missing=True),
            ],
            universe="All household members aged 5 and above",
            skip_condition_raw="If q_age < 5, skip to next section.",
            unit_of_analysis=UnitLevel.individual,
            module="Section 4: Education",
            extraction_confidence=0.90,
            needs_review=False,
        )

    def test_substantive_categories(self):
        assert self.var.categories is not None
        substantive = [c for c in self.var.categories if not c.is_missing]
        assert len(substantive) == 7

    def test_missing_categories(self):
        assert self.var.categories is not None
        missing = [c for c in self.var.categories if c.is_missing]
        assert len(missing) == 2

    def test_universe_recorded(self):
        assert self.var.universe is not None
        assert "aged 5" in self.var.universe

    def test_skip_condition_preserved(self):
        assert self.var.skip_condition_raw is not None


# ── Confidence and review flag ────────────────────────────────────────────────


class TestConfidenceValidation:
    def test_confidence_upper_bound(self):
        with pytest.raises(ValidationError):
            SurveyVariable(
                raw_name="test",
                data_type=DataType.numeric,
                extraction_confidence=1.5,  # invalid: > 1.0
            )

    def test_confidence_lower_bound(self):
        with pytest.raises(ValidationError):
            SurveyVariable(
                raw_name="test",
                data_type=DataType.numeric,
                extraction_confidence=-0.1,  # invalid: < 0.0
            )

    def test_confidence_boundary_values(self):
        for val in [0.0, 0.5, 0.7, 1.0]:
            var = SurveyVariable(
                raw_name="test",
                data_type=DataType.numeric,
                extraction_confidence=val,
            )
            assert var.extraction_confidence == val


# ── SurveySVIS container ──────────────────────────────────────────────────────


class TestSurveySVIS:
    def setup_method(self):
        self.svis = SurveySVIS(
            survey_id="BGD_2022_HIES",
            country_code="BGD",
            year=2022,
            survey_name="Bangladesh Household Income and Expenditure Survey 2022",
            study_type=StudyType.lsms,
            data_collection_mode="CAPI",
            language="English",
            variables=[],
            source_file="BGD_2022_HIES_questionnaire.pdf",
            source_format="pdf",
            extraction_date=date(2024, 6, 1),
        )

    def test_survey_id(self):
        assert self.svis.survey_id == "BGD_2022_HIES"

    def test_json_serialization(self):
        json_str = self.svis.model_dump_json()
        assert "BGD_2022_HIES" in json_str
        assert "lsms" in json_str

    def test_json_round_trip(self):
        """Serialize to JSON and back — all fields survive."""
        json_str = self.svis.model_dump_json()
        recovered = SurveySVIS.model_validate_json(json_str)
        assert recovered.survey_id == self.svis.survey_id
        assert recovered.year == self.svis.year

    def test_variables_list_starts_empty(self):
        assert self.svis.variables == []

    def test_add_variable(self):
        var = SurveyVariable(
            raw_name="q_sex",
            data_type=DataType.categorical_single,
            extraction_confidence=1.0,
        )
        self.svis.variables.append(var)
        assert len(self.svis.variables) == 1
