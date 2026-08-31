# Command-Line Interface

The installed command is a bootstrap interface. It reports package help and
version information; it does not perform extraction.

```console
survey-scribe --help
survey-scribe --version
```

Passing an input file is not supported by the installed `0.1.x` command.

::: survey_scribe.cli
    options:
      members:
        - build_parser
        - main
