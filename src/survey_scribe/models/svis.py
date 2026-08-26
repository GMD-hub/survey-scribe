"""Survey Variable Information Schema (SVIS) legacy-compatible models."""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field


class DataType(str, Enum):
    """Simplified data type used for harmonization."""

    numeric = "numeric"
    categorical_single = "categorical_single"
    categorical_multi = "categorical_multi"
    text = "text"
    date = "date"
    other = "other"


class StudyType(str, Enum):
    """Survey instrument classification."""

    lsms = "lsms"
    dhs = "dhs"
    lfs = "lfs"
    hhs = "hhs"
    mics = "mics"
    cwiq = "cwiq"
    census = "census"
    other = "other"


class UnitLevel(str, Enum):
    """Unit of analysis described by a variable."""

    individual = "individual"
    household = "household"
    other = "other"


class AnswerCategory(BaseModel):
    """One answer option for a categorical variable."""

    code: int | str = Field(description="Value stored in the raw microdata file.")
    label: str = Field(description="Human-readable answer label.")
    is_missing: bool = Field(
        default=False,
        description="Whether the code represents a non-substantive missing response.",
    )


class NumericRange(BaseModel):
    """Valid value range for a numeric variable."""

    min_value: float | None = Field(default=None, description="Minimum valid value.")
    max_value: float | None = Field(default=None, description="Maximum valid value.")
    notes: str | None = Field(default=None, description="Context about range interpretation.")


class SurveyVariable(BaseModel):
    """Structured description of one questionnaire variable."""

    raw_name: str = Field(description="Variable name used in raw microdata.")
    label: str | None = Field(default=None, description="Short human-readable variable label.")
    question_text: str | None = Field(
        default=None, description="Question text preserved from the questionnaire."
    )
    data_type: DataType = Field(description="Harmonization-oriented variable type.")
    categories: list[AnswerCategory] | None = Field(
        default=None, description="Complete answer options for categorical variables."
    )
    numeric_range: NumericRange | None = Field(
        default=None, description="Documented valid range for numeric variables."
    )
    universe: str | None = Field(default=None, description="Population asked the question.")
    skip_condition_raw: str | None = Field(
        default=None, description="Unmodified source routing or skip instruction."
    )
    module: str | None = Field(default=None, description="Questionnaire section or module.")
    unit_of_analysis: UnitLevel = Field(
        default=UnitLevel.individual,
        description="Entity described by the variable.",
    )
    source_page: int | None = Field(
        default=None, description="Zero-indexed source page for review provenance."
    )
    extraction_confidence: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "LLM self-assessed confidence in the accuracy of this extraction. "
            "Score the whole record, not individual fields. "
            "1.0 = all fields clear and unambiguous. "
            "0.9 = one minor uncertainty (e.g. label is slightly paraphrased). "
            "0.7 = notable uncertainty but overall reliable. "
            "Below 0.7 = significant doubt; set needs_review=True. "
            "0.0 = the LLM is guessing."
        ),
    )
    needs_review: bool = Field(default=False, description="Whether human review is required.")
    notes: str | None = Field(default=None, description="Extraction uncertainty or context.")


class SurveySVIS(BaseModel):
    """Complete SVIS for one survey instrument."""

    survey_id: str = Field(description="Stable COUNTRYISO3_YEAR_ACRONYM identifier.")
    country_code: str = Field(description="ISO3 survey country code.")
    year: int = Field(description="Survey reference year.")
    survey_name: str = Field(description="Official survey name.")
    study_type: StudyType | None = Field(default=None, description="Survey classification.")
    data_collection_mode: str | None = Field(
        default=None, description="Collection mode such as CAPI, paper, or mixed."
    )
    language: str | None = Field(default=None, description="Primary questionnaire language.")
    variables: list[SurveyVariable] = Field(
        description="Variables in stable source-document order."
    )
    source_file: str = Field(description="Original questionnaire filename.")
    source_format: str = Field(description="Source format such as pdf or xlsx.")
    extraction_date: date = Field(description="Date on which extraction ran.")
    extraction_notes: str | None = Field(
        default=None, description="Document-level extraction diagnostics."
    )
