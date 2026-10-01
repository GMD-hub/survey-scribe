# Hosting Survey Scribe as a Foundry Agent: What Changed and Why

This branch adds everything required to run Survey Scribe inside a
[Microsoft Foundry hosted agent](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agents):
a containerized service, invoked over the Responses protocol, that downloads
a questionnaire from blob storage, converts it to SVIS, and uploads the
result. None of the pipeline's behavior changed for existing callers; the
changes either add a new deployment surface or fix defects that only surface
in that container environment.

## New files: the agent itself

| File | Purpose |
| --- | --- |
| `azure.yaml` | `azd` project manifest. Declares the Foundry project, the `gpt-5.4-mini` model deployment, and the `survey-scribe-package-agent-v3` hosted agent service (container resources, environment variables, Responses protocol version). |
| `src/survey_scribe/main.py` | Agent entrypoint. Builds a `FoundryChatClient`, registers a single tool (`convert_questionnaire`), and serves it with `ResponsesHostServer`. The tool downloads a named file from the storage container's `input/` folder, runs `SurveyScribe.aconvert`, and uploads SVIS artifacts to `output/`. |
| `src/survey_scribe/Dockerfile` | Multi-stage container build: a build-only stage fetches and checksum-verifies OCR/layout models, and the runtime stage installs `requirements.txt`, copies the package in as `survey_scribe/`, and bakes in the verified model cache. |
| `src/survey_scribe/requirements.txt` | Pinned dependency list for the container image (replaces the old repo-root `requirements.txt`, which was unpinned and intended for local dev only). |
| `src/survey_scribe/fetch_ocr_artifacts.py` | Build-time script run only inside the Dockerfile's `ocr-artifacts` stage. Downloads the approved EasyOCR archives and Docling's layout/TableFormer models, then verifies them against the checksum allowlist so the runtime image never fetches models over the network. |
| `src/survey_scribe/.dockerignore`, `src/survey_scribe/.azdignore` | Keep local virtualenvs, caches, and `.env` files out of the image and out of `azd` deployment packaging. |
| `AGENTS.md` | Repo-level guidance pointing agents/contributors at the `azd ai agent` workflow and the Microsoft Foundry skill. |

### Why a hosted agent needs its own entrypoint and image

Survey Scribe is published as a library (`SurveyScribe` facade, CLI). A
Foundry hosted agent is a long-running HTTP service that Foundry invokes
over the Responses protocol, not a one-shot CLI process. `main.py` adapts the
library to that contract: it exposes exactly one tool call surface
(`convert_questionnaire`), resolves credentials via `DefaultAzureCredential`
instead of interactive config, and treats blob storage as the only I/O
boundary (no local file paths are ever exposed to the agent caller). The
Dockerfile exists because hosted agents are deployed as containers, and the
OCR-artifact pre-fetch stage exists so the deployed container is fully
offline and reproducible — it never calls out to GitHub or Hugging Face at
request time, only at (checksum-verified) build time.

## Modified files: fixes required for the container environment

### `src/survey_scribe/sources/docling.py` — conditional OCR

Added `_pdf_has_text_layer()`, which uses PyMuPDF to sample the first few
pages of a PDF for an existing extractable text layer. `DoclingConverter`
now only forces full-page EasyOCR (`pipeline_options.do_ocr`) when no text
layer is detected.

**Why:** the hosted agent's container is capped at 2 vCPU / 4 GiB
(`azure.yaml`'s `container.resources`). Running EasyOCR unconditionally on
born-digital PDFs — which already have a text layer — routinely exhausted
that memory ceiling and OOM-killed the worker. Skipping OCR when it isn't
needed keeps memory usage within the hosted plan's limits without changing
output for genuinely scanned documents, which still get OCR as before.

### `src/survey_scribe/providers/openai_compatible.py` and `providers/azure.py` — reasoning-model request shape

Added `_max_tokens_param_name()` and `_supports_custom_temperature()`.
Requests to models in the `o1`/`o3`/`o4`/`gpt-5` families now send
`max_completion_tokens` instead of `max_tokens` and omit `temperature`
entirely (these reasoning models reject a non-default temperature).

**Why:** `azure.yaml` provisions the agent against `gpt-5.4-mini`, a
reasoning-family model. The previous request shape (`max_tokens` +
explicit `temperature`) is only valid for non-reasoning chat models and
would be rejected by the API for this deployment.

### `src/survey_scribe/client.py` and `pipeline.py` — error messages for the agent's tool response

Failed-result diagnostics now call the existing `redact_exception()` helper
instead of returning the fixed strings `"Conversion failed."` /
`"Structured conversion failed."`.

**Why:** `main.py`'s `convert_questionnaire` tool returns diagnostic text
directly to the calling agent (and from there, to the end user) because the
hosting framework replaces a raised tool exception with an opaque "Function
failed." message otherwise. A generic string left the user with no actionable
detail; `redact_exception()` gives a specific, still-credential-safe error.

### `src/survey_scribe/__init__.py` — version lookup without installed metadata

`__version__` now falls back to `"0.0.0+unknown"` when
`importlib.metadata.version("survey-scribe")` raises `PackageNotFoundError`.

**Why:** the Dockerfile copies the package source directly into the image
(`COPY . ./survey_scribe/`) rather than `pip install`-ing a built
distribution, so no `dist-info` exists at runtime. Without the fallback,
importing `survey_scribe` in the container raised at startup.

### `pyproject.toml` — exclude the build-only script from the published wheel

Added `exclude = ["src/survey_scribe/fetch_ocr_artifacts.py"]` to the wheel
build target.

**Why:** `fetch_ocr_artifacts.py` imports `ocr` as a flat top-level module
(see its docstring) and is only ever run inside the Dockerfile's
`ocr-artifacts` build stage. It is not valid to import as part of the
installed `survey_scribe` package and must not ship in the published wheel.

### Root `requirements.txt` removed

Deleted in favor of `src/survey_scribe/requirements.txt`, which is now the
single pinned dependency list the container installs, plus the
hosted-agent-only dependencies (`azure-ai-agentserver-responses`,
`agent-framework-foundry`, `agent-framework-foundry-hosting`, `debugpy`,
`azure-storage-blob`) that the library itself does not need.
