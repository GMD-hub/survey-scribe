# AI Providers

Survey Scribe uses a provider only when a source or routing path needs
model-assisted structured extraction. Native XLSForm conversion and complete
native XLSForm routing can use zero provider calls.

## Choose an adapter

| Provider value | Extra | Endpoint | Credential |
| --- | --- | --- | --- |
| `openai` | `openai` | OpenAI default or explicit `OPENAI_BASE_URL` | API key |
| `openrouter` | `openai` | Reviewed default preset or explicit override | API key |
| `vercel` | `openai` | Reviewed default AI Gateway preset or explicit override | API key |
| `custom` | `openai` | Explicit OpenAI-compatible HTTPS URL | API key or generic bearer value |
| `azure`, `azure_openai` | `openai` | Azure endpoint, API version, and deployment | API key or token callback |
| `anthropic` | `anthropic` | Dedicated Anthropic SDK | API key |
| Injected provider | Application-owned | Defined by `StructuredProvider` | Application-owned |

All public facade capability rows are `configuration-only`. No named live
model/version is currently `verified`.

## Install only required extras

```console
python -m pip install "survey-scribe[openai]"
python -m pip install "survey-scribe[anthropic]"
```

Provider SDK imports are lazy. Importing `survey_scribe` or running
`survey-scribe --help` does not import a provider SDK, acquire a credential, or
make a network request.

No approved PyPI release is currently available. Apply these extras to an
approved wheel or pinned source installation as described in
[Installation](../getting-started/installation.md).

## List adapters and evidence

```console
survey-scribe providers
```

This command prints a static adapter table. It does not discover deployments,
models, credentials, quota, endpoint access, or live availability.

## Configure with environment variables

The SDK reads the environment only when `resolve_environment=True`. The CLI
always resolves its supplied environment.

```bash
export SURVEY_SCRIBE_PROVIDER="openai"
export SURVEY_SCRIBE_MODEL="<approved-model-id>"
export OPENAI_API_KEY="<secret-from-runtime-store>"
```

Then run:

```console
survey-scribe config check
survey-scribe convert questionnaire.docx --output-dir output
```

`config check` validates settings and adapter construction. It does not send a
model request.

Generic variables are:

```text
SURVEY_SCRIBE_PROVIDER
SURVEY_SCRIBE_MODEL
SURVEY_SCRIBE_BASE_URL
SURVEY_SCRIBE_API_KEY
SURVEY_SCRIBE_BEARER_TOKEN
```

Provider-specific variables include `OPENAI_API_KEY`, `OPENAI_BASE_URL`,
`OPENROUTER_API_KEY`, `AI_GATEWAY_API_KEY`, `ANTHROPIC_API_KEY`, and the standard
`AZURE_OPENAI_*` endpoint, deployment, API-version, and key fields.

There is no `SURVEY_SCRIBE_API_VERSION` environment variable and no environment
variable for `token_callback`.

## OpenAI-compatible quick start

```python
import os
from pathlib import Path

from survey_scribe import ResultStatus, SurveyScribe

with SurveyScribe(
    provider="openai",
    model="<approved-model-id>",
    api_key=os.environ["OPENAI_API_KEY"],
) as client:
    result = client.convert(Path("questionnaire.docx"))

if result.status is not ResultStatus.success:
    raise RuntimeError("Send provider extraction to review")
```

Use `openrouter` or `vercel` as the provider value for those reviewed defaults.
An explicit `base_url` overrides the named preset, so it also changes the data
egress destination. Apply the same endpoint review and allowlist policy as for
`custom`. Use `custom` only with an explicit HTTPS URL whose API implements the
required OpenAI Chat Completions and strict structured-output behavior.

Do not use `token_callback` with non-Azure facade providers. The current facade
credential check can accept it, but those provider factories do not consume it.

## Azure and Microsoft Foundry quick start

```python
import os
from pathlib import Path

from survey_scribe import ResultStatus, SurveyScribe

with SurveyScribe(
    provider="azure_openai",
    model="<approved-deployment-name>",
    base_url="https://resource.example/",
    api_version="<approved-api-version>",
    api_key=os.environ["AZURE_OPENAI_API_KEY"],
) as client:
    result = client.convert(Path("questionnaire.docx"))

if result.status is not ResultStatus.success:
    raise RuntimeError("Send Azure extraction to review")
```

Use a synchronous no-argument `token_callback` instead of `api_key` for a
host-managed token. The host owns scope selection, identity discovery, refresh,
and failure handling.

Only Azure OpenAI-compatible Chat Completions endpoints are supported. See
[Microsoft Foundry](../platforms/microsoft-foundry.md).

## Anthropic quick start

```python
import os
from pathlib import Path

from survey_scribe import ResultStatus, SurveyScribe

with SurveyScribe(
    provider="anthropic",
    model="<approved-model-id>",
    api_key=os.environ["ANTHROPIC_API_KEY"],
) as client:
    result = client.convert(Path("questionnaire.docx"))

if result.status is not ResultStatus.success:
    raise RuntimeError("Send Anthropic extraction to review")
```

Anthropic capability rows must not advertise `seed`. Unsupported generation
settings fail before transport.

## Capability evidence

Every provider has a `ModelCapabilities` record. Strict schema inspection fails
before transport when structured output is disabled, strict schema is disabled,
evidence is `unknown`, the response model has an open object, or generation
settings exceed declared support.

| Evidence | Meaning |
| --- | --- |
| `unknown` | Do not send a request |
| `configuration-only` | Administrator-supplied declaration, not live proof |
| `verified` | Protected evidence for the exact provider, model/version, and SDK version |

Facade defaults declare a 32,000-token input limit and at least a 4,096-token
output limit. These are package assertions, not verified model limits. Construct
the adapter directly with an administrator-owned capability row when exact
limits matter.

## Retries and concurrency

Survey Scribe disables provider SDK retries and owns one bounded retry loop.
Transport and structured-validation retries share the same `max_attempts` budget.

Default policy:

```text
max attempts: 3
initial delay: 0.5 seconds
maximum delay: 8.0 seconds
backoff: exponential, no jitter
```

Authentication failures are not retried. Rate limits, timeouts, connection
failures, HTTP 408, and HTTP 5xx can be retried. Truncation fails closed.

`max_concurrency` limits one conversion or one ordered batch. It is not a
process-global limit. Add an application-level limiter when several clients can
run at the same time.

## Provider response

`ProviderResponse[T]` contains validated output, normalized usage, finish reason,
configured provider and model names, response ID, transport attempts, and
validation attempts. It does not contain the raw SDK request, response, or
headers.

The Azure and OpenAI adapters report configured route identity. They do not read
a dynamic backend model identity from the provider response.

## Custom provider

Implement `StructuredProvider` when a host needs a transport that the packaged
adapters do not support. The protocol requires schema inspection, token
estimation, one async `generate()` method, and normalized response metadata.

Use this boundary for a Palantir source-managed client, a non-standard
authentication method, or a gateway that does not implement the supported SDK
route. Do not route provider SDK objects into extraction or routing core code.

See [Provider Contracts](../reference/providers.md) for the exact protocol and
adapter signatures.

## Production checklist

1. Pin the provider SDK and Survey Scribe versions.
2. Use a closed response schema.
3. Supply reviewed capability limits.
4. Store credentials in the host secret system.
5. Apply endpoint host allowlists and egress policy outside the package.
6. Set retry, concurrency, and partial-result policy.
7. Run offline contract tests before any live request.
8. Record one authorized live verification for each supported model row.
9. Confirm provider logging, retention, region, and model-training policy.
10. Close the client with a sync or async context manager.

See [Configuration](configuration.md), [Security and API Keys](security.md), and
[Privacy and Local-First Boundaries](privacy.md).
