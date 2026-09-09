# mAI Factory

mAI Factory integration uses Survey Scribe's generic Azure OpenAI-compatible
provider extension points. There is no separate `mai_factory` provider, CLI
profile, TOML section, or environment profile in the public package.

!!! important "Evidence boundary"

    The header and callback mechanism has offline synthetic contract tests. The
    public repository does not contain a protected live mAI Factory result. Exact
    endpoint, API version, route alias, token scope, metadata headers, auxiliary
    key header, and onboarding steps must come from an approved private
    application configuration.

## Architecture

The application bootstrap owns all mAI-specific values and injects one
`AzureOpenAIProvider` through the existing `StructuredProvider` boundary:

```text
private runtime configuration
  -> primary token callback
  -> static non-secret metadata headers
  -> per-attempt sensitive header callback
  -> required header names
  -> AzureOpenAIProvider
  -> SurveyScribe / QuestionnaireRouter / StructuredPipeline
```

Survey Scribe keeps source normalization, strict schema checks, retries,
concurrency, result handling, artifacts, and privacy controls local to the
package.

## Prerequisites

Obtain these values through your approved private process:

| Value | Public example placeholder |
| --- | --- |
| Azure-compatible endpoint | `https://gateway.example/azure` |
| API version | `<approved-api-version>` |
| Deployment or route alias | `<approved-deployment-or-route-alias>` |
| Primary token source | `APPLICATION_AZURE_TOKEN` |
| Static metadata names and values | `X-Application-Route` |
| Auxiliary secret header name and source | `X-Application-Aux-Key` |
| Required header set | Application-owned tuple |
| Verified model limits and settings | Administrator-owned `ModelCapabilities` |

Do not put exact private values, tokens, subscription keys, tenant IDs, scopes,
contacts, or internal package instructions in this public repository.

## Install

Install an approved package artifact with the `openai` extra:

```console
python -m pip install "survey-scribe[openai]"
```

Keep private credential utilities outside `src/survey_scribe`. The core package
supports Python 3.11 through 3.13 and does not depend on an organization-specific
token package.

## Configure the provider

This complete example uses only generic placeholders:

```python
import os
from pathlib import Path

from survey_scribe import ResultStatus, SurveyScribe, SurveyScribeConfig
from survey_scribe.config import GenerationConfig, RetryConfig
from survey_scribe.providers import CapabilityEvidence, ModelCapabilities
from survey_scribe.providers.azure import AzureOpenAIProvider


def acquire_primary_token() -> str:
    return os.environ["APPLICATION_AZURE_TOKEN"]


def acquire_sensitive_headers() -> dict[str, str]:
    return {
        "X-Application-Aux-Key": os.environ["APPLICATION_GATEWAY_AUX_KEY"],
    }


capabilities = ModelCapabilities(
    provider="azure_openai",
    model="<approved-deployment-or-route-alias>",
    structured_output=True,
    strict_schema=True,
    max_input_tokens=32_000,
    max_output_tokens=4_096,
    supported_generation_settings=frozenset(
        {"temperature", "max_output_tokens", "seed"}
    ),
    evidence=CapabilityEvidence.configuration_only,
    tested_sdk_version="application-managed",
)

provider = AzureOpenAIProvider(
    deployment=capabilities.model,
    azure_endpoint="https://gateway.example/azure",
    api_version="<approved-api-version>",
    token_callback=acquire_primary_token,
    metadata_headers={
        "X-Application-Route": "questionnaire-extraction",
    },
    sensitive_headers_callback=acquire_sensitive_headers,
    required_headers=(
        "X-Application-Route",
        "X-Application-Aux-Key",
    ),
    capabilities=capabilities,
)

runtime = SurveyScribeConfig(
    generation=GenerationConfig(
        temperature=0.0,
        max_output_tokens=4_096,
    ),
    retry=RetryConfig(
        max_attempts=3,
        initial_delay_seconds=0.5,
        max_delay_seconds=8.0,
    ),
    max_concurrency=4,
)

with SurveyScribe(provider, config=runtime) as client:
    result = client.convert(Path("questionnaire.docx"))

if result.status is ResultStatus.failed:
    raise RuntimeError("mAI-backed extraction failed")
if result.status is ResultStatus.partial:
    review_codes = tuple(item.code for item in result.diagnostics)
```

Replace the `configuration-only` capability limits only with approved values.
Do not label a row `verified` until an authorized live contract test covers the
exact endpoint, route, model version, and SDK version.

## Header channels

### Static metadata

Use `metadata_headers` only for non-secret values. The provider copies this
mapping during construction and retains it in memory.

Header names must be valid ASCII HTTP token names. Values must be non-empty
ASCII strings without control bytes or leading or trailing spaces. The adapter
rejects authentication, proxy, host, content, and transport headers.

### Per-attempt sensitive headers

`sensitive_headers_callback` is a synchronous, no-argument function. It runs
inside the concurrency slot immediately before each request attempt and runs
again for a retry. Its returned mapping is attempt-local and is not stored as
provider state or serialized.

Keep the callback fast. Read from an in-memory host cache, environment, or local
secret source. Do not make a network request from the callback because it blocks
the async event loop while it holds a concurrency slot.

### Required headers

`required_headers` is case-insensitive. A missing required name fails before
transport. The package default is empty, so the private bootstrap must supply the
approved set.

Primary authentication remains SDK-owned. Caller-defined `Authorization`, API
key, proxy, host, content, and transport headers are reserved.

## Desktop and managed-runtime patterns

Survey Scribe does not discover credentials. Each host injects the same
no-argument callback contract:

| Runtime | Host responsibility |
| --- | --- |
| Developer desktop | Acquire and refresh the approved user token outside Survey Scribe |
| Hosted application | Acquire and refresh an application token outside Survey Scribe |
| Managed data platform | Adapt platform-managed credentials to the callback and header contracts |

Do not import a private credential SDK into the public package. Keep the adapter
in the application repository and test it separately.

## Validate before production

1. Confirm that the endpoint implements Azure OpenAI Chat Completions.
2. Confirm that the Azure SDK constructs the approved route.
3. Confirm all static and secret header names with the gateway owner.
4. Test that callbacks are invoked again after a retry.
5. Test that missing headers fail before any request.
6. Test that errors and tracebacks do not expose known secret values.
7. Run one synthetic strict-schema extraction without network access.
8. Run one authorized live contract test with sanitized evidence.
9. Confirm provider retention, region, model-training, and abuse-monitoring policy.
10. Confirm that primary artifacts are written only to approved storage.

## Unsupported mAI features

The public package does not provide:

- Exact mAI endpoint or route configuration
- Credential or scope discovery
- A dedicated mAI provider value
- mAI CLI, TOML, or environment fields
- Responses transport
- A health-check client
- Dynamic backend model identity
- Model deployment, quota, networking, or role management
- Translation, text-to-speech, embeddings, or search integration

If the gateway requires a non-Azure authorization scheme, a caller-defined
reserved authentication header, or a non-Chat-Completions route, implement an
application-owned `StructuredProvider`.

See [Microsoft Foundry](../platforms/microsoft-foundry.md),
[AI Providers](../guides/ai-providers.md), and
[Provider Contracts](../reference/providers.md).
