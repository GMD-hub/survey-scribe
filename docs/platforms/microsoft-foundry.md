# Microsoft Foundry

Survey Scribe can use a Microsoft Foundry model endpoint only when that endpoint
implements the Azure OpenAI-compatible Chat Completions contract used by
`AsyncAzureOpenAI`.

Microsoft Foundry and Palantir Foundry are different platforms. See the separate
[Palantir Foundry](palantir-foundry.md) deployment assessment.

## Supported boundary

The Azure adapter constructs this request shape:

```text
{azure_endpoint}/openai/deployments/{deployment}/chat/completions
    ?api-version={api_version}
```

Supported configuration includes:

- One HTTPS endpoint.
- One deployment or route name.
- One API version.
- An Azure API key or a synchronous token callback.
- Strict Instructor tool output.
- Package-owned bounded retries and concurrency.

The package does not support a Responses-only endpoint, deploy a model, create a
project, assign roles, configure network access, manage quota, discover managed
identity, or call a health route.

All facade-generated model capabilities are `configuration-only`. They permit
request validation but do not prove live endpoint access, model limits, or
quality.

## Install

Use an approved distribution with the `openai` extra:

```console
python -m pip install "survey-scribe[openai]"
```

No approved PyPI release is currently available. See
[Installation](../getting-started/installation.md) for wheel and pinned-source
options.

## API-key quick start

Keep credentials outside source and TOML:

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
    raise RuntimeError("Send questionnaire extraction to review")
```

The endpoint must use HTTPS and must not contain user information, a fragment,
or a recognized secret query parameter.

## Host-managed token quick start

The host application owns identity and token acquisition:

```python
from pathlib import Path

from survey_scribe import SurveyScribe


def acquire_token() -> str:
    return application_token_source()


async def extract_questionnaire():
    async with SurveyScribe(
        provider="azure_openai",
        model="<approved-deployment-name>",
        base_url="https://resource.example/",
        api_version="<approved-api-version>",
        token_callback=acquire_token,
    ) as client:
        return await client.aconvert(Path("questionnaire.docx"))
```

`application_token_source()` is application code. Survey Scribe does not import
Azure Identity, select a scope, or call the token callback during construction.
The Azure SDK calls it when authentication is required.

Use a refreshable callback for managed runtimes. A configured `bearer_token`
becomes a callback that always returns the same static value.

## Direct provider construction

Construct `AzureOpenAIProvider` directly when an administrator must provide an
exact `ModelCapabilities` row or approved gateway headers. This is required for
the generic [mAI Factory](../integrations/mai-factory.md) pattern.

Do not combine an injected provider with facade-level model, endpoint,
credential, API-version, callback, or environment-resolution arguments. Use a
non-secret `SurveyScribeConfig` only for generation, retry, confidence,
concurrency, and artifact settings.

## Production checklist

1. Confirm that the endpoint implements Azure Chat Completions for the selected API version.
2. Confirm the exact deployment name and strict structured-output behavior.
3. Supply an administrator-owned capability row when generic limits are not sufficient.
4. Use host-managed key or token storage.
5. Set endpoint egress and data-retention policy outside Survey Scribe.
6. Run an offline SDK contract test with the exact headers and route.
7. Run one authorized live test before you label a model row `verified`.
8. Inspect `success`, `partial`, and `failed` results before artifact publication.

## Operational limits

- SDK retries are disabled. Survey Scribe owns the retry budget.
- Authentication and header-callback failures are not retried.
- Rate limits, timeouts, connection failures, HTTP 408, and HTTP 5xx can be retried.
- There is no public provider request-timeout setting.
- There is no jitter, `Retry-After` handling, circuit breaker, or process-global limiter.
- Configured provider and model names are reported. The adapter does not capture a dynamic backend model identity from the response.

See [AI Providers](../guides/ai-providers.md),
[Configuration](../guides/configuration.md), and
[Provider Contracts](../reference/providers.md).
