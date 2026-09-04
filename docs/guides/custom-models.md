# Custom Structured Output

Use `StructuredPipeline` when the required output is a Pydantic model other than
SVIS. Use `ChunkedStructuredPipeline` when the source can exceed one provider
request and your application can define how to combine chunk results.

These APIs use the same local source adapters, resource limits, strict provider
contract, retry policy, and result envelope as `SurveyScribe`. They do not apply
SVIS field rules, confidence policy, duplicate handling, or routing semantics.

## One-call pipeline

`StructuredPipeline` normalizes the source and makes exactly one provider call.
The complete normalized document must fit both `max_request_tokens` and the
provider capability limit. An oversized request fails before transport. The
provider response must validate as the supplied Pydantic model.

This executable example uses the package fake. It does not load a provider SDK,
read a credential, or access the network.

```python
# docs-exec: structured-pipeline-fake
from pydantic import BaseModel

from survey_scribe import ResultStatus, StructuredPipeline
from survey_scribe.providers import CapabilityEvidence, ModelCapabilities
from survey_scribe.providers.testing import DeterministicFakeProvider


class Summary(BaseModel):
    title: str
    question_count: int


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
provider = DeterministicFakeProvider(
    capabilities=capabilities,
    responder=lambda _request: Summary(
        title="Synthetic household questionnaire",
        question_count=2,
    ),
)
source = DOCS_TMP_PATH / "synthetic-questionnaire.txt"
source.write_text("Age in years\n\nEmployment status", encoding="utf-8")

result = StructuredPipeline(provider, Summary).convert(source)

assert result.status is ResultStatus.success
assert result.output == Summary(
    title="Synthetic household questionnaire",
    question_count=2,
)
assert provider.call_count == 1
```

In an application, inject a reviewed `StructuredProvider` instead of
`DeterministicFakeProvider`. The custom `instructions` value is a system
instruction. Source text remains inside a separate untrusted-data envelope.

## Chunked pipeline

`ChunkedStructuredPipeline` creates deterministic, ordered chunks under the
provider and request token ceilings. It calls the provider once per chunk under
one `max_concurrency` limit. It then passes successful `ProviderResponse` values
and ordered `FailedBlock` values to your reducer.

```python
from pydantic import BaseModel

from survey_scribe import ChunkedStructuredPipeline
from survey_scribe.providers import ProviderResponse
from survey_scribe.results import FailedBlock


class ChunkSummary(BaseModel):
    labels: tuple[str, ...]


class CombinedSummary(BaseModel):
    labels: tuple[str, ...]
    failed_chunks: tuple[str, ...]


def combine(
    responses: tuple[ProviderResponse[ChunkSummary], ...],
    failures: tuple[FailedBlock, ...],
) -> CombinedSummary:
    return CombinedSummary(
        labels=tuple(label for response in responses for label in response.output.labels),
        failed_chunks=tuple(failure.block_id for failure in failures),
    )


pipeline = ChunkedStructuredPipeline(
    provider,
    ChunkSummary,
    combine,
    max_request_tokens=32_000,
    overlap_tokens=1_000,
    max_concurrency=4,
    allow_partial=False,
)
```

The reducer owns merge, deduplication, ordering beyond chunk order, and domain
validation. The package does not infer these rules for a custom model. Overlap can
repeat source text, so a reducer must handle repeated facts when needed.

With the default `allow_partial=False`, any failed chunk produces a failed result
and the reducer does not run. With `allow_partial=True`, the reducer receives all
successful responses and failures; usable reducer output with failures has
`partial` status. An empty document calls the reducer with two empty tuples.

Both pipelines return `ExtractionResult`. They convert operational exceptions to
safe failed results, but they re-raise cancellation and process-control signals.
Synchronous `convert()` cannot run in an active event loop; async applications
must use `aconvert()` or `extract()`.

See the [Results guide](results.md) for statuses and generic JSON artifacts, and
the [providers reference](../reference/providers.md) for capability evidence.
