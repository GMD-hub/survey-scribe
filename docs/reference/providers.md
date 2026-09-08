# Provider Contracts

Routing depends on the provider-neutral `StructuredProvider` port. Provider SDKs
and Instructor remain inside adapters. Capability inspection must pass before
source content is sent.

::: survey_scribe.providers.base
    options:
      members:
        - StructuredProvider
        - ProviderResponse
        - ProviderMessage
        - NormalizedUsage
        - ConcurrencyLimiter
        - SchemaDescriptor

::: survey_scribe.providers.capabilities
    options:
      members:
        - ModelCapabilities
        - CapabilityEvidence
        - schema_descriptor

## Supported adapters and evidence

All shipped adapter paths have deterministic contract tests. No named live
model/version has completed the protected verification process, so every model
row created by the public facade is `configuration-only`. This label means the
declared limits are used for validation; it is not a claim that the endpoint,
model behavior, context window, or extraction quality was verified.

| Provider value | Extra | Endpoint configuration | Credential | Evidence |
| --- | --- | --- | --- | --- |
| `openai` | `openai` | Reviewed OpenAI preset, or `OPENAI_BASE_URL` | `OPENAI_API_KEY` | configuration-only |
| `openrouter` | `openai` | Reviewed OpenRouter preset | `OPENROUTER_API_KEY` | configuration-only |
| `vercel` | `openai` | Reviewed Vercel AI Gateway preset | `AI_GATEWAY_API_KEY` | configuration-only |
| `custom` | `openai` | Explicit `base_url` required; use HTTPS in production | `SURVEY_SCRIBE_API_KEY` | configuration-only |
| `azure`, `azure_openai` | `openai` | Endpoint, API version, deployment | API key or token callback | configuration-only |
| `anthropic` | `anthropic` | Dedicated Anthropic adapter | `ANTHROPIC_API_KEY` | configuration-only |

Use `survey-scribe providers` to inspect this same evidence boundary. A
`verified` row would require a protected contract run against the exact named
provider, model/version, and SDK version. `unknown` evidence fails closed before
transport.

## Configuration examples

```console
# OpenAI
SURVEY_SCRIBE_PROVIDER=openai SURVEY_SCRIBE_MODEL=model-id survey-scribe config check

# OpenRouter
SURVEY_SCRIBE_PROVIDER=openrouter SURVEY_SCRIBE_MODEL=model-id survey-scribe config check

# Vercel AI Gateway
SURVEY_SCRIBE_PROVIDER=vercel SURVEY_SCRIBE_MODEL=model-id survey-scribe config check

# Custom OpenAI-compatible HTTPS gateway
survey-scribe config check --provider custom --model model-id --base-url https://gateway.example/v1

# Azure OpenAI-compatible chat completions
survey-scribe config check --provider azure --model deployment-name \
  --base-url https://resource.example/ --api-version 2025-04-01-preview

# Anthropic
SURVEY_SCRIBE_PROVIDER=anthropic SURVEY_SCRIBE_MODEL=model-id survey-scribe config check
```

These commands require the matching credential environment variable. They
validate adapter construction but do not make a model request.

## Adapter construction

`InstructorOpenAIProvider` is the packaged OpenAI-compatible adapter. Applications
must supply an administrator-owned `ModelCapabilities` row. A
`configuration_only` row allows deterministic schema and request checks; it does
not prove that a live provider or model was tested.

```python
from survey_scribe import QuestionnaireRouter
from survey_scribe.providers import CapabilityEvidence, ModelCapabilities
from survey_scribe.providers.openai_compatible import InstructorOpenAIProvider


async def synthetic_completion(**request: object) -> object:
    response_model = request["response_model"]
    payload = build_synthetic_response_for(response_model)
    return payload


capabilities = ModelCapabilities(
    provider="test-gateway",
    model="configured-model",
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
provider = InstructorOpenAIProvider(
    model=capabilities.model,
    capabilities=capabilities,
    completion=synthetic_completion,
)
router = QuestionnaireRouter(provider)
```

The injected `completion` keeps this construction credential-free and avoids an
SDK import. Production applications normally omit it, install the `openai` extra,
and supply credentials from protected runtime configuration. Direct OpenAI or
LangChain clients are not routing inputs. Adapt them to `StructuredProvider`.

Named presets are available for OpenAI, OpenRouter, and Vercel AI Gateway.
OpenRouter accepts only the non-secret `HTTP-Referer` and `X-Title` headers.
Custom gateways require an explicit base URL and use the same header allowlist.

Azure OpenAI uses `AzureOpenAIProvider`. Configure exactly one API key or
refreshable token callback. Survey Scribe retains and passes the callback to the
Azure SDK without calling it during construction or persisting returned token
values. `InstructorAnthropicProvider` is available
through the optional `anthropic` extra. All SDK imports remain lazy.

### Generic Azure-compatible gateway headers

Applications that need caller-defined gateway headers construct
`AzureOpenAIProvider` directly and inject it through the existing
`StructuredProvider` boundary. The facade, CLI, TOML, and environment schema do
not define gateway-specific fields.

```python
import os

from survey_scribe import SurveyScribe
from survey_scribe.providers import CapabilityEvidence, ModelCapabilities
from survey_scribe.providers.azure import AzureOpenAIProvider


def acquire_token() -> str:
    return os.environ["SYNTHETIC_AZURE_RUNTIME_TOKEN"]


def sensitive_headers() -> dict[str, str]:
    return {
        "X-Synthetic-Aux-Key": os.environ["SYNTHETIC_GATEWAY_AUX_KEY"],
    }


capabilities = ModelCapabilities(
    provider="azure_openai",
    model="deployment-name",
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
    api_version="api-version",
    token_callback=acquire_token,
    metadata_headers={"X-Synthetic-Route": "questionnaire-extraction"},
    sensitive_headers_callback=sensitive_headers,
    required_headers={"X-Synthetic-Route", "X-Synthetic-Aux-Key"},
    capabilities=capabilities,
)
client = SurveyScribe(provider)
```

`metadata_headers` is only for non-secret, static request metadata. The adapter
copies it during construction. `sensitive_headers_callback` is a bounded,
synchronous function invoked for each package-owned request attempt. The adapter
copies its returned values into an attempt-local mapping; it does not store or
serialize those values. `required_headers`
fails safely before transport when a required name is absent.

The application owns token and auxiliary-secret acquisition. Keep these
callbacks non-blocking, and do not make a network request from them. A gateway
route or header confirms only the configured route; it does not prove the exact
backend model or service. Only Foundry endpoints that expose the Azure
OpenAI-compatible chat-completions API are supported. See [Security and API
Keys](../guides/security.md) for credential handling rules.

Survey Scribe disables each SDK's internal retry loop and applies only the
configured package retry policy. Transport and structured-validation attempts
are therefore bounded and reported consistently. Anthropic capability rows must
not advertise `seed`; explicit unsupported settings fail before transport.

No live model row is advertised as verified by this table. A row becomes
`verified` only after a protected, named model/version contract run records that
evidence. Unknown rows fail closed during schema inspection.

The placeholder `build_synthetic_response_for()` represents an application test
fixture and is not a package function. No quality claim follows from this example.

::: survey_scribe.providers.openai_compatible
    options:
      members:
        - InstructorOpenAIProvider
        - OpenAICompatiblePreset

::: survey_scribe.providers.azure
    options:
      members:
        - AzureOpenAIProvider

::: survey_scribe.providers.anthropic
    options:
      members:
        - InstructorAnthropicProvider
