# Survey Scribe

<!-- cg:auto:overview -->
Survey Scribe converts local survey questionnaires to the typed Survey Variable Information Schema (SVIS). The base schema package `survey-scribe` provides typed SVIS Pydantic models with JSON serialization. It also provides synchronous, asynchronous, and batch APIs, provider adapters, safe local source normalization, deterministic chunking, questionnaire routing graphs, secure configuration, and versioned artifacts.

The DECDG / GPID team at the World Bank develops Survey Scribe. The package is at alpha status (v0.1.0). Package publication is subject to legal approval recorded in `docs/legal-disposition.md`.

Current focus: make the package work well with the World Bank MAI factory. After that, make the package Azure Foundry compatible.

## Contents

- [Home](README.md)
- [API Reference](api-reference.md)
- [Vignettes](vignettes.md)
- [Changelog](changelog.md)
<!-- cg:auto:end -->

<!-- cg:auto:installation -->
### Installation

Survey Scribe is a Python package. It supports Python `>=3.11,<3.14`. The project uses `uv` with a hatchling build backend and a `src/survey_scribe/` layout.

Install the locked development environment:

```bash
uv sync --locked --python 3.11
```

Optional dependency groups add provider and format support:

| Extra | Purpose |
|-------|---------|
| `[openai]` | OpenAI provider adapter |
| `[anthropic]` | Anthropic provider adapter |
| `[pdf]` | PDF source processing with Docling |
| `[tabular]` | Tabular source processing with openpyxl |

The package is at alpha status (v0.1.0). Publication is subject to legal approval recorded in `docs/legal-disposition.md`. Until publication, install from source.
<!-- cg:auto:end -->

<!-- cg:auto:quick-start -->
### Quick Start

Survey Scribe installs the `survey-scribe` CLI. The CLI supports:

- Single and batch questionnaire conversion
- Configuration checks
- Provider discovery
- Routing-schema export

Start with:

```bash
survey-scribe --help
```

Generated outputs are excluded from git: `output/*`, `*_svis.json`, and `survey-scribe.toml` stay local. Credentials in `.env` / `.env.*` are never committed; configuration is credential-safe.
<!-- cg:auto:end -->
