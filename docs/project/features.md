# Features and Limitations

This ledger describes the current public package. It separates implemented
features, conditional integration patterns, and features that are not included.

## Support labels

| Label | Meaning |
| --- | --- |
| Supported | Implemented with deterministic repository tests |
| Conditional | The package contract exists, but a host-owned or private integration step is required |
| Configuration-only | A model capability is declared but no protected live model row is verified |
| Not included | No public package implementation exists |

## Questionnaire extraction

| Capability | Status | Notes |
| --- | --- | --- |
| Questionnaire instrument to `SurveySVIS` | Supported | Native XLSForm or provider-assisted document extraction |
| Local PDF, DOCX, XLSX, CSV, HTML, Markdown, and text inputs | Supported | Format-specific limits apply |
| Provider-free XLSForm SVIS | Supported | Use `SourceRegistry.convert_for_svis()` |
| Ordered sync and async batches | Supported | One shared limiter per batch |
| Completed-answer records | Conditional | Use a caller-defined closed Pydantic model |
| Respondent microdata table | Not included | No built-in respondent or submission schema |
| Submission-export parser | Not included | No vendor-specific response parser |
| Automatic skipped-answer classification | Not included | Answer state is caller-defined |
| Remote URL ingestion | Not included | Local paths and confined bundles only |

## Source processing

| Capability | Status | Notes |
| --- | --- | --- |
| Deterministic source blocks and tables | Supported | Physical provenance and coverage are validated |
| Resource and archive controls | Supported | Limits are configurable |
| Offline PDF OCR | Supported | Approved local artifacts and English-only EasyOCR |
| XLSX formula or macro execution | Not included | Unsafe workbook features are rejected |
| XLSForm external choice CSV | Supported | Companion must be declared in `SourceBundle` |
| Multilingual PDF OCR | Not included | Current OCR path is English only |
| Operating-system sandbox | Not included | Host isolation is still required |

## Routing and skip patterns

| Capability | Status | Notes |
| --- | --- | --- |
| Directed questionnaire multigraph | Supported | Accepted edges are separate from audit candidates |
| Activation conditions | Supported | Representation only |
| Native XLSForm relevance projection | Supported | Limited expression subset |
| Provider-assisted routing evidence | Configuration-only | No verified live model row |
| Append-only review history | Supported | Original evidence remains available |
| Repeat and roster templates | Supported | No respondent-instance expansion |
| Runtime interview traversal | Not included | No next-screen engine |
| Condition evaluation on answers | Not included | No application of routing to respondent data |
| Complete XPath or JSON Logic behavior | Not included | Unsupported logic remains opaque |
| Graphical routing editor | Not included | JSON schema and Python models only |

## Results and serialization

| Capability | Status | Notes |
| --- | --- | --- |
| Typed `success`, `partial`, and `failed` results | Supported | Status follows operational evidence |
| Versioned generation directories | Supported | Includes manifest, active pointer, and optional sidecar |
| Durable overwrite and recovery | Supported | Process lock, journal, and idempotent repair |
| Legacy SVIS projection | Supported | Stable ordered JSON contract |
| Routed manifest version 2 | Supported | Routed main plus exact legacy projection |
| Raw prompt or provider response persistence | Not included | Digests are stored instead |
| Stable routed main at output root | Not included | Routed main is generation-specific |

## AI providers

| Adapter | Status | Transport |
| --- | --- | --- |
| OpenAI | Configuration-only | OpenAI-compatible strict structured output |
| OpenRouter | Configuration-only | Reviewed OpenAI-compatible preset |
| Vercel AI Gateway | Configuration-only | Reviewed OpenAI-compatible preset |
| Custom OpenAI-compatible HTTPS | Configuration-only | Explicit base URL |
| Azure OpenAI and compatible Microsoft Foundry endpoint | Configuration-only | Azure Chat Completions route |
| Anthropic | Configuration-only | Dedicated Anthropic adapter |
| Caller `StructuredProvider` | Conditional | Application owns transport and capability evidence |

No named live model/version is marked `verified`. The package does not discover
deployments, model availability, quota, or live endpoint access.

## Platform integrations

| Platform | Status | Boundary |
| --- | --- | --- |
| Palantir Foundry | Conditional, not tested | A dataset-filesystem transform pattern is documented; no shipped Palantir adapter or approved package artifact exists |
| Microsoft Foundry | Conditional | Supported only through an Azure OpenAI-compatible Chat Completions endpoint |
| mAI Factory | Conditional, offline contract only | Uses generic Azure endpoint, token, and header extension points; private profile is host-owned |
| Hosted Survey Scribe service | Not included | Package is a local Python library and CLI |

Survey Scribe does not provision infrastructure, configure network policy,
assign roles, deploy models, manage quota, or discover managed identity. The host
must supply endpoints and credentials.

## Provider operations

Supported provider behavior includes strict schema inspection, normalized usage,
bounded retries, per-call or per-batch concurrency, safe error normalization,
and lazy SDK imports.

The package does not include:

- Responses transport
- Provider Batch API
- Embeddings
- Translation
- Text-to-speech
- Search
- Health endpoints
- Streaming responses
- A request-timeout setting
- `Retry-After` handling or jitter
- A circuit breaker
- A process-global rate limiter
- Cost or spend controls
- Exact backend identity for a dynamic gateway route

## Public interfaces

Supported interfaces are:

- `SurveyScribe` sync, async, and ordered batch conversion
- `StructuredPipeline` and `ChunkedStructuredPipeline`
- `QuestionnaireRouter` Python API
- Typed SVIS, routed SVIS, source, provider, result, and serialization modules
- `survey-scribe convert`
- `survey-scribe batch`
- `survey-scribe providers`
- `survey-scribe config check`
- `survey-scribe schema export routing`

The CLI does not include a routing command, completed-answer command,
source-normalization command, or manifest-inspection command.

## Compatibility and release state

Survey Scribe supports CPython 3.11 through 3.13 and Pydantic 2.11.7 or later
below major version 3. The package is alpha software. No approved PyPI release is
available. Production users must install an approved wheel, Conda artifact, or
pinned source revision.

See [Compatibility](../compatibility.md), [Installation](../getting-started/installation.md),
and the [API Overview](../reference/index.md).
