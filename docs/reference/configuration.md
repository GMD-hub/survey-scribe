# Configuration API

The configuration API has no implicit file or environment access unless the
selected resolution method requests it. Credential fields are excluded from
representation and serialization.

See [Configuration](../guides/configuration.md) for fields, precedence, TOML, and
environment names. See [Security and API Keys](../guides/security.md) before
supplying a credential.

The downloadable [configuration serialization schema](schemas.md) is generated
from this model and checked for drift. It excludes credentials and the callable
token provider by design.

::: survey_scribe.config
    options:
      members:
        - GenerationConfig
        - RetryConfig
        - ArtifactConfig
        - SurveyScribeConfig
