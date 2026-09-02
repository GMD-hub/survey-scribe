# Command-Line Interface

The installed command reports package help and version information and exports
the deterministic routing JSON Schema. It does not perform extraction or make a
provider call.

```console
survey-scribe --help
survey-scribe --version
survey-scribe schema export routing
```

The schema command writes only canonical JSON to standard output, so it can be
redirected to a file. It does not read configuration, environment credentials,
or optional provider SDKs. Passing a questionnaire input file is not supported by
the installed `0.1.x` command.

::: survey_scribe.cli
    options:
      members:
        - build_parser
        - main
