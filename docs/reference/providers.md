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

The placeholder `build_synthetic_response_for()` represents an application test
fixture and is not a package function. No quality claim follows from this example.

::: survey_scribe.providers.openai_compatible
    options:
      members:
        - InstructorOpenAIProvider
