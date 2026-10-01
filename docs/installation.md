# Installation

## Supported Python Versions

Survey Scribe supports CPython 3.11, 3.12, and 3.13 on Linux, macOS, and Windows.

## From PyPI

Survey Scribe `0.1.x` is alpha software, with published releases available on
PyPI. Install the base package with:

```console
python -m pip install survey-scribe
```

The base installation contains Pydantic, `defusedxml`, the typed package API,
and the CLI. It does not load provider SDKs, OCR models, or document converters
at import time.

## From a Built Wheel

Build and install a local release candidate:

```console
uv build
python -m pip install dist/survey_scribe-0.1.1-py3-none-any.whl
```

Use a fresh virtual environment for a realistic installation check. Do not rely
on imports from the repository root.

## Development Environment

Install the exact tested dependency graph from `uv.lock`:

```console
uv sync --locked --python 3.11
```

The development group includes pytest, coverage, Ruff, Pyright, MkDocs,
Hatchling, build, and Twine.

## Optional Dependencies

| Extra | Purpose | Installation |
| --- | --- | --- |
| `openai` | OpenAI-compatible provider adapter dependencies | `pip install "survey-scribe[openai]"` |
| `anthropic` | Anthropic provider adapter dependencies | `pip install "survey-scribe[anthropic]"` |
| `pdf` | Docling and OCR dependencies | `pip install "survey-scribe[pdf]"` |
| `tabular` | Workbook parsing dependencies | `pip install "survey-scribe[tabular]"` |

These extras supply optional provider and source dependencies. The installed
`survey-scribe` command is in the base package; the deprecated repository-only
`docling_pipeline.py` script is not included in the wheel.

## Verify the Install

```console
survey-scribe --version
survey-scribe --help
python -c "from survey_scribe import SurveySVIS; print(SurveySVIS.__name__)"
```

The final command should emit `SurveySVIS` without importing provider or OCR
libraries.
