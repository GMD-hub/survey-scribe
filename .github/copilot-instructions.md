# Survey Scribe GitHub Copilot Instructions

Survey Scribe is a typed, local-first Python package that converts supported
survey questionnaire files to the Survey Variable Information Schema (SVIS).

## Current Paths

| Path | Role |
| --- | --- |
| `src/survey_scribe/client.py` | Public synchronous and asynchronous `SurveyScribe` facade |
| `src/survey_scribe/models/svis.py` | Canonical SVIS Pydantic models |
| `src/survey_scribe/sources/` | Local source validation and adapters |
| `src/survey_scribe/providers/` | Structured provider ports and adapters |
| `src/survey_scribe/pipeline.py` | Deterministic extraction and quality policy |
| `src/survey_scribe/results.py` | Result status and artifact-write API |
| `src/survey_scribe/cli.py` | Installed argparse command |
| `docling_pipeline.py` | Deprecated repository-only 1.x compatibility shim |

Do not restore the removed root `agents/`, `extractors/`, or `schemas/`
implementations. New code uses package imports from `survey_scribe`.

## Commands

```console
uv run survey-scribe --help
uv run survey-scribe config check
uv run survey-scribe convert questionnaire.pdf --output-dir output
uv run survey-scribe batch questionnaire-a.pdf questionnaire-b.xlsx --output-dir output
uv run survey-scribe providers
uv run survey-scribe schema export routing
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run mkdocs build --strict
```

## Security And Compatibility

- Accept local paths only. Do not add remote URL ingestion.
- Read credentials from supported environment variables or non-echo input.
- Never write credentials, authorization headers, raw provider responses, or
  questionnaire text to logs, diagnostics, or manifests.
- Keep `docling_pipeline.py` lazy and preserve `run(Path, Path) -> None` through
  1.x.
- Preserve exact legacy SVIS serialization unless an approved intentional
  correction records the change.
- Keep provider SDKs behind adapters and do not create clients at import time.
- Use the public `SurveyScribe`, configuration, result, and source APIs in
  applications and commands.
