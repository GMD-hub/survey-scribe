# Usage

## Define a Variable

Every variable requires a raw name, data type, and extraction confidence.

```python
from survey_scribe import DataType, NumericRange, SurveyVariable, UnitLevel

age = SurveyVariable(
    raw_name="q_age",
    label="Age in completed years",
    question_text="How old is [NAME] in completed years?",
    data_type=DataType.numeric,
    numeric_range=NumericRange(min_value=0, max_value=120),
    universe="All household members",
    unit_of_analysis=UnitLevel.individual,
    extraction_confidence=0.98,
)
```

Pydantic rejects confidence values outside the inclusive range from `0.0` to
`1.0` and rejects unknown enum values.

## Define Categories

Use `is_missing=True` for non-substantive responses that downstream systems
must treat as missing.

```python
from survey_scribe import AnswerCategory, DataType, SurveyVariable

consent = SurveyVariable(
    raw_name="q_consent",
    data_type=DataType.categorical_single,
    categories=[
        AnswerCategory(code=1, label="Yes"),
        AnswerCategory(code=2, label="No"),
        AnswerCategory(code=99, label="Refused", is_missing=True),
    ],
    extraction_confidence=1.0,
)
```

## Build a Survey Record

```python
from datetime import date

from survey_scribe import StudyType, SurveySVIS

survey = SurveySVIS(
    survey_id="BGD_2022_HIES",
    country_code="BGD",
    year=2022,
    survey_name="Bangladesh Household Income and Expenditure Survey 2022",
    study_type=StudyType.lsms,
    language="English",
    variables=[age, consent],
    source_file="BGD_2022_HIES_questionnaire.pdf",
    source_format="pdf",
    extraction_date=date.today(),
)
```

## Serialize and Validate

```python
payload = survey.model_dump_json(indent=2)
validated = SurveySVIS.model_validate_json(payload)

assert validated == survey
```

For plain JSON-compatible objects instead of a string, use
`survey.model_dump(mode="json")`.

## Review Metadata

`extraction_confidence` records the extractor's whole-record confidence.
`needs_review` is stored separately and is not derived automatically in the
legacy-compatible `0.1.x` schema. Set it explicitly when policy requires human
review.

```python
uncertain = SurveyVariable(
    raw_name="q_other",
    data_type=DataType.other,
    extraction_confidence=0.45,
    needs_review=True,
    notes="The answer table was partially illegible.",
)
```

See [Compatibility](compatibility.md) before changing defaults, field order, or
serialized values.
