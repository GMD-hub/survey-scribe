# Practical Examples

## Validate an Existing SVIS File

```python
from pathlib import Path

from survey_scribe import SurveySVIS

source = Path("output/TST_2024_SYNTH_svis.json")
survey = SurveySVIS.model_validate_json(source.read_text(encoding="utf-8"))

review_queue = [variable for variable in survey.variables if variable.needs_review]
```

A Pydantic `ValidationError` identifies invalid fields and values. Handle that
exception at the application boundary where the source filename and remediation
can be reported safely.

## Separate Missing Categories

```python
from survey_scribe import SurveyVariable


def missing_codes(variable: SurveyVariable) -> set[int | str]:
    """Return codes explicitly classified as non-substantive responses."""
    if variable.categories is None:
        return set()
    return {category.code for category in variable.categories if category.is_missing}
```

## Write a Stable JSON Artifact

```python
from pathlib import Path

target = Path("output") / f"{survey.survey_id}_svis.json"
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(survey.model_dump_json(indent=2), encoding="utf-8")
```

Applications processing restricted questionnaires should place generated files
in an approved, access-controlled location. The repository ignores `output/*`
by default.

## Generate a JSON Schema

```python
import json
from pathlib import Path

from survey_scribe import SurveySVIS

schema = SurveySVIS.model_json_schema()
Path("survey-svis.schema.json").write_text(
    json.dumps(schema, indent=2),
    encoding="utf-8",
)
```

The generated schema is useful for editor validation and cross-language
consumers. Treat changes to it as compatibility-sensitive.
