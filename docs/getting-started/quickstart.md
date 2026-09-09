# Quickstart

This guide extracts questionnaire metadata and writes a versioned artifact set.
It does not extract respondent answer rows. See
[Completed Questionnaires](../guides/completed-questionnaires.md) for a
caller-defined answer contract.

## 1. Extract an XLSForm without a provider

Install the `tabular` extra and run:

```python
from datetime import date
from pathlib import Path

from survey_scribe import ExtractionResult
from survey_scribe.results import ArtifactProvenance
from survey_scribe.sources import SourceRegistry

conversion = SourceRegistry.default().convert_for_svis(
    Path("questionnaire.xlsx"),
    extraction_date=date.today(),
)
if conversion.svis is None:
    raise RuntimeError("The workbook is not a supported XLSForm")

review_codes = tuple(item.code for item in conversion.document.diagnostics)
if conversion.native is not None:
    review_codes += tuple(item.code for item in conversion.native.diagnostics)
if review_codes:
    raise RuntimeError(f"Review XLSForm diagnostics before publication: {review_codes}")
if conversion.document.snapshot_sha256 is None:
    raise RuntimeError("The source snapshot has no digest")

result = ExtractionResult(
    output=conversion.svis,
    artifact_provenance=ArtifactProvenance(
        source_sha256=(conversion.document.snapshot_sha256,),
        model_response_sha256=(),
        prompt_versions=(),
    ),
)
written = result.write(Path("output"))
```

This path makes no provider call. `conversion.svis` preserves questionnaire
variables, choices, module labels, raw relevance, and retained notes.
`conversion.native` contains group, repeat, expression, and routing structure.
The stable SVIS artifact does not contain that full native structure.

The output contains the stable `<survey_id>_svis.json` file and a
`.survey-scribe/` generation tree with a manifest, sidecar, and active pointer.
A second write for the same survey fails unless you pass `overwrite=True`.

## 2. Inspect the result

```python
from survey_scribe import ResultStatus

if written.status is ResultStatus.success:
    survey = written.output
elif written.status is ResultStatus.partial:
    review_codes = tuple(item.code for item in written.diagnostics)
else:
    raise RuntimeError("No usable questionnaire output")
```

A quality warning alone remains `success`. `partial` means that usable output
has an operational failure, such as a failed source block. A failed result has no
output and cannot be written.

## 3. Normalize a local source

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
without a provider call after provider construction. See [Questionnaire Sources](../guides/sources.md) for format,
resource, and security controls.

## 4. Convert with `SurveyScribe`

For a configured provider, use the synchronous facade outside an event loop:

The PDF example also needs the `pdf` extra and a validated local OCR artifact
directory. Use DOCX or text when you want to test the provider without OCR.

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
from pathlib import Path
from tempfile import TemporaryDirectory

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
with TemporaryDirectory() as temporary_directory:
    source = Path(temporary_directory) / "synthetic-questionnaire.txt"
    source.write_text("Age in years", encoding="utf-8")

    with SurveyScribe(provider, extraction_date=date(2026, 9, 4)) as client:
        result = client.convert(source)

    assert result.status is ResultStatus.success
    assert result.output is not None
    assert result.output.variables[0].raw_name == "age"
```

## 5. Run the installed command

```console
survey-scribe convert questionnaire.txt --output-dir output
```

The [command-line guide](../cli.md) documents configuration, output files, batch
runs, and default versus strict exit behavior.

## 6. Continue the workflow

1. Read the full [Questionnaire Extraction](../guides/extraction.md) guide.
2. Add [Skip Patterns](../guides/skip-patterns.md) and routing when needed.
3. Select an [AI Provider](../guides/ai-providers.md) for non-native sources.
4. Use the [Palantir Foundry](../platforms/palantir-foundry.md) transform for a hosted native XLSForm path.
