# SVIS Field Guide

The Survey Variable Information Schema (SVIS) represents one survey instrument
and its variables. The schema preserves source wording, code lists, provenance,
confidence, and review decisions in a JSON-compatible form.

## Validation and policy

Pydantic enforces declared types, required fields, enum values, and the
`extraction_confidence` range. Some domain rules remain application policy in
`0.1.x`.

!!! warning "Policy is not automatic validation"

    The schema does not enforce ISO3 country codes, survey ID formats, unique
    variable names, category presence for categorical variables, or
    `min_value <= max_value`. It also does not derive `needs_review` from
    confidence. Enforce these rules in your quality workflow when required.

## Enumerations

### `DataType`

| Value | Use |
| --- | --- |
| `numeric` | A number used as a number, such as age or hours worked |
| `categorical_single` | One code selected from a code list |
| `categorical_multi` | Multiple codes can apply |
| `text` | Free-form text |
| `date` | A date or datetime value |
| `other` | A value outside the preceding groups |

### `StudyType`

Accepted values are `lsms`, `dhs`, `lfs`, `hhs`, `mics`, `cwiq`, `census`, and
`other`.

### `UnitLevel`

Accepted values are `individual`, `household`, and `other`. The default is
`individual`.

## `AnswerCategory`

| Field | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `code` | `int \| str` | Yes | - | Value stored in the raw data |
| `label` | `str` | Yes | - | Human-readable answer label |
| `is_missing` | `bool` | No | `False` | Non-substantive response such as refused or not stated |

Mark non-substantive values explicitly. Downstream code can then separate valid
categories from missing-value codes without label matching.

## `NumericRange`

| Field | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `min_value` | `float \| None` | No | `None` | Minimum valid substantive value |
| `max_value` | `float \| None` | No | `None` | Maximum valid substantive value |
| `notes` | `str \| None` | No | `None` | Units, exceptions, or range context |

The model accepts an open-ended range and does not compare the minimum with the
maximum. Validate range order before using it for data checks.

## `SurveyVariable`

| Field | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `raw_name` | `str` | Yes | - | Variable name in raw microdata |
| `label` | `str \| None` | No | `None` | Short variable label |
| `question_text` | `str \| None` | No | `None` | Questionnaire wording |
| `data_type` | `DataType` | Yes | - | Harmonization-oriented data type |
| `categories` | `list[AnswerCategory] \| None` | No | `None` | Ordered code list |
| `numeric_range` | `NumericRange \| None` | No | `None` | Valid numeric range |
| `universe` | `str \| None` | No | `None` | Population asked the question |
| `skip_condition_raw` | `str \| None` | No | `None` | Unmodified routing instruction |
| `module` | `str \| None` | No | `None` | Questionnaire section |
| `unit_of_analysis` | `UnitLevel` | No | `individual` | Entity described by the variable |
| `source_page` | `int \| None` | No | `None` | Zero-indexed page used by the package model |
| `extraction_confidence` | `float` | Yes | - | Confidence from `0.0` through `1.0` |
| `needs_review` | `bool` | No | `False` | Explicit human-review decision |
| `notes` | `str \| None` | No | `None` | Uncertainty or interpretation notes |

### Review policy example

```python
from survey_scribe import SurveyVariable


def requires_review(variable: SurveyVariable, threshold: float = 0.7) -> bool:
    """Apply an application review policy without changing the source record."""
    missing_categories = (
        variable.data_type.value.startswith("categorical")
        and not variable.categories
    )
    return (
        variable.needs_review
        or variable.extraction_confidence < threshold
        or variable.question_text is None
        or missing_categories
    )
```

Keep policy separate from the source record so that review criteria can change
without changing the serialized schema contract.

## `SurveySVIS`

| Field | Type | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `survey_id` | `str` | Yes | - | Stable survey identifier |
| `country_code` | `str` | Yes | - | Survey country code |
| `year` | `int` | Yes | - | Survey reference year |
| `survey_name` | `str` | Yes | - | Official survey name |
| `study_type` | `StudyType \| None` | No | `None` | Survey classification |
| `data_collection_mode` | `str \| None` | No | `None` | CAPI, paper, mixed, or another mode |
| `language` | `str \| None` | No | `None` | Primary questionnaire language |
| `variables` | `list[SurveyVariable]` | Yes | - | Variables in source order |
| `source_file` | `str` | Yes | - | Original source filename |
| `source_format` | `str` | Yes | - | Source format label |
| `extraction_date` | `datetime.date` | Yes | - | Extraction date |
| `extraction_notes` | `str \| None` | No | `None` | Document-level notes |

The conventional survey ID is `COUNTRYISO3_YEAR_ACRONYM`, for example
`BGD_2022_HIES`. The current model records this value but does not validate the
pattern.

## Pydantic operations

All SVIS models inherit the Pydantic 2 API:

```python
from survey_scribe import SurveySVIS

survey = SurveySVIS.model_validate(input_values)
json_text = survey.model_dump_json(indent=2)
json_values = survey.model_dump(mode="json")
schema = SurveySVIS.model_json_schema()
restored = SurveySVIS.model_validate_json(json_text)
```

JSON mode serializes enum members as strings and dates in ISO 8601 form.

## Mutability

SVIS models and their variable lists are mutable for legacy compatibility. If a
stable snapshot is required, serialize it or use
`ExtractionResult.serialization_snapshot()` before passing the record to other
code.
