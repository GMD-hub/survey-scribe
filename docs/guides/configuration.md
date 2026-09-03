# Configuration

`SurveyScribeConfig` validates application settings and resolves them from
explicit values, TOML, and environment variables. Reading files and environment
variables is opt-in for SDK code.

```python
from survey_scribe.config import SurveyScribeConfig

config = SurveyScribeConfig(
    provider="openai",
    model="gpt-model-name",
    max_concurrency=4,
    confidence_threshold=0.7,
)
```

The object is frozen, rejects unknown fields, and hides input values in Pydantic
validation errors.

## Main settings

| Field | Type | Default | Validation |
| --- | --- | --- | --- |
| `config_version` | `Literal[1]` | `1` | Must be the integer `1` |
| `provider` | `str` | `"openai"` | Trimmed, lowercased, hyphens become underscores |
| `model` | `str \| None` | `None` | Cannot be empty when set |
| `base_url` | `AnyHttpUrl \| None` | `None` | Cannot include user information, fragments, or sensitive query keys |
| `api_version` | `str \| None` | `None` | Cannot be empty when set |
| `api_key` | `SecretStr \| None` | `None` | Excluded from representation and serialization |
| `bearer_token` | `SecretStr \| None` | `None` | Excluded from representation and serialization |
| `token_callback` | `Callable[[], str] \| None` | `None` | Synchronous, no-argument callback |
| `generation` | `GenerationConfig` | See below | Frozen nested model |
| `retry` | `RetryConfig` | See below | Frozen nested model |
| `max_concurrency` | `int` | `4` | From 1 through 128 |
| `confidence_threshold` | `float` | `0.7` | From `0.0` through `1.0` |
| `routing` | `RoutingConfig` | See below | Provider-neutral frozen limits |
| `artifacts` | `ArtifactConfig` | See below | Frozen nested model |

At most one credential form can be set. A credential is not required for local
schema and source operations.

## Nested settings

### Generation

| Field | Type | Default | Validation |
| --- | --- | --- | --- |
| `temperature` | `float` | `0.0` | Finite value from `0.0` through `2.0` |
| `max_output_tokens` | `int` | `4096` | At least 1 |
| `seed` | `int \| None` | `None` | Strict integer when set |

### Retry

| Field | Type | Default | Validation |
| --- | --- | --- | --- |
| `max_attempts` | `int` | `3` | From 1 through 10 |
| `initial_delay_seconds` | `float` | `0.5` | Finite and nonnegative |
| `max_delay_seconds` | `float` | `8.0` | At least `initial_delay_seconds` |

### Artifacts

| Field | Type | Default | Validation |
| --- | --- | --- | --- |
| `sidecar` | `bool` | `True` | Strict Boolean |
| `manifest` | `Literal[True]` | `True` | Manifests cannot be disabled |

### Routing

| Field | Default | Purpose |
| --- | ---: | --- |
| `max_source_quote_chars` | 2,000 | Maximum exact evidence quote |
| `max_request_tokens` | 32,000 | Hard request ceiling before provider capability limits |
| `max_inventory_items_per_call` | 250 | Stable inventory partition limit |
| `max_candidate_targets_per_reference` | 10 | Ambiguity bound before review |
| `max_discrepancies_per_review_call` | 25 | Bounded reviewer packet |
| `max_source_spans_per_decision` | 8 | Citation bound per decision |
| `max_condition_depth` | 6 | Condition AST depth limit |
| `max_condition_nodes` | 100 | Condition AST node limit |
| `low_confidence_threshold` | 0.70 | Adaptive incoming-pass trigger |
| `unusual_in_degree_threshold` | 4 | Adaptive incoming-pass trigger |
| `unusual_out_degree_threshold` | 3 | Adaptive incoming-pass trigger |
| `max_concurrency` | 4 | Shared outbound-attempt ceiling |
| `generation` | `GenerationConfig()` | Routing-provider generation settings |
| `retry` | `RetryConfig()` | Routing-provider retry settings |

Routing configuration contains no credentials and does not select or construct a
provider. The top-level `generation` and `retry` values do not replace these
routing-nested values. Production applications create a `StructuredProvider`
from administrator-owned configuration and inject it with the nested settings:

```python
router = QuestionnaireRouter(provider, config=config.routing)
```

!!! note

    `ArtifactConfig` records future application defaults. In `0.1.x`, pass
    `sidecar` and `overwrite` directly to `ExtractionResult.write()`.

## Safe TOML

Create `survey-scribe.toml` for non-secret settings:

```toml
config_version = 1
provider = "azure"
model = "survey-extractor"
base_url = "https://example.openai.azure.com/"
api_version = "2025-04-01-preview"
max_concurrency = 4
confidence_threshold = 0.7

[generation]
temperature = 0.0
max_output_tokens = 4096

[retry]
max_attempts = 3
initial_delay_seconds = 0.5
max_delay_seconds = 8.0

[artifacts]
sidecar = true
manifest = true

[routing]
max_request_tokens = 32000
max_inventory_items_per_call = 250
max_concurrency = 4

[routing.generation]
temperature = 0.0
max_output_tokens = 4096

[routing.retry]
max_attempts = 3
initial_delay_seconds = 0.5
max_delay_seconds = 8.0
```

Credentials are prohibited anywhere in TOML. The loader rejects credential-like
field names recursively.

Load this exact file and opt in to environment variables:

```python
from survey_scribe.config import SurveyScribeConfig

config = SurveyScribeConfig.from_config(
    "survey-scribe.toml",
    resolve_environment=True,
)
```

When no path is supplied, `from_config()` checks only
`./survey-scribe.toml`. It does not search parent or home directories.

## Environment variables

Generic names take priority over provider-specific names.

| Variable | Field |
| --- | --- |
| `SURVEY_SCRIBE_PROVIDER` | `provider` |
| `SURVEY_SCRIBE_MODEL` | `model` |
| `SURVEY_SCRIBE_BASE_URL` | `base_url` |
| `SURVEY_SCRIBE_API_KEY` | `api_key` |
| `SURVEY_SCRIBE_BEARER_TOKEN` | `bearer_token` |

Supported provider-specific names are:

| Provider | Variables |
| --- | --- |
| `openai` | `OPENAI_API_KEY`, `OPENAI_BASE_URL` |
| `openrouter` | `OPENROUTER_API_KEY` |
| `vercel` | `AI_GATEWAY_API_KEY` |
| `anthropic` | `ANTHROPIC_API_KEY` |
| `azure`, `azure_openai` | `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_VERSION`, `AZURE_OPENAI_DEPLOYMENT` |

There is no `SURVEY_SCRIBE_API_VERSION` environment variable in `0.1.x`.

## Resolution precedence

`SurveyScribeConfig.resolve()` uses this high-to-low order:

1. Non-`None` constructor values.
2. Explicit fields in a supplied `SurveyScribeConfig`.
3. Generic `SURVEY_SCRIBE_*` environment variables.
4. Provider-specific environment variables.
5. Explicit TOML values.
6. Model defaults.

Environment access occurs only when `resolve_environment=True`.

```python
config = SurveyScribeConfig.resolve(
    constructor={"model": "runtime-model"},
    config_path="survey-scribe.toml",
    resolve_environment=True,
)
```

`resolve_cli()` always resolves the supplied environment and gives flags the
highest priority. Pass `environ={}` in controlled tests to prevent access to the
process environment.

## Errors

Invalid resolved settings raise `ConfigurationError`. Multiple credential forms
raise `AmbiguousCredentialError`. Both expose stable package error codes. Do not
include raw secret values when you add application context to these errors.

See [Security and API Keys](security.md) for environment, `.env`, direct
construction, CI, rotation, and logging practices.
