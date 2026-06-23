"""
Survey Variable Information Schema (SVIS)
==========================================
Pydantic models defining the structured output of the questionnaire
extraction pipeline.

This schema is the central contract between:
  1. The extraction agents  (which fill it in)
  2. The LLM harmonization stage  (which reads it to propose GMD mappings)
  3. The historical precedents database  (which stores it for future retrieval)

Design principle: every field earns its place.
This schema is not a general-purpose questionnaire standard.
It captures exactly what is needed for GMD variable harmonization —
no more, no less.

Key reference: the Survey Solutions QuestionnaireSchema.json was used
as a checklist when designing this schema. Fields present in SS but
absent here were deliberately excluded because they describe interviewer
UI behavior rather than what a variable measures.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ── Enumerations ──────────────────────────────────────────────────────────────

class DataType(str, Enum):
    """
    Simplified data type for harmonization purposes.
    Collapses all questionnaire question types into six categories
    that are meaningful for GMD variable mapping.

    Note: The Survey Solutions schema has 11 question types. We reduce
    them here because the display format (radio button vs dropdown) is
    irrelevant to what a variable means. What matters is whether it is
    a number, a code from a list, free text, or a date.
    """
    numeric            = "numeric"
    # A number used as a number.
    # Examples: age in years, household size, years of education (educy),
    # income in local currency, land area in hectares.

    categorical_single = "categorical_single"
    # Respondent chooses exactly one option from a predefined list.
    # Examples: sex, urban/rural, marital status, employment status,
    # education level, relation to household head.
    # The most common type for GMD demographic variables.

    categorical_multi  = "categorical_multi"
    # Respondent can select multiple options simultaneously.
    # Examples: sources of income, assets owned, activities in past week.

    text               = "text"
    # Free-form string response.
    # Examples: household member name, open-ended answer.
    # Rarely maps directly to a GMD target variable.

    date               = "date"
    # A date or datetime value.
    # Example: date of birth — can be used to derive age (Situation B mapping).

    other              = "other"
    # GPS coordinates, audio recordings, photographs, QR barcodes.
    # Not relevant to the current PoC scope.


class StudyType(str, Enum):
    """
    Survey instrument type classification.
    Used to retrieve relevant historical harmonization precedents —
    an LSMS precedent is more likely to be useful than a DHS one
    when processing another LSMS.
    """
    lsms   = "lsms"    # Living Standards Measurement Study
    dhs    = "dhs"     # Demographic and Health Survey
    lfs    = "lfs"     # Labour Force Survey
    hhs    = "hhs"     # Household Health Survey
    mics   = "mics"    # Multiple Indicator Cluster Survey
    cwiq   = "cwiq"    # Core Welfare Indicators Questionnaire
    census = "census"  # Population and housing census
    other  = "other"


class UnitLevel(str, Enum):
    """
    The unit of analysis — who or what the variable describes.

    This is one of the most important fields for GMD, which stores
    variables at multiple levels in the same flat file. Variables
    at the wrong level cause silent errors in poverty calculations.

    In the Survey Solutions schema this is implicit — you infer it by
    checking whether a question is nested inside a person-level Roster.
    In the SVIS it is explicit because the LLM must produce it directly.
    """
    individual = "individual"  # Describes a person (age, sex, education, labor)
    household  = "household"   # Describes the household unit (dwelling, assets)
    other      = "other"       # Plot, enterprise, livestock holding, etc.


# ── Building blocks ───────────────────────────────────────────────────────────

class AnswerCategory(BaseModel):
    """
    One answer option for a categorical variable.

    Captures both the numeric code stored in the microdata file and
    the human-readable label from the questionnaire.

    The is_missing flag is critical: codes meaning "don't know",
    "refused", or "not applicable" must be recoded to missing (.)
    in the GMD harmonized file rather than treated as substantive values.
    Flagging them here, at extraction time, prevents errors downstream.
    """
    code: int | str
    # The value stored in the raw microdata file.
    # Usually an integer (e.g. 1 = Male, 2 = Female) but occasionally
    # a string code (e.g. "A", "B").

    label: str
    # The label shown to the respondent or printed in the codebook.
    # Examples: "Primary education complete", "Wage employee"

    is_missing: bool = False
    # True if this code represents a non-substantive response that
    # must be recoded to missing (.) in GMD.
    # Mark True for: "Don't know", "Refused", "Not applicable",
    # "Not stated", "No information", or any equivalent phrasing.
    # Mark False for all substantive answer options.


class NumericRange(BaseModel):
    """
    Valid value range for a numeric variable.

    Extracted from validation expressions, question instructions,
    or interviewer notes in the questionnaire.

    Why this matters: detecting the valid range helps identify coded
    missing values hiding as numbers (e.g. age = 99 meaning "unknown").
    A value of 99 inside a range of 0-120 is plausible; a value of 99
    in a variable whose stated maximum is 90 is almost certainly a
    missing-value code — and should have been in AnswerCategory with
    is_missing=True.
    """
    min_value: Optional[float] = None
    # Minimum valid substantive value.
    # Examples: 0 for age, 1 for household size, 0 for years of education.

    max_value: Optional[float] = None
    # Maximum valid substantive value.
    # Examples: 120 for age, 25 for years of education.

    notes: Optional[str] = None
    # Additional context about the range.
    # Example: "Values 98 and 99 appear in the data but represent
    # 'don't know' and 'refused' — they are listed in categories
    # with is_missing=True."


# ── Core variable record ──────────────────────────────────────────────────────

class SurveyVariable(BaseModel):
    """
    Complete structured description of one variable in a survey questionnaire.

    This is the central unit of the SVIS. One SurveyVariable record is
    produced for each extractable question. The entire point of the
    questionnaire extraction pipeline is to fill in these records accurately.

    Downstream, the harmonization AI reads these records and proposes
    mappings to GMD target variables. The quality of those mappings
    depends directly on the completeness and accuracy of these fields.
    """

    # ── Identity ─────────────────────────────────────────────────────────────

    raw_name: str
    # The variable name as it will appear in the raw microdata file.
    # Examples: "q14", "hh_educ", "s2b_q4", "B3a".
    #
    # If no code is printed in the questionnaire, construct a short
    # descriptive snake_case name from the question content.
    # Examples: "highest_educ_level", "age_completed_years", "urban_rural".

    label: Optional[str] = None
    # A short, human-readable description of what the variable measures.
    # Maximum 80 characters (the Stata variable label limit).
    # Example: "Highest level of education completed"

    question_text: Optional[str] = None
    # The full question text exactly as written in the questionnaire.
    # Preserve any placeholders like [NAME] or [ROSTER].
    # Example: "What is the highest level of schooling [NAME] has completed?"

    # ── Type ──────────────────────────────────────────────────────────────────

    data_type: DataType

    # ── Content ───────────────────────────────────────────────────────────────

    categories: Optional[list[AnswerCategory]] = None
    # For categorical_single and categorical_multi variables only.
    # List EVERY answer option exactly as printed in the questionnaire —
    # do not omit any, including missing-value codes.
    # Omitting categories is the most common and most damaging extraction error.

    numeric_range: Optional[NumericRange] = None
    # For numeric variables only.
    # Capture the valid range from validation expressions or instructions.
    # Leave null if no range information is available in the questionnaire.

    # ── Universe ──────────────────────────────────────────────────────────────

    universe: Optional[str] = None
    # Plain-language description of who is asked this question.
    # This tells the harmonization AI which household members have a
    # valid value for this variable and which should be set to missing.
    #
    # Examples:
    #   "All household members"
    #   "All household members aged 5 and above"
    #   "Household head only"
    #   "Women aged 15 to 49"
    #   "Employed persons only"

    skip_condition_raw: Optional[str] = None
    # The raw skip or routing instruction as written in the questionnaire.
    # Preserved exactly — do not interpret or simplify.
    # This is kept for reference and audit; the plain-language universe
    # field above is what the harmonization AI actually uses.
    # Example: "If Q3 = 00 (never attended school), skip to Q20."

    # ── Context ───────────────────────────────────────────────────────────────

    module: Optional[str] = None
    # The section or module this variable belongs to.
    # Provides semantic context for the harmonization AI — an 'educ'
    # variable inside an Education module is different from an 'educ'
    # variable inside a Job History module.
    # Examples: "Section 4: Education", "Labour Module", "Household Roster"

    unit_of_analysis: UnitLevel = UnitLevel.individual
    # Whether this variable describes a person or a household.
    # Infer from context:
    #   - Questions inside a person-by-person roster → individual
    #   - Questions about the dwelling, shared assets, total income → household
    # When in doubt, flag for review and note your reasoning.

    # ── Extraction provenance ─────────────────────────────────────────────────

    source_page: Optional[int] = None
    # PDF page number where this variable was found (zero-indexed).
    # Used for human review — reviewer can go directly to the source page.

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
        )
    )

    needs_review: bool = False
    # True if this variable should be checked by a human reviewer.
    # Set True automatically when:
    #   - extraction_confidence < 0.7
    #   - question_text is null
    #   - data_type could not be determined reliably
    #   - categories is null for a variable that appears categorical
    #
    # The human reviewer can correct the record and set this back to False.

    notes: Optional[str] = None
    # Free text for the LLM to record extraction uncertainties, ambiguities,
    # or observations that do not fit other fields.
    # Examples:
    #   "Answer codes were in a table that did not extract cleanly.
    #    Codes 1-5 recovered; code 6 may be missing."
    #   "Question appears twice with different wording — used the version
    #    on page 14."
    #   "Universe not explicitly stated; inferred from section heading."


# ── Survey-level container ────────────────────────────────────────────────────

class SurveySVIS(BaseModel):
    """
    Complete SVIS for one survey instrument.
    One SurveySVIS file is produced per questionnaire processed.
    Serialized to JSON and stored in the output/ directory.
    """

    # ── Survey identity ───────────────────────────────────────────────────────

    survey_id: str
    # Unique identifier for this survey.
    # Convention: COUNTRYISO3_YEAR_ACRONYM
    # Examples: "BGD_2022_HIES", "ETH_2021_ESS", "COL_2020_GEIH"

    country_code: str
    # ISO3 alpha country code (3 uppercase letters).
    # Examples: BGD, ETH, COL, KEN, VNM, NGA

    year: int
    # Survey reference year. Four-digit integer.

    survey_name: str
    # Full official name of the survey.
    # Example: "Bangladesh Household Income and Expenditure Survey 2022"

    study_type: Optional[StudyType] = None

    data_collection_mode: Optional[str] = None
    # How data was collected.
    # Examples: "CAPI", "paper", "CATI", "mixed", "unknown"

    language: Optional[str] = None
    # Primary language of the questionnaire.
    # Examples: "English", "French", "Spanish", "Arabic"

    # ── Variables ─────────────────────────────────────────────────────────────

    variables: list[SurveyVariable]
    # All variables extracted from this questionnaire,
    # ordered by appearance in the document.

    # ── Provenance ────────────────────────────────────────────────────────────

    source_file: str
    # Original filename of the questionnaire document.
    # Example: "BGD_2022_HIES_questionnaire_v2.pdf"

    source_format: str
    # Format of the source file.
    # Examples: "pdf", "xlsx", "ss_json"

    extraction_date: date
    # Date this extraction was run. Set automatically by the pipeline.

    extraction_notes: Optional[str] = None
    # Pipeline-level notes about the extraction run.
    # Example: "Pages 12-14 were image-only and skipped.
    #           Chunking fell back to page-based (no headings detected)."
