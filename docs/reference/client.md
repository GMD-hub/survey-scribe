# Client and Pipeline API

`SurveyScribe` is the public SVIS extraction facade. It supports synchronous,
asynchronous, and ordered batch conversion. It accepts an injected
`StructuredProvider` or explicit provider configuration.

The standard output is questionnaire instrument metadata. It is not respondent
microdata. Use [Completed Questionnaires](../guides/completed-questionnaires.md)
for caller-defined answer records.

## Facade methods

| Method | Return | Use |
| --- | --- | --- |
| `convert(source)` | `ExtractionResult[SurveySVIS]` | One source outside an event loop |
| `aconvert(source)` | `ExtractionResult[SurveySVIS]` | One source in async code |
| `convert_many(sources)` | `list[ExtractionResult[SurveySVIS]]` | Ordered synchronous batch |
| `aconvert_many(sources)` | `list[ExtractionResult[SurveySVIS]]` | Ordered async batch |
| `close()` | `None` | Close a synchronous client |
| `aclose()` | `None` | Close an async client |

Use a context manager for lifecycle control. An injected provider cannot be
combined with facade-level model, endpoint, credential, API-version, callback,
or environment-resolution arguments.

## Constructor parameters

| Parameter | Purpose |
| --- | --- |
| `provider` | Injected `StructuredProvider`, provider name, or configured default |
| `model` | Model, deployment, or route identity for facade construction |
| `api_key` | Explicit primary API key |
| `base_url` | Explicit HTTPS endpoint; overrides OpenAI-compatible presets |
| `api_version` | Required Azure-compatible API version |
| `token_callback` | Synchronous Azure token callback |
| `config` | Non-secret runtime, generation, retry, routing, and artifact settings |
| `resolve_environment` | Opt in to SDK environment lookup |
| `source_registry` | Application source adapter registry |
| `source_limits` | Resource limits for all facade conversions |
| `extraction_date` | Stable date override for deterministic output |

`from_config()` adds an optional explicit TOML path. It checks only
`./survey-scribe.toml` when no path is supplied.

## Errors and result behavior

Invalid argument combinations raise `ProgrammerInputError`. A synchronous call
inside an event loop raises `RunningEventLoopError`. Use after close raises
`ClientClosedError`. Configuration errors are raised during construction.

Expected source and provider failures become a failed `ExtractionResult` with
safe diagnostics. Partial source or provider work can return usable output with
`ResultStatus.partial`. Cancellation and process-control signals propagate.

::: survey_scribe.client.SurveyScribe

`StructuredPipeline` makes one bounded provider call for a caller-defined
Pydantic model. `ChunkedStructuredPipeline` requires a caller reducer and defines
explicit strict and partial behavior.

Both custom pipelines expose `convert()`, `aconvert()`, and `extract()`. The
response model must be a closed Pydantic `BaseModel`. The chunked reducer owns
deduplication, conflicts, repeat assembly, and final domain validation.

::: survey_scribe.pipeline.StructuredPipeline

::: survey_scribe.pipeline.ChunkedStructuredPipeline

## Advanced pipeline exports

The module also declares the default extraction contracts and quality helpers as
public. Use these only when the facade and custom pipelines do not provide the
required control.

::: survey_scribe.pipeline
    options:
      members:
        - BlockExtraction
        - ExtractedMetadata
        - ExtractedVariable
        - ExtractionPipeline
        - PipelineConfig
        - QualityOutcome
        - QualityRecord
        - Reducer
        - apply_quality_policy

See [Custom Structured Output](../guides/custom-models.md) for guarantees,
limits, and a credential-free executable example.
