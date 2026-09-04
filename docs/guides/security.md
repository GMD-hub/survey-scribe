# Security and API Keys

API keys are bearer credentials. Anyone who obtains a key can use the provider
permissions assigned to it. Keep secrets out of source control, TOML, command
history, logs, diagnostics, and generated documentation.

Survey Scribe can resolve credentials into `SurveyScribeConfig`. Routing consumes
an injected `StructuredProvider`; the routing core does not read credentials or
import a provider SDK. Use the same controls when an application constructs the
optional provider adapter.

Survey Scribe has no telemetry client. Local normalization and native XLSForm
conversion do not send source content. Provider-backed extraction sends
normalized content to the endpoint that you configure, subject to that
provider's retention and logging policy. See [Privacy and Local-First
Boundaries](privacy.md).

## Recommended order

Use these options in decreasing order of preference:

1. A managed identity or short-lived token callback when the provider supports it.
2. A secret manager injected into an environment variable at process start.
3. A local `.env` file that is excluded from version control for development only.
4. Direct construction from a secret already held in memory.

Never put a literal key in Python, notebooks, TOML, YAML, shell scripts, test
fixtures, or command arguments.

## Environment variables

Set the provider-standard variable for the current shell.

=== "Linux and macOS"

    ```bash
    export OPENAI_API_KEY="<your-key>"
    ```

=== "PowerShell"

    ```powershell
    $Env:OPENAI_API_KEY = "<your-key>"
    ```

=== "Windows Command Prompt"

    ```bat
    set OPENAI_API_KEY=YOUR_KEY_VALUE
    ```

Then explicitly allow environment resolution:

```python
from survey_scribe.config import SurveyScribeConfig

config = SurveyScribeConfig.resolve(
    constructor={"provider": "openai", "model": "gpt-model-name"},
    resolve_environment=True,
)

assert config.api_key is not None
```

Use `SURVEY_SCRIBE_API_KEY` when you need one generic variable across supported
providers. It takes priority over a provider-specific key.

## Local `.env` files

Survey Scribe does not read `.env` files automatically. This prevents unexpected
filesystem access by SDK code. For local development, load one explicitly with
`python-dotenv`:

```console
python -m pip install python-dotenv
```

Create `.env` with restrictive filesystem permissions:

```dotenv
OPENAI_API_KEY=replace-with-your-secret
SURVEY_SCRIBE_MODEL=gpt-model-name
```

Exclude it from Git and provide only a placeholder template:

```gitignore
.env
.env.*
!.env.example
```

```dotenv title=".env.example"
OPENAI_API_KEY=
SURVEY_SCRIBE_MODEL=
```

Load the file without replacing secrets already supplied by the environment:

```python
from dotenv import load_dotenv

from survey_scribe.config import SurveyScribeConfig

load_dotenv(override=False)

config = SurveyScribeConfig.resolve(
    constructor={"provider": "openai"},
    resolve_environment=True,
)
```

Do not use a committed `.env` file for CI or production.

## Direct configuration construction

Direct construction is safe only when the secret comes from a protected runtime
source. Wrap the value in Pydantic `SecretStr` so accidental representation does
not show the clear text:

```python
import os

from pydantic import SecretStr

from survey_scribe.config import SurveyScribeConfig

config = SurveyScribeConfig(
    provider="openai",
    model="gpt-model-name",
    api_key=SecretStr(os.environ["OPENAI_API_KEY"]),
)
```

Do not do this:

```python
config = SurveyScribeConfig(api_key="<hard-coded-secret>")  # Never do this.
```

Only one of `api_key`, `bearer_token`, or `token_callback` can be configured.

## Structured provider boundary

Applications can construct an adapter from the `openai` extra or provide another
implementation of `StructuredProvider`. Instructor is internal to the packaged
OpenAI-compatible adapter. Direct OpenAI or LangChain objects are not routing
core inputs; adapt them to `StructuredProvider` so schema inspection, normalized
metadata, retry counts, truncation, and shared concurrency remain enforceable.

Do not first place a key in an ordinary application dictionary that might be
logged or serialized. Do not add it to a URL query string, graph, sidecar,
manifest, or evaluator fixture.

## Test capture versus production

G6 protects one optional live test capture. It does not configure production and
must not become an interactive approval on every production request. Production
administrators own provider selection, gateway quota, secret storage, source
authorization, logging, and institutional retention policy. The package enforces
configured per-request, schema, source-binding, and concurrency bounds; it does
not claim control over gateway-side retention.

## Token callbacks

A synchronous, no-argument callback can provide short-lived bearer tokens:

```python
from survey_scribe.config import SurveyScribeConfig


def acquire_token() -> str:
    return credential_provider.get_token()


config = SurveyScribeConfig(
    provider="azure",
    model="survey-extractor",
    token_callback=acquire_token,
)
```

The callback is excluded from configuration serialization. Keep the credential
provider itself outside the serialized application state.

## GitHub Actions secrets

Current Survey Scribe repository tests are credential-free. A downstream
application can create a separate protected provider job. The command below is a
placeholder for that downstream repository, not a Survey Scribe test path:

```yaml
- name: Run provider integration tests
  env:
    OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
  run: python -m pytest downstream_tests/protected_provider
```

Use protected GitHub environments for production credentials. Documentation
builds do not need provider credentials and must not receive them.

## TOML and URL controls

`survey-scribe.toml` is for non-secret settings. The loader rejects `api_key`,
`bearer_token`, `token_callback`, and other credential-like keys at any nesting
level.

`base_url` rejects user information, fragments, and sensitive query parameters
such as `api_key`, `token`, `client_secret`, `password`, `signature`, and `sig`.
Use the provider SDK authentication field or request header instead.

## Logging and diagnostics

Credential fields are excluded from `model_dump()`, JSON serialization, and
`repr(config)`. Package redaction helpers remove common authorization headers,
assigned secrets, URL credentials, query secrets, and known sensitive values.

These controls reduce disclosure risk but cannot identify every secret format.

- Never log `os.environ`, request headers, provider request objects, or raw exceptions.
- Pass known secret values to redaction helpers before recording third-party errors.
- Review sidecar diagnostics before sharing them outside the approved environment.
- Treat questionnaire text and SVIS output as potentially restricted data.

The main SVIS artifact intentionally contains `question_text`. Redaction of
diagnostics does not remove questionnaire content from the main output.

## Rotation and incident response

1. Revoke a disclosed key at the provider immediately.
2. Create a replacement with the minimum permissions and quota required.
3. Update the secret manager or CI secret without committing the value.
4. Restart affected workloads so that they read the new credential.
5. Inspect provider audit logs and usage for unauthorized activity.
6. Remove the secret from Git history if it was committed; deleting the current
   file alone is not sufficient.

Use separate keys for development, CI, and production. Add spend or rate limits
where the provider supports them, and rotate long-lived keys on a defined
schedule.
