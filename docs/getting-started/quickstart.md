# Quickstart

This guide creates a typed SVIS record, serializes it, validates it again, and
writes a versioned artifact set. For direct questionnaire conversion, install the
required source and provider extras first.

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
is useful when you need to inspect normalized blocks. `SurveyScribe.convert()`
continues from normalized content to `SurveySVIS`, or uses native XLSForm output
without a provider call. See [Local Sources](../guides/sources.md) for format,
resource, and security controls.

## 6. Convert with `SurveyScribe`

For a configured provider, use the synchronous facade outside an event loop:

```python
from pathlib import Path

from survey_scribe import SurveyScribe

with SurveyScribe.from_config(resolve_environment=True) as client:
    result = client.convert(Path("questionnaire.pdf"))

if result.output is None:
    raise RuntimeError("Questionnaire conversion failed")
```

`from_config()` reads only `./survey-scribe.toml` unless a path is supplied.
Environment access is explicit in the SDK. In async code, use `aconvert()` and
`aclose()` instead.

The following executable test example proves the same facade without a provider
SDK, credential, or network route:

```python
# docs-exec: survey-scribe-fake
import json
from datetime import date

from survey_scribe import DataType, ResultStatus, SurveyScribe, SurveyVariable
from survey_scribe.pipeline import BlockExtraction, ExtractedMetadata, ExtractedVariable
from survey_scribe.providers import CapabilityEvidence, ModelCapabilities
from survey_scribe.providers.testing import DeterministicFakeProvider, FakeRequest


def respond(request: FakeRequest) -> object:
    if request.response_model is ExtractedMetadata:
        return ExtractedMetadata(
            survey_id="SYN_2026_HHS",
            country_code="SYN",
            year=2026,
            survey_name="Synthetic Household Survey",
        )
    content = next(message.content for message in request.messages if message.role == "user")
    chunk_id = content.split("CHUNK_ID: ", 1)[1].splitlines()[0]
    block_ids = tuple(json.loads(content.split("SOURCE_BLOCK_IDS: ", 1)[1].splitlines()[0]))
    return BlockExtraction(
        block_id=chunk_id,
        variables=(
            ExtractedVariable(
                variable=SurveyVariable(
                    raw_name="age",
                    label="Age in years",
                    data_type=DataType.numeric,
                    extraction_confidence=1.0,
                ),
                source_block_ids=(block_ids[0],),
            ),
        ),
    )


capabilities = ModelCapabilities(
    provider="synthetic",
    model="deterministic-fake",
    structured_output=True,
    strict_schema=True,
    max_input_tokens=32_000,
    max_output_tokens=4_096,
    supported_generation_settings=frozenset(
        {"temperature", "max_output_tokens", "seed"}
    ),
    evidence=CapabilityEvidence.configuration_only,
    tested_sdk_version="synthetic-no-sdk",
)
provider = DeterministicFakeProvider(capabilities=capabilities, responder=respond)
source = DOCS_TMP_PATH / "synthetic-questionnaire.txt"
source.write_text("Age in years", encoding="utf-8")

with SurveyScribe(provider, extraction_date=date(2026, 9, 4)) as client:
    result = client.convert(source)

assert result.status is ResultStatus.success
assert result.output is not None
assert result.output.variables[0].raw_name == "age"
```

## 7. Run the installed command

```console
survey-scribe convert questionnaire.txt --output-dir output
```

The [command-line guide](../cli.md) documents configuration, output files, batch
runs, and default versus strict exit behavior.
