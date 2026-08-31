# Quickstart

This guide creates a typed SVIS record, serializes it, validates it again, and
writes a versioned artifact set.

## 1. Define variables

```python
from survey_scribe import (
    AnswerCategory,
    DataType,
    NumericRange,
    SurveyVariable,
    UnitLevel,
)

age = SurveyVariable(
    raw_name="q_age",
    label="Age in completed years",
    question_text="How old is [NAME] in completed years?",
    data_type=DataType.numeric,
    numeric_range=NumericRange(min_value=0, max_value=120),
    universe="All household members",
    unit_of_analysis=UnitLevel.individual,
    source_page=7,
    extraction_confidence=0.98,
)

sex = SurveyVariable(
    raw_name="q_sex",
    label="Sex of household member",
    question_text="What is the sex of [NAME]?",
    data_type=DataType.categorical_single,
    categories=[
        AnswerCategory(code=1, label="Male"),
        AnswerCategory(code=2, label="Female"),
        AnswerCategory(code=9, label="Not stated", is_missing=True),
    ],
    extraction_confidence=1.0,
)
```

`extraction_confidence` must be from `0.0` through `1.0`. The schema does not
automatically set `needs_review`; set it explicitly when your review policy
requires it.

## 2. Build a survey record

```python
from datetime import date

from survey_scribe import StudyType, SurveySVIS

survey = SurveySVIS(
    survey_id="TST_2024_SYNTH",
    country_code="TST",
    year=2024,
    survey_name="Synthetic Household Survey",
    study_type=StudyType.lsms,
    data_collection_mode="CAPI",
    language="English",
    variables=[age, sex],
    source_file="questionnaire.pdf",
    source_format="pdf",
    extraction_date=date.today(),
)
```

Values such as the ISO3 country code and survey identifier are conventions, not
format validators in `0.1.x`. Validate institutional naming rules in your
application boundary.

## 3. Serialize and validate

```python
payload = survey.model_dump_json(indent=2)
restored = SurveySVIS.model_validate_json(payload)

assert restored == survey
```

Use `survey.model_dump(mode="json")` when you need a JSON-compatible Python
dictionary instead of a string.

## 4. Add diagnostics and write artifacts

```python
from pathlib import Path

from survey_scribe.results import Diagnostic, DiagnosticCode, ExtractionResult

result = ExtractionResult(
    output=survey,
    diagnostics=(
        Diagnostic(
            code=DiagnosticCode.quality_low_confidence,
            message="Review q_age against the printed questionnaire.",
        ),
    ),
)

written = result.write(Path("output"))

print(written.status.value)
for artifact in written.artifacts:
    print(artifact.kind, artifact.path, artifact.sha256)
```

The first write creates a main JSON file, generation files, a manifest, and an
active pointer. A second write for the same survey fails unless you explicitly
pass `overwrite=True`.

## 5. Normalize a local source

```python
from pathlib import Path

from survey_scribe.sources import SourceRegistry

document = SourceRegistry.default().convert(Path("questionnaire.md"))

for block in document.blocks:
    print(block.order, block.kind, block.provenance)
```

Source conversion returns `SourceDocument`. It does not call a model provider and
does not create `SurveySVIS`. See [Local Sources](../guides/sources.md) for format,
resource, and security controls.
