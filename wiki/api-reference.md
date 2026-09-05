# API Reference

<!-- cg:auto:functions -->
### Functions and Models

Survey Scribe exposes typed SVIS Pydantic models, JSON serialization, synchronous and asynchronous conversion APIs, batch conversion, source normalization, deterministic chunking, routing graphs, and provider adapters.

#### `AzureOpenAIProvider`

The public Azure OpenAI adapter separates non-secret metadata from request-local secret headers:

```python
AzureOpenAIProvider(
    *,
    deployment: str,
    azure_endpoint: str,
    api_version: str,
    capabilities: ModelCapabilities,
    api_key: str | None = None,
    token_callback: Callable[[], str] | None = None,
    metadata_headers: Mapping[str, str] | None = None,
    sensitive_headers_callback: Callable[[], Mapping[str, str]] | None = None,
    required_headers: Collection[str] = (),
    completion: Completion | None = None,
) -> None
```

`metadata_headers` is copied when the provider is created. `sensitive_headers_callback` runs immediately before each package-owned request attempt, and its returned mapping is not retained. `required_headers` is copied and checked without regard to letter case after both header channels are merged. Caller-defined headers cannot replace authentication or HTTP transport headers.
<!-- cg:auto:end -->

<!-- cg:auto:parameters -->
### Parameters

| Parameter | Requirement |
|-----------|-------------|
| `deployment` | Azure deployment name used as the provider model identifier. |
| `azure_endpoint` | Valid Azure HTTPS endpoint. Credentials in the URL are not permitted. |
| `api_version` | Non-empty Azure API version. |
| `capabilities` | `ModelCapabilities` entry whose provider is `azure` or `azure_openai`. |
| `api_key` | Optional Azure API key. For normal SDK use, configure exactly one of `api_key` and `token_callback`. |
| `token_callback` | Optional synchronous callback that supplies a refreshable Azure token. It is mutually exclusive with `api_key`. |
| `metadata_headers` | Optional mapping of static, non-secret headers. The provider copies the mapping during construction. |
| `sensitive_headers_callback` | Optional synchronous, non-blocking callback that returns attempt-local secret headers. The provider validates the result for each attempt and does not retain it. |
| `required_headers` | Optional collection of header names that must be present after metadata and sensitive headers are merged. Names are copied and matched case-insensitively. |
| `completion` | Optional custom completion implementation. Credentials can be omitted when this is supplied; `api_key` and `token_callback` still cannot both be set. |

Metadata and sensitive header names must not collide. Header names and values must be valid, and sensitive values are not permitted in `metadata_headers`. Invalid constructor input raises a fresh `TypeError` or `ValueError` after credential-bearing constructor state is detached.
<!-- cg:auto:end -->

<!-- cg:auto:return-values -->
### Return Values and Failures

Conversion APIs return SVIS documents as JSON. Artifacts are versioned. Generated outputs are excluded from git: `output/*` and `*_svis.json` stay local.

When an Instructor response is already an instance of the requested Pydantic response model, the adapter returns that instance without dumping and validating it again. This preserves aliases, computed fields, serializers, and non-idempotent validator behavior. The schema descriptor hashes the exact effective strict schema sent to the provider, including its deterministic root title.

Provider failures have a safe public contract:

- Authentication failures raise a fresh `ProviderAuthenticationError` with code `PROVIDER_AUTHENTICATION_FAILED` and message `Provider authentication failed.`
- Exhausted rate limits raise a fresh `ProviderRateLimitError` with code `PROVIDER_RATE_LIMITED` and message `The structured provider rate limit was exhausted.`
- Other transport failures raise a fresh `ProviderTransportError` with code `PROVIDER_TRANSPORT_FAILED`, message `The structured provider transport failed.`, and normalized retryability.

These package exceptions do not retain the raw provider exception, its cause or context, or secret-bearing traceback frames. Cancellation, keyboard interruption, and system exit keep their control category but use fresh exceptions without the raw message or traceback.
<!-- cg:auto:end -->

← [Home](README.md)
