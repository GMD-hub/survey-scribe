# Dependency Compatibility Record

## Selection Policy

Phase 1 uses exact versions in the standalone PEP 723 probe before the project
lock is generated. The probe imports public APIs only and does not download OCR
models, contact providers, or acquire credentials.

| Component | Selected version | Decision |
| --- | --- | --- |
| Pydantic | 2.11.7 | Preserve the characterized v2 serialization contract |
| Instructor | 1.10.0 | Use the maintained public API; do not import `instructor.v2` internals |
| OpenAI SDK | 1.99.9 | OpenAI-compatible and Azure client transports |
| Anthropic SDK | 0.64.0 | Optional provider adapter |
| Docling | 2.54.0 | Local document conversion with `PyPdfiumDocumentBackend` |
| EasyOCR | 1.7.2 | Selected real OCR backend; model artifacts are separately prefetched |
| PyMuPDF | 1.26.4 | Legacy scan characterization only |
| openpyxl | 3.1.5 | Deterministic workbook parsing with formula evaluation disabled |
| tiktoken | 0.11.0 | Token estimation for compatible model families |
| lingua-language-detector | 2.1.1 | Legacy language fallback characterization |
| tenacity | 9.1.2 | Bounded transport retry support |

## License Disposition

| Component | Upstream license | Engineering disposition |
| --- | --- | --- |
| Pydantic | MIT | Allowed for local engineering and build-only CI |
| Instructor | MIT | Allowed for local engineering and build-only CI |
| OpenAI SDK | Apache-2.0 | Allowed for local engineering and build-only CI |
| Anthropic SDK | MIT | Allowed for local engineering and build-only CI |
| Docling | MIT | Allowed for local engineering and build-only CI |
| EasyOCR code | Apache-2.0 | Allowed for local engineering and build-only CI |
| PyMuPDF | AGPL-3.0 or commercial | Characterization only; redistribution/publication requires legal review |
| openpyxl | MIT | Allowed for local engineering and build-only CI |
| tiktoken | MIT | Allowed for local engineering and build-only CI |
| lingua-language-detector | Apache-2.0 | Allowed for local engineering and build-only CI |
| tenacity | Apache-2.0 | Allowed for local engineering and build-only CI |

These records do not authorize package publication. Transitive dependencies and
model weights remain subject to the no-publication gate in
`docs/legal-disposition.md`.

## Compatibility Gate

Run the probe independently of the project and current lock:

```bash
env -u UV_INDEX -u UV_INDEX_URL -u UV_EXTRA_INDEX_URL uv run --no-config --no-project --default-index https://pypi.org/simple --python 3.11 --script scripts/probe_dependencies.py
env -u UV_INDEX -u UV_INDEX_URL -u UV_EXTRA_INDEX_URL uv run --no-config --no-project --default-index https://pypi.org/simple --python 3.12 --script scripts/probe_dependencies.py
env -u UV_INDEX -u UV_INDEX_URL -u UV_EXTRA_INDEX_URL uv run --no-config --no-project --default-index https://pypi.org/simple --python 3.13 --script scripts/probe_dependencies.py
```

PowerShell users must first remove `UV_INDEX`, `UV_INDEX_URL`, and
`UV_EXTRA_INDEX_URL` from `Env:`, then run the same `uv` arguments beginning at
`uv run`. The approved public source for this probe is PyPI. The explicit
`--script` flag prevents cached inline-script environments from selecting a
different interpreter.

All three imports must pass before `uv.lock` is generated. A failure blocks the
package bootstrap until a replacement version is approved.

## OCR Artifacts

The selected English smoke-test bundle is fixed below. Files are fetched from
official EasyOCR GitHub release assets into a local cache and are never committed
or redistributed by this repository.

| Role | File | Release URL | Bytes | SHA-256 | Upstream digest |
| --- | --- | --- | ---: | --- | --- |
| CRAFT detector | `craft_mlt_25k.zip` | `https://github.com/JaidedAI/EasyOCR/releases/download/pre-v1.1.6/craft_mlt_25k.zip` | 77,251,756 | `8dc6a1c703a89ed56308ef742d26ebd45c656248cbbbda6e7fe60e569f873e65` | MD5 `2f8227d2def4037cdb3b34389dcf9ec1` |
| English generation-2 recognizer | `english_g2.zip` | `https://github.com/JaidedAI/EasyOCR/releases/download/v1.3/english_g2.zip` | 14,040,947 | `1b5eaebf1c062de6205560c97ffcfa8dc0e6f413c340e8adc5cfc57e159f61ff` | MD5 `5864788e1821be9e454ec108d61b887d` |

EasyOCR code is Apache-2.0. The release pages do not provide a separate explicit
license grant for these model archives, so their redistribution and public CI
artifact upload remain blocked pending institutional legal approval. Local
technical evaluation may download them into the cache under the limited
engineering authorization. Later OCR setup must verify the SHA-256 values, set
`DOCLING_ARTIFACTS_PATH`, and disable network access before conversion. Import
compatibility is established; real-OCR quality remains later-phase evidence.

## Runtime Boundaries

- `itsai` is not a package dependency.
- Provider and OCR dependencies remain optional extras.
- No client, credential provider, model, or OCR artifact is initialized during
  package import or CLI help.
- Raw provider responses, headers, tokens, and questionnaire text are not
  retained as provenance.

## Locking

`pyproject.toml` is authoritative. `uv.lock` is generated only after the three
interpreter probes pass and is committed for reproducibility.
