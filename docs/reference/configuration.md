# Configuration API

The configuration API has no implicit file or environment access unless the
selected resolution method requests it. Credential fields are excluded from
representation and serialization.

See [Configuration](../guides/configuration.md) for fields, precedence, TOML, and
environment names. See [Security and API Keys](../guides/security.md) before
supplying a credential.

::: survey_scribe.config
    options:
      members:
        - GenerationConfig
        - RetryConfig
        - ArtifactConfig
        - SurveyScribeConfig
