# Release Readiness

## Current State

The repository is configured to produce release-candidate evidence without
publishing it:

- CI tests Python 3.11-3.13 and the supported operating systems.
- Coverage must remain at or above 95 percent.
- Ruff and Pyright check source and tests.
- Hatchling builds the wheel and source distribution.
- Twine validates core metadata and README rendering.
- Distribution tests inspect contents and install the wheel in isolation.
- MkDocs builds this site in strict mode and stores it as a workflow artifact.

PyPI upload and GitHub Pages deployment jobs are intentionally absent. The
project's legal disposition permits build-only artifacts but still prohibits
publication.

## Versioning

The package uses a static PEP 440 version in `pyproject.toml`. Before a release:

1. Choose the Semantic Versioning increment.
2. Update `project.version` in `pyproject.toml`.
3. Regenerate `uv.lock` with `uv lock`.
4. Move changelog entries from `Unreleased` to the dated version.
5. Build and validate both distribution artifacts.

The runtime `survey_scribe.__version__` reads installed metadata, so no second
source version needs editing.

## Local Release Candidate

```console
uv sync --locked --python 3.11
uv run pytest tests/unit tests/characterization tests/test_schema.py \
  --cov=survey_scribe --cov-branch --cov-report=term-missing
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run mkdocs build --strict
uv build
uv run twine check --strict dist/*
```

## Activation After Approval

Publication requires a separate recorded authorization. At that point:

1. Configure PyPI Trusted Publishing for `GMD-hub/survey-scribe`, a protected
   `pypi` environment, and the approved workflow filename.
2. Add an isolated manual publish job with only `id-token: write` permission.
3. Configure GitHub Pages to use GitHub Actions as its source.
4. Add an isolated Pages deployment job with only `pages: write` and
   `id-token: write` permissions.
5. Require environment approval and rerun the complete release-candidate checks.

Do not use long-lived PyPI tokens or repository-wide write permissions.
