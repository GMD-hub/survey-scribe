# Installation

Survey Scribe supports CPython 3.11, 3.12, and 3.13 on Linux, macOS, and Windows.
Use a virtual environment so that optional document libraries do not affect other
projects.

## Install from PyPI

=== "pip"

    ```console
    python -m pip install survey-scribe
    ```

=== "uv"

    ```console
    uv add survey-scribe
    ```

The base installation contains the typed package and Pydantic. It does not load
provider SDKs, OCR models, or document converters at import time.

!!! note "Alpha releases"

    If the requested release is not yet available from your package index,
    install a built wheel or the Git repository as shown below.

## Install optional features

Install only the extras that your application uses.

| Extra | Adds | Command |
| --- | --- | --- |
| `pdf` | Docling, EasyOCR, language detection, and PDF support | `python -m pip install "survey-scribe[pdf]"` |
| `tabular` | XLSX support through openpyxl | `python -m pip install "survey-scribe[tabular]"` |
| `openai` | OpenAI-compatible SDK dependencies for downstream integrations | `python -m pip install "survey-scribe[openai]"` |
| `anthropic` | Anthropic SDK dependencies for downstream integrations | `python -m pip install "survey-scribe[anthropic]"` |

The OpenAI and Anthropic extras install provider libraries. They do not add a
packaged extraction client or extraction command.

Multiple extras can be installed together:

```console
python -m pip install "survey-scribe[pdf,tabular]"
```

## Install a local wheel

Build and install the project in a clean environment:

```console
uv build
python -m pip install dist/survey_scribe-0.1.0-py3-none-any.whl
```

## Install from Git

Use a tagged revision or commit hash for reproducible deployments:

```console
python -m pip install \
  "survey-scribe @ git+https://github.com/GMD-hub/survey-scribe.git@305769db22d8471d722e075bc32f79113b4d8efc"
```

Avoid an unpinned branch URL in production.

## Set up a development environment

The repository uses `uv.lock` as the reproducible dependency lock:

```console
git clone https://github.com/GMD-hub/survey-scribe.git
cd survey-scribe
uv sync --locked --python 3.11
```

Run the documentation site locally with:

```console
uv run mkdocs serve
```

## Verify the installation

```console
survey-scribe --version
survey-scribe --help
python -c "from survey_scribe import SurveySVIS; print(SurveySVIS.__name__)"
```

The last command prints `SurveySVIS`. The command-line interface currently
provides package help and version output only.

## Common installation issues

### PDF conversion reports a missing dependency

Install the `pdf` extra, configure local OCR artifacts, and validate them before
conversion. See [PDF and OCR setup](../guides/sources.md#pdf-and-ocr-setup).

### XLSX conversion reports a missing dependency

Install the `tabular` extra. CSV, Markdown, HTML, and text conversion do not need
this extra.

### Import resolves to the repository instead of the installed wheel

Run the verification command from a directory outside the repository, or use a
fresh virtual environment. This detects packaging errors that local source-tree
imports can hide.
