# Contributing to Survey Scribe

## Development Setup

Install [uv](https://docs.astral.sh/uv/), clone the repository, and create the
locked development environment:

```console
uv sync --locked --python 3.11
```

Only synthetic or separately approved fixtures may be committed. Do not add
restricted questionnaires, credentials, provider responses, or generated
survey output.

## Quality Checks

Run the checks used by continuous integration:

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

Distribution tests require a built wheel and the prepared dependency
wheelhouse. CI is the authoritative isolated-install check.

## Pull Requests

1. Create a focused feature branch.
2. Add or update tests for behavioral changes.
3. Update documentation and the `Unreleased` changelog section.
4. Run all relevant quality checks.
5. Open a pull request with the motivation, behavior change, and validation.

Use clear commit subjects such as `feat: add workbook extraction` or
`fix: preserve categorical string codes`.

## Release Boundary

GitHub Pages documentation publication is approved and uses the Pages OpenID
Connect workflow recorded in `docs/legal-disposition.md`. Package publication
remains disabled. Do not add package publishing credentials, tag-triggered
release jobs, or package registry deployment permissions without separate
approval.
