---
project-name: "Survey Scribe"
team: "DECDG / GPID -- World Bank"
created: "2026-09-04"
last-reviewed: "2026-09-04"
---

# Survey Scribe

## Objective

Survey Scribe converts local survey questionnaires to the typed Survey Variable
Information Schema (SVIS). It provides synchronous, asynchronous, and batch APIs,
provider adapters, safe local source normalization, deterministic chunking,
questionnaire routing graphs, secure configuration, and versioned artifacts.

## Key Deliverables

- Base schema package `survey-scribe` with typed SVIS Pydantic models and JSON serialization
- Installed CLI for single and batch conversion, configuration checks, provider discovery, routing-schema export
- Optional dependency groups: `[openai]`, `[anthropic]`, `[pdf]` (Docling), `[tabular]` (openpyxl)
- Source-grounded routing multigraphs with native XLSForm relevance/repeat routing
- Locked development environment: `uv sync --locked --python 3.11`
- MkDocs documentation site (deployed via GitHub Actions)

## Constraints

- Restricted survey data: `tests/samples/*` is gitignored — questionnaire PDFs may be restricted data
- Generated outputs excluded from git: `output/*`, `*_svis.json`, `survey-scribe.toml`
- Credentials: `.env` / `.env.*` are never committed; credential-safe configuration
- Python version window: `>=3.11,<3.14`
- Alpha status (v0.1.0): package publication subject to legal approval recorded in `docs/legal-disposition.md`

## Current Focus

We are working on making sure that this Python package works well with the MAI
factory of the World Bank. Then we will make sure that the package is Azure
Foundry compatible.
