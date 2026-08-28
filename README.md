# Survey Scribe

[![CI](https://github.com/GMD-hub/survey-scribe/actions/workflows/ci.yml/badge.svg)](https://github.com/GMD-hub/survey-scribe/actions/workflows/ci.yml)
[![Python 3.11-3.13](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Survey Scribe provides typed Pydantic models for the Survey Variable
Information Schema (SVIS), a structured representation of household survey
questionnaire metadata. The repository also contains a legacy local-first PDF
extraction pipeline used by the World Bank Global Monitoring Database team.

> **Alpha status:** Version `0.1.0` ships the SVIS model API and a bootstrap
> command. The legacy extraction pipeline is not included in the wheel and
> depends on internal authentication. PyPI and GitHub Pages publication remain
> disabled pending the approval recorded in
> [`docs/legal-disposition.md`](docs/legal-disposition.md).

## Features

- Typed SVIS models with Pydantic validation and JSON serialization.
- Stable top-level imports for schema consumers.
- Numeric, categorical, text, date, and other variable classifications.
- Missing-category, source-provenance, confidence, and review metadata.
- A PEP 561 `py.typed` marker for editor and type-checker support.
- A dependency-free `survey-scribe --help` and `--version` command.

## Installation

After publication is approved, install the base schema package with:

```console
pip install survey-scribe
```

For development from this repository, use the locked environment:

```console
uv sync --locked --python 3.11
```

Optional dependency groups are available for future provider and document
adapters:

```console
pip install "survey-scribe[openai]"
pip install "survey-scribe[anthropic]"
pip install "survey-scribe[pdf]"
pip install "survey-scribe[tabular]"
```

Installing an extra does not expose the repository-only legacy pipeline as a
wheel command.

## Quick Start

```python
from datetime import date

from survey_scribe import AnswerCategory, DataType, SurveySVIS, SurveyVariable

sex = SurveyVariable(
    raw_name="q_sex",
    label="Sex of household member",
    question_text="What is the sex of [NAME]?",
    data_type=DataType.categorical_single,
    categories=[
        AnswerCategory(code=1, label="Male"),
        AnswerCategory(code=2, label="Female"),
        AnswerCategory(code=9, label="Not stated", is_missing=True),
    ],
    extraction_confidence=1.0,
)

survey = SurveySVIS(
    survey_id="TST_2024_SYNTH",
    country_code="TST",
    year=2024,
    survey_name="Synthetic Household Survey",
    variables=[sex],
    source_file="questionnaire.pdf",
    source_format="pdf",
    extraction_date=date(2024, 6, 1),
)

json_payload = survey.model_dump_json(indent=2)
restored = SurveySVIS.model_validate_json(json_payload)
assert restored == survey
```

Inspect the installed command without loading optional providers:

```console
survey-scribe --help
survey-scribe --version
```

## Documentation

The documentation includes installation guidance, schema usage, practical
examples, generated API reference, compatibility notes, and release-readiness
instructions.

```console
uv run mkdocs serve
```

The local site is available at `http://127.0.0.1:8000/` while the server runs.

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
