# Command-Line Interface

The installed command supports local single and batch conversion, configuration
validation, provider discovery, and deterministic schema export.

```console
survey-scribe --help
survey-scribe --version
survey-scribe convert questionnaire.pdf --output-dir output
survey-scribe batch questionnaire-a.pdf questionnaire-b.xlsx --output-dir output
survey-scribe providers
survey-scribe config check
survey-scribe schema export routing
```

The schema command writes only canonical JSON to standard output and does not
read configuration or credentials. Conversion writes transactional artifacts by
default. See the [CLI guide](../cli.md) for configuration precedence, artifact
behavior, batch manifests, exit statuses, and credential controls.

::: survey_scribe.cli
    options:
      members:
        - build_parser
        - main
