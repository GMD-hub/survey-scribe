# Installation

Survey Scribe supports CPython 3.11, 3.12, and 3.13 on Linux, macOS, and Windows.
Use a virtual environment so that optional document libraries do not affect other
projects.

## Release and publication status

Survey Scribe is alpha software. The repository declares version `0.1.0`, but no
approved PyPI release is currently available. Production deployments must use an
approved wheel, Conda artifact, or pinned source revision.

## Install an approved wheel

Build the repository revision in a controlled build environment:

```console
uv build
python -m pip install dist/survey_scribe-0.1.0-py3-none-any.whl
```

Do not use an artifact from an untrusted pull request or local directory. Record
the source commit and wheel digest in your deployment manifest.

The base installation contains Pydantic, `defusedxml`, the typed package, and the
CLI. It does not load provider SDKs, OCR models, or document converters at import
time.

## Future package-index installation

After publication approval and release verification, package-index installation
will use:

```console
python -m pip install survey-scribe
```

Do not use this command until your approved package index contains the release.

## Install optional features

Install only the extras that your application uses.

| Extra | Adds | Command |
| --- | --- | --- |
| `pdf` | Docling, EasyOCR, language detection, and PDF support | `python -m pip install "survey-scribe[pdf]"` |
| `tabular` | XLSX support through openpyxl | `python -m pip install "survey-scribe[tabular]"` |
| `openai` | OpenAI-compatible SDK dependencies for downstream integrations | `python -m pip install "survey-scribe[openai]"` |
| `anthropic` | Anthropic SDK dependencies for downstream integrations | `python -m pip install "survey-scribe[anthropic]"` |

The base package includes the extraction client and command. The OpenAI and
Anthropic extras add the SDKs used by their provider adapters.

Multiple extras can be installed together:

```console
python -m pip install "survey-scribe[pdf,tabular]"
```

## Install from Git

Use a tagged revision or commit hash for reproducible deployments:

```console
APPROVED_COMMIT="<full-reviewed-commit-sha>"
python -m pip install \
  "survey-scribe @ git+https://github.com/GMD-hub/survey-scribe.git@${APPROVED_COMMIT}"
```

Avoid an unpinned branch URL in production.
Replace the placeholder with the full commit SHA that your deployment review
approved.

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

The last command prints `SurveySVIS`. The installed command also provides
`convert`, `batch`, `providers`, `config check`, and `schema export`.

For hosted deployments, also review [Palantir Foundry](../platforms/palantir-foundry.md),
[Microsoft Foundry](../platforms/microsoft-foundry.md), and
[mAI Factory](../integrations/mai-factory.md).

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
