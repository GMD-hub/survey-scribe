# Common Use Cases

These examples use packaged APIs only. They do not depend on the repository-only
legacy provider pipeline.

## Validate an existing SVIS file

```python
from pathlib import Path

from pydantic import ValidationError

from survey_scribe import SurveySVIS

source = Path("output/TST_2024_SYNTH_svis.json")

try:
    survey = SurveySVIS.model_validate_json(source.read_text(encoding="utf-8"))
except ValidationError as error:
    validation_issues = error.errors(include_input=False)
```

Handle the exception at the application boundary so you can add the source path
without exposing the full document payload.

## Build a human-review queue

```python
from survey_scribe import DataType, SurveySVIS, SurveyVariable


def needs_policy_review(variable: SurveyVariable, threshold: float) -> bool:
    is_categorical = variable.data_type in {
        DataType.categorical_single,
        DataType.categorical_multi,
    }
    return (
        variable.needs_review
        or variable.extraction_confidence < threshold
        or variable.question_text is None
        or (is_categorical and not variable.categories)
    )


def review_queue(survey: SurveySVIS, threshold: float = 0.7) -> list[SurveyVariable]:
    return [
        variable
        for variable in survey.variables
        if needs_policy_review(variable, threshold)
    ]
```

This policy is explicit because the model does not derive `needs_review`.

## Extract missing-value codes

```python
from survey_scribe import SurveyVariable


def missing_codes(variable: SurveyVariable) -> set[int | str]:
    if variable.categories is None:
        return set()
    return {
        category.code
        for category in variable.categories
        if category.is_missing
    }
```

This supports recoding non-substantive values before harmonization.

## Normalize and chunk a questionnaire

```python
from pathlib import Path

from survey_scribe.sources import SourceLimits, SourceRegistry
from survey_scribe.sources.chunking import chunk_document

limits = SourceLimits(max_source_bytes=50 * 1024 * 1024, max_pages=500)
document = SourceRegistry.default().convert(
    Path("questionnaire.html"),
    limits=limits,
)
chunked = chunk_document(document, max_tokens=4_000, overlap_tokens=200)

work_items = tuple(
    {
        "chunk_id": chunk.id,
        "text": chunk.text,
        "provenance": [item.model_dump(mode="json") for item in chunk.provenance],
    }
    for chunk in chunked.chunks
)
```

Treat each `text` value as untrusted input when sending it to another system.
The package does not send these work items to a provider.

## Publish a result with diagnostics

```python
from pathlib import Path

from survey_scribe.results import Diagnostic, ExtractionResult

result = ExtractionResult(
    output=survey,
    diagnostics=(
        Diagnostic(
            code="APPLICATION_REVIEW_COMPLETE",
            message="Two category labels were verified against the source.",
        ),
    ),
)

written = result.write(Path("approved-output"))
artifact_digests = {
    str(reference.path): reference.sha256
    for reference in written.artifacts
}
```

Custom string diagnostic codes are accepted. Use a documented application
namespace to avoid confusion with built-in package codes.

## Generate JSON Schema for another system

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

Treat generated schema changes as compatibility-sensitive. Pin the Survey Scribe
version used by schema consumers.

## Test configuration without process secrets

```python
from survey_scribe.config import SurveyScribeConfig

test_environment = {
    "SURVEY_SCRIBE_PROVIDER": "openai",
    "SURVEY_SCRIBE_MODEL": "test-model",
    "SURVEY_SCRIBE_API_KEY": "test-only-placeholder",
}

config = SurveyScribeConfig.resolve(
    resolve_environment=True,
    environ=test_environment,
)

assert config.provider == "openai"
assert config.model == "test-model"
```

Passing an explicit mapping makes precedence tests deterministic and prevents
accidental use of a developer credential.
