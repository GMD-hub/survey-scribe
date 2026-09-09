# Survey Scribe

[![CI](https://github.com/GMD-hub/survey-scribe/actions/workflows/ci.yml/badge.svg)](https://github.com/GMD-hub/survey-scribe/actions/workflows/ci.yml)
[![Python 3.11-3.13](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Survey Scribe converts local survey questionnaires to the typed Survey Variable
Information Schema (SVIS). It provides synchronous, asynchronous, and batch APIs,
provider adapters, safe local source normalization, deterministic chunking,
questionnaire routing graphs, secure configuration, and versioned artifacts.

> **Alpha status:** The source tree declares version `0.1.0` and contains the
> public `SurveyScribe` API, conversion CLI, typed models, source and provider
> adapters, transactional artifacts, and `QuestionnaireRouter`. No approved PyPI
> release is currently available.

## Features

- Typed SVIS models with Pydantic validation and JSON serialization.
- Stable top-level imports for schema consumers.
- Numeric, categorical, text, date, and other variable classifications.
- Missing-category, source-provenance, confidence, and review metadata.
- Local PDF, DOCX, XLSX, CSV, HTML, Markdown, and text normalization.
- Token-aware chunking with stable overlap and table provenance.
- Credential-safe configuration and versioned artifact manifests.
- Source-grounded directed routing multigraphs with separate evidence and audit history.
- Native XLSForm relevance and repeat routing without a provider call.
- Caller-defined structured pipelines for completed-form records.
- A PEP 561 `py.typed` marker for editor and type-checker support.
- An installed CLI for single and batch conversion, configuration checks,
  provider listing, and deterministic routing-schema export.

The standard client extracts questionnaire instrument metadata. It does not
produce respondent microdata, classify skipped answers, execute routing, or
expand repeat instances.

## Installation

After publication is approved, install the base schema package with:

```console
pip install survey-scribe
```

For development from this repository, use the locked environment:

```console
uv sync --locked --python 3.11
```

Optional dependency groups are available for provider and document adapters:

```console
pip install "survey-scribe[openai]"
pip install "survey-scribe[anthropic]"
pip install "survey-scribe[pdf]"
pip install "survey-scribe[tabular]"
```

The base package includes the CLI. Install provider and source extras required by
the selected conversion path.

## Quick Start

```python
from datetime import date

from survey_scribe.sources import SourceRegistry

conversion = SourceRegistry.default().convert_for_svis(
    "questionnaire.xlsx",
    extraction_date=date.today(),
)
if conversion.svis is None:
    raise RuntimeError("The workbook is not a supported XLSForm")

review_codes = tuple(item.code for item in conversion.document.diagnostics)
if conversion.native is not None:
    review_codes += tuple(item.code for item in conversion.native.diagnostics)
if review_codes:
    raise RuntimeError(f"Review XLSForm diagnostics before use: {review_codes}")

survey = conversion.svis
```

This native XLSForm path makes no provider call. PDF, DOCX, and other
questionnaire instruments use `SurveyScribe` with a configured provider.

Inspect the installed command without loading optional providers:

```console
survey-scribe --help
survey-scribe --version
survey-scribe providers
survey-scribe config check
survey-scribe convert questionnaire.pdf --output-dir output
survey-scribe batch questionnaire-a.pdf questionnaire-b.xlsx --output-dir output
survey-scribe schema export routing > questionnaire-routing-graph-v1.0.json
```

Set credentials with environment variables or use `--prompt-api-key` /
`--prompt-bearer-token`. The CLI writes sidecars and manifests by default,
refuses existing artifacts unless `--overwrite` is present, and supports
`--strict` when partial output must produce a nonzero exit. See the
[CLI guide](docs/cli.md) and [migration guide](docs/migration.md).

## Documentation

The public website includes end-to-end questionnaire extraction, completed-form
contracts, skip-pattern examples, Palantir Foundry deployment, Microsoft Foundry,
mAI Factory, AI provider setup, artifacts, security, privacy, and generated API
references.

- [Documentation website](https://gmd-hub.github.io/survey-scribe/)
- [DeepWiki project guide](https://deepwiki.com/GMD-hub/survey-scribe)
- [Extraction guide](docs/guides/extraction.md)
- [Completed questionnaires](docs/guides/completed-questionnaires.md)
- [Skip patterns](docs/guides/skip-patterns.md)
- [Palantir Foundry](docs/platforms/palantir-foundry.md)
- [mAI Factory](docs/integrations/mai-factory.md)
- [AI providers](docs/guides/ai-providers.md)

```console
uv run mkdocs serve
```

The local site is available at `http://127.0.0.1:8000/` while the server runs.
Pushes to `main` build and deploy the strict static site to GitHub Pages through
`.github/workflows/deploy-docs.yml`.

## Development

```console
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest tests/unit tests/characterization tests/test_schema.py \
  --cov=survey_scribe --cov-branch --cov-report=term-missing
uv run mkdocs build --strict
uv build
uv run twine check --strict dist/*
```

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for fixture controls and pull request
requirements. Security reports follow [`SECURITY.md`](SECURITY.md).

## Versioning

Survey Scribe uses PEP 440 and Semantic Versioning. The current static version is
declared once in `pyproject.toml`; the runtime `survey_scribe.__version__` value
is read from installed distribution metadata. Release changes are recorded in
[`CHANGELOG.md`](CHANGELOG.md).

## License

Survey Scribe is licensed under the [MIT License](LICENSE). Package publication
is a separate operational decision and remains gated.
