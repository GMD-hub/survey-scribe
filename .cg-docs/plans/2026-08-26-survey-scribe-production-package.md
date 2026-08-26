---
date: 2026-08-26
title: "Survey Scribe Production Python Package"
status: active
scope: "Deep"
brainstorm: "../brainstorms/2026-08-26-survey-scribe-production-package.md"
language: "Python"
estimated-effort: "large"
deviation-policy: "ask"
artifact-schema-version: 1
phases: 6
completed-phases: [1]
current-phase: 2
execution-report: "../work-reports/2026-08-26-survey-scribe-production-package.md"
tags: [python, packaging, architecture, llm, docling, svis, providers, testing, documentation]
---

# Plan: Survey Scribe Production Python Package

## Objective

Refactor the current questionnaire-to-SVIS proof-of-concept into an installable, typed, local-first `survey-scribe` engineering release candidate. The finished repository will expose SVIS-first sync/async Python APIs and a CLI, support BYOK provider and questionnaire-source adapters, preserve the legacy SVIS JSON contract and selected entry points, enforce deterministic quality/status rules, and include executed local and remote CI evidence plus publishable documentation.

Public publication is not part of this plan's completion outcome. License text, open-source terminology, contribution acceptance, PyPI publication, and GitHub Pages publication require explicit legal and release authorization and a separate authorized release decision. A legal blocker is evidence of non-authorization, never passing release evidence.

## Context

The approved brainstorm selected a ports-and-adapters modular package rather than a plugin microkernel or a third-party provider router. The package remains one distribution in v1, with optional provider extras and extension protocols that can support later ecosystem packages.

Current implementation constraints:

- `docling_pipeline.py` synchronously orchestrates conversion, extraction, and file writes and returns no result.
- `agents/svis_agent.py` imports `itsai`, creates a World Bank Azure/Instructor client at import time, and hardcodes endpoint/model/retry settings.
- `extractors/docling_pdf.py` enables Docling OCR but skips detected scans, drops preamble/short sections, and sets every page reference to zero.
- `schemas/svis.py` is the downstream JSON contract, but quality rules described in comments are not deterministic validators.
- `tests/test_schema.py` covers model construction and serialization only.
- Packaging metadata, console entry points, provider/source contract tests, release workflows, and a maintained documentation site do not exist.
- No `compound-gpid.md` or `compound-gpid.local.md` exists, so charter Objective/Constraints/Current Focus alignment cannot be verified; no prior solution artifacts exist. `roadmap.json` exists for future extensions but does not currently link this production-package plan.
- The GitHub repository is already public and has no approved license metadata in the working tree, making repository visibility, copyright ownership, contributor provenance, and permission for continued public development an immediate Phase 1 legal-exposure gate.

## Requirements

| ID | Requirement | Source |
|----|-------------|--------|
| R1 | Provide a top-level SVIS-first `SurveyScribe` API with sync, async, and batch conversion | Brainstorm: Product Purpose/Public API |
| R2 | Return a frozen typed `ExtractionResult[T]` envelope with immutable result-owned collections and `success`, `partial`, and `failed` semantics; caller-supplied `T` need not be deeply immutable | Brainstorm: Public API/Failure Behavior; plan review P2.7 |
| R3 | Preserve the current main SVIS JSON field structure, root CLI shape, and `run(Path, Path) -> None` through 1.x | Brainstorm: Public API/Schema and Validation |
| R4 | Make OpenAI-compatible model, key, and optional base URL the simplest BYOK route | Brainstorm: Provider Flexibility |
| R5 | Support Azure OpenAI/Foundry, Anthropic, OpenRouter, Vercel Gateway, custom gateways, and injected World Bank token providers through normalized adapters | Brainstorm: Provider Flexibility |
| R6 | Support Tier 1 digital/scanned PDF, DOCX, XLSX, CSV, HTML, Markdown, and text with fixture-backed provenance | Brainstorm: Input Formats |
| R7 | Support XLSForm in core delivery and add Survey Solutions only after sanitized versioned fixtures define the supported export contract | Brainstorm: Input Formats; plan review P1.3 |
| R8 | Provide typed Python and TOML configuration for models, generation, retries, concurrency, validation, and artifacts without persisted secrets | Brainstorm: Configuration |
| R9 | Keep SVIS canonical; support document-level custom Pydantic extraction and chunked custom extraction only with a caller-supplied reducer | Brainstorm: Product Purpose/Schema and Validation; plan review P1.2 |
| R10 | Apply deterministic review, reconciliation, failure, retry, redaction, and atomic artifact policies | Brainstorm: Schema and Validation/Failure Behavior |
| R11 | Use `pyproject.toml`, `src/` layout, Hatchling, `uv`, `py.typed`, Ruff, Pyright, pytest, and Python 3.11-3.13 | Brainstorm: Packaging, Documentation, and Website |
| R12 | Provide unit, source/provider contract, integration, CLI, compatibility, package, browser/docs, security, and golden-quality tests, with local phase evidence separated from authorized remote CI evidence | Brainstorm: Packaging; plan review P1.6 |
| R13 | Publish-ready MkDocs Material documentation must cover API, CLI, providers, sources, configuration, schemas, migration, security, and quality | Brainstorm: Packaging, Documentation, and Website |
| R14 | Provide a static curated-sample playground with no uploads, keys, or live inference | Brainstorm: Packaging, Documentation, and Website |
| R15 | Keep runtime local-first with no hosted API, managed credentials, telemetry, or multi-tenant infrastructure | Brainstorm: Product Purpose |
| R16 | Track extraction completeness and quality separately, including dense repeated-table recall | README model-quality findings; brainstorm Devil's Advocate |
| R17 | Immediately record the legal disposition of the already-public repository and block pushes, public artifacts, publication workflows, release, and open-source claims until authorized | Brainstorm: Licensing; plan review P1.4/P1.5 |
| R18 | Enforce untrusted-document resource, archive, path, external-reference, formula/macro, remote-service, and prompt-injection controls | Plan review P2.8 |

## Normative Runtime Contracts

These decisions are implementation authority. Changes require approval under `deviation-policy: ask`.

### Compatibility Contract

- Legacy JSON compatibility means exact key names, nesting, JSON value types, enum values, null/default serialization, and variable ordering, evaluated with a fixed clock. Whitespace and indentation are not contractual.
- Value-level corrections are allowed only when listed in `tests/fixtures/legacy/intentional-corrections.toml`; the initial list covers deterministic `needs_review`, real page provenance, scan processing, and explicit partial diagnostics.
- The root command retains `python docling_pipeline.py INPUT [--output-dir DIR]`; `run(Path, Path) -> None` still returns `None` through 1.x.
- The legacy shim discovers `./survey-scribe.toml` only, then environment configuration. It never restores import-time World Bank credentials. Missing configuration produces one actionable migration error rather than silently selecting a provider.
- The legacy invocation matrix must define warning, exit, exception, scan, no-content, output filename, overwrite, and partial-result behavior explicitly.

### Public SDK Contract

```python
LocalSource = str | os.PathLike[str]

class SourceBundle:
    root: Path
    primary: Path
    companions: tuple[Path, ...]

class SurveyScribe:
    def convert(self, source: LocalSource | SourceBundle) -> ExtractionResult[SurveySVIS]: ...
    async def aconvert(self, source: LocalSource | SourceBundle) -> ExtractionResult[SurveySVIS]: ...
    def convert_many(self, sources: Iterable[LocalSource | SourceBundle]) -> list[ExtractionResult[SurveySVIS]]: ...
    async def aconvert_many(self, sources: Iterable[LocalSource | SourceBundle]) -> list[ExtractionResult[SurveySVIS]]: ...
    def close(self) -> None: ...
    async def aclose(self) -> None: ...

class StructuredPipeline[T]:
    # One document-level model call; fail before calling if the normalized input exceeds the model limit.
    ...

class ChunkedStructuredPipeline[TChunk, TResult]:
    # Requires reducer: Callable[[tuple[ProviderResponse[TChunk], ...]], TResult].
    ...
```

- V1 accepts local paths and explicit local bundles only. Bytes, arbitrary file objects, and URLs are rejected.
- Invalid constructor/configuration/programmer inputs raise typed exceptions before conversion. Source/provider/runtime failures return `ExtractionResult(status="failed")`. `asyncio.CancelledError`, `KeyboardInterrupt`, and `SystemExit` propagate.
- Batch methods return one result per input in input order and share the configured global concurrency ceiling.
- `SurveyScribe` supports sync/async context managers and explicit close methods. The sync facade rejects use inside a running event loop.
- Conversion has no write side effect. `result.write(output_dir, *, sidecar=True, overwrite=False) -> ExtractionResult[T]` returns a new frozen envelope with artifact references and never mutates the original. It raises typed `ArtifactWriteError` or `ArtifactCollisionError`; the CLI catches these and applies the command-outcome table.
- A chunked custom reducer receives stable source-order successful responses plus failed-block diagnostics. Reducer failure returns `failed`; an empty successful response tuple is passed to the reducer; `allow_partial=False` prevents reducer invocation when any block fails.

### Configuration Precedence

| Rank | CLI | Python SDK |
| --- | --- | --- |
| 1 | Explicit CLI flags and non-echo credential prompt | Explicit constructor arguments |
| 2 | `SURVEY_SCRIBE_*` environment variables | Explicit `SurveyScribeConfig` values |
| 3 | Provider-standard environment variables | `SURVEY_SCRIBE_*`, then provider-standard environment variables when `resolve_environment=True` |
| 4 | Explicit `--config PATH` | Explicitly requested TOML path |
| 5 | `./survey-scribe.toml` only | No implicit TOML unless `from_config()` is used |
| 6 | Package defaults | Package defaults |

- Do not search parent or home directories.
- Supported provider variables include `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `AI_GATEWAY_API_KEY`, `ANTHROPIC_API_KEY`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_VERSION`, and `AZURE_OPENAI_DEPLOYMENT`.
- `SURVEY_SCRIBE_API_KEY`, `SURVEY_SCRIBE_MODEL`, `SURVEY_SCRIBE_BASE_URL`, and `SURVEY_SCRIBE_PROVIDER` are generic overrides.
- Simultaneous key, bearer token, and token-callback configuration is an error unless the selected adapter documents one unambiguous precedence. Config serialization always omits secret values.

### Provider Response and Capability Contract

```python
class ProviderResponse[T]:
    output: T
    usage: NormalizedUsage | None
    finish_reason: str | None
    provider: str
    model: str
    response_id: str | None
    transport_attempts: int
    validation_attempts: int
```

- `StructuredProvider.generate()` returns `ProviderResponse[T]`, not bare `T`.
- Raw response bodies, headers, and tokens are never retained in provenance.
- `ModelCapabilities` records structured-output support, token estimator, input/output limits, temperature/seed support, and whether behavior is verified, configuration-only, or unknown.
- Claims apply to adapter protocols and named tested model/version rows, not every model sold by a provider or gateway. Unknown explicit settings fail closed.
- Truncation/length finish reasons cannot be treated as complete structured output.

### Default Quality Action Table

| Condition | Diagnostic/action | `needs_review` | Extraction status |
| --- | --- | --- | --- |
| Confidence below threshold | `QUALITY_LOW_CONFIDENCE`; no field mutation except review flag | true | unchanged |
| Categorical variable lacks categories | `QUALITY_MISSING_CATEGORIES`; retain record | true | unchanged unless provider output is structurally invalid |
| Numeric range has min greater than max | Pydantic validation retry; failed block after exhaustion | n/a | partial if other usable blocks exist |
| Same raw name on distinct questions | `QUALITY_DUPLICATE_RAW_NAME`; retain both, never silently rename/merge | true for affected records | unchanged |
| Exact normalized question repeated solely by overlapping source blocks | Remove later duplicate by stable source/block order; `QUALITY_OVERLAP_DEDUPED` | unchanged | unchanged |
| Similar question without exact overlap proof | Retain both; `QUALITY_POSSIBLE_DUPLICATE` | true | unchanged |
| Model module conflicts with authoritative source section | Source section wins; `QUALITY_MODULE_RECONCILED` | true | unchanged |
| Placeholder/missing required metadata | Keep legacy-compatible placeholder; `METADATA_INCOMPLETE` | affected records unchanged | partial |
| Unreadable page or omitted failed block | Record source/block diagnostic; do not fabricate output | affected records true where applicable | partial |

CLI `--strict` concerns partial execution, not review warnings. Quality severities may be configured, but changing the default action table is a public-policy deviation.

### Artifact and Command Outcome Contract

- Main JSON, sidecar, and manifest are written into an immutable run-specific directory keyed by run ID. Validate/fsync that generation, then atomically replace one small active-generation pointer; never overwrite files in the active generation.
- The stable legacy `<survey_id>_svis.json` is a separately staged and atomically replaced compatibility projection of the completed immutable generation. Run-aware readers use the active pointer and immutable generation, so a projection or pointer failure cannot corrupt the prior active artifact set.
- Default `overwrite=False`. `overwrite=True` permits a new immutable generation and compatibility projection but never mutates the prior generation. Concurrent identical survey IDs use an exclusive lock and return a typed collision error rather than interleaving files.
- Any required main/sidecar/manifest write failure is an artifact failure and exits nonzero, regardless of extraction status.
- Single default CLI: success `0`, partial `0`, failed/artifact failure nonzero. Single strict CLI: success `0`, partial/failed/artifact failure nonzero.
- Batch default CLI exits nonzero if any input fails or has an artifact failure; partial-only batches exit `0`. Batch strict exits nonzero if any input is partial, failed, or has an artifact failure.

### Untrusted-Document and OCR Contract

- Configurable defaults: 250 MB source, 2,000 pages, 1 GB archive expansion, 100:1 archive ratio, 2,000,000 tabular cells, 100 companion files, and 30-minute source-conversion deadline.
- Never execute formulas, macros, embedded scripts, or external relationships. HTML remote resources are ignored. Bundle companions must resolve inside `SourceBundle.root` after symlink resolution.
- Disable Docling remote services. Questionnaire text is untrusted data in fixed system instructions; extraction calls have no tools.
- Selected real OCR path is Docling's EasyOCR backend with package and model artifacts pinned by the dependency compatibility record. Prefetch artifacts in an explicit CI setup job, verify checksums, set `DOCLING_ARTIFACTS_PATH`, then block network for tests.
- Run real OCR on a designated Linux/Python 3.12 job and a local smoke fixture; use deterministic fakes for the full OS/Python matrix. Document model license, cache size, first-run, and fully offline setup.
- Run Docling conversion in a killable worker process, not a thread. On deadline, terminate and join the worker, recreate it before accepting new work, and emit a timeout diagnostic. Reserve thread offload for parsers with cooperative cancellation.
- The dependency compatibility record must select and constrain Instructor API mode, OpenAI/Anthropic SDKs, Docling/EasyOCR, `openpyxl`, and `tiktoken`. Use provider-specific token estimators when available and a conservative documented fallback. Generate the final lock only after Python 3.11-3.13 import probes pass.

## Dependency Graph

| Phase | Depends on | Unlocks |
| --- | --- | --- |
| 1. Legal/dependency/compatibility foundation | Approved plan | All implementation phases |
| 2. Runtime and source foundation | Phase 1 package/import boundaries | Provider and pipeline implementation |
| 3. Providers and orchestration | Phase 2 config/results/source contracts | Public API and compatibility migration |
| 4. Public API and core format completion | Phases 2-3 | CLI, full evaluation, and docs examples |
| 5. Delivery and evidence | Phases 1-4; does not depend on Survey Solutions fixtures | Engineering release-candidate decision |
| 6. External-gated integration and release hardening | Phase 5 evidence; sanitized Survey Solutions fixtures for that adapter | Final engineering readiness; a separate authorized publication decision |

Phases are sequential at their gates. Within Phase 2, result/config work may proceed alongside source fixture preparation. Within Phase 5, CI and documentation may proceed in parallel after the public API stabilizes.

## Phase 1: Legal, Dependency, and Compatibility Foundation

### 1. Resolve Immediate Legal Exposure, Fixture Rights, and Dependency Decisions

- **Requirements**: R3, R10, R16, R17, R18
- **Files**: `docs/legal-disposition.md`, `docs/dependencies.md`, `docs/compatibility.md`, `docs/evaluation.md`, `scripts/probe_dependencies.py`, `scripts/validate_golden_manifest.py`, `tests/fixtures/golden/manifest.toml`, `tests/fixtures/golden/quality-thresholds.toml`, `tests/fixtures/legacy/intentional-corrections.toml`
- **Details**: Record current GitHub visibility, repository/license state, copyright ownership, accepted-contribution provenance, whether continued local implementation is permitted, and whether the repository must become private. Until disposition is approved, prohibit pushes, public CI artifacts, samples, publication workflows, and release claims. Inventory candidate source/output fixtures and record rights, checksums, restrictions, expected variable inventory, field judgments, provider/model/prompt versions, and numeric pass thresholds before use. Synthetic fixtures may test deterministic mechanics but cannot substantiate historical dense-table quality. Run a dependency/OCR compatibility spike before the final lock: select constrained Instructor API mode, OpenAI/Anthropic SDKs, Docling/EasyOCR and model bundle, `openpyxl`, and `tiktoken`; record licenses, cache size, Python/OS support, and minimal 3.11-3.13 import probes. `scripts/probe_dependencies.py` and `scripts/validate_golden_manifest.py` must contain pinned PEP 723 dependencies and run with `uv run --no-project`, isolating them from the current unusable lock/project state. Finalize the compatibility and default quality action tables in this plan as executable fixture policy.
- **Test Scenarios**: Public repository with no license; contributor with unclear provenance; prohibited fixture; checksum drift; missing real corpus; Python-version import failure; Docling/OCR model-license incompatibility; threshold file missing a required metric.
- **Tests**: `gh repo view --json visibility,owner,name`; repository history/contributor inventory artifact; `uv run --no-project --python 3.11 scripts/probe_dependencies.py`, repeated for 3.12 and 3.13; `uv run --no-project --script scripts/validate_golden_manifest.py` with its PEP 723 dependencies.
- **Acceptance criteria**: A written disposition explicitly permits or blocks local development and public pushes; every planned fixture has a rights/checksum record; dependency/OCR choices and quality thresholds are fixed before package locking. If continued development authorization is absent, `/cg-work` stops before Step 2.

### 2. Bootstrap Packaging, Move the Unchanged Schema, and Capture Characterization

- **Requirements**: R3, R11, R12, R15, R16
- **Files**: `pyproject.toml`, `uv.lock`, `.python-version`, `.gitignore`, `src/survey_scribe/__init__.py`, `src/survey_scribe/py.typed`, `src/survey_scribe/models/svis.py`, `src/survey_scribe/cli.py`, `tests/conftest.py`, `tests/characterization/`, `tests/fixtures/legacy/`, `tests/package/test_clean_install.py`, `.github/workflows/ci.yml`
- **Details**: First add the minimal Hatchling/uv test harness using the dependencies selected in Step 1; do not move runtime orchestration yet. Move the unchanged SVIS models into the wheel immediately and update schema tests to use the packaged path. A temporary root `schemas/svis.py` re-export is allowed only until Step 7 cleanup. Stub `itsai`, token/client creation, Docling calls, and provider calls in characterization `conftest.py` before importing legacy modules; record the exact legacy commit/dependency context. Capture representative `SurveySVIS.model_dump_json()` output, `run()` return, root CLI arguments, metadata reconciliation, scan/no-content behavior, partial chunk behavior, output naming/overwrite, and fixed-clock serialization. Keep value-level intentional corrections in the approved exceptions file. Then complete distribution metadata, console entry point, dependency groups/extras, Ruff, Pyright, pytest/pytest-asyncio, coverage, MkDocs tools, and build checks. Configure temporary Phase 1 Pyright scope to include only `src/` and migrated tests while excluding the current root script and legacy `agents/`, `extractors/`, and `schemas/`; characterization tests, not static analysis, guard those frozen legacy files. Step 7 must remove all exclusions and type-check the final root shim. Phase-local evidence is local build/import only; remote OS CI is final evidence after an authorized commit/push.
- **Test Scenarios**: Legacy module imports with stubs; exact schema key/type/default comparison; fixed extraction date; missing provider extras; missing credentials; network blocked; wheel/sdist install on locally available interpreters; CLI help without `itsai`.
- **Tests**: `uv run pytest tests/characterization tests/test_schema.py`; `uv lock --check`; `uv build`; `uv run pytest tests/package/test_clean_install.py`; `uv run ruff check .`; `uv run pyright`
- **Acceptance criteria**: Characterization runs after a valid bootstrap, not before it. `test_clean_install.py` creates a temporary uv environment, installs the built wheel with locked cached dependencies, and invokes package import plus installed CLI help without network, credentials, or `itsai`. No cross-platform CI claim is made yet.

## Phase 2: Runtime and Source Foundation

### 3. Implement Configuration, Results, Errors, and Artifact Writing

- **Requirements**: R2, R8, R10, R15
- **Files**: `src/survey_scribe/config.py`, `src/survey_scribe/results.py`, `src/survey_scribe/errors.py`, `src/survey_scribe/serialization/legacy.py`, `src/survey_scribe/serialization/artifacts.py`, `tests/unit/test_config.py`, `tests/unit/test_results.py`, `tests/unit/test_artifacts.py`
- **Details**: Implement the normative precedence matrix without parent/home TOML search and reject ambiguous credential forms. Define normalized exceptions and stable diagnostic codes. Implement a frozen generic result envelope whose owned diagnostics/failed-block/artifact collections are tuples; document that caller `T` may remain mutable and offer a serialization snapshot where needed. Separate conversion from writing. Implement `result.write() -> new result`, typed write/collision exceptions, immutable run-specific generations, atomic active pointer, separate atomic legacy projection, exclusive per-survey lock, and explicit overwrite policy. Redact keys, auth headers, endpoint query secrets, and questionnaire text from normal logs/errors.
- **Test Scenarios**: Every precedence rank; simultaneous key/token/callback; missing key variable; unknown TOML key; parent config ignored; invalid URL/threshold/concurrency; unsupported config version; outer-envelope reassignment and tuple mutation; nested `T` mutability disclaimer; `result.write()` returns a new envelope and leaves the original unchanged; typed write/collision failures; status derivation; concurrent identical IDs; failure during immutable generation/projection/pointer replacement; stale/mismatched pointer; malicious survey ID; nested-exception redaction.
- **Tests**: `uv run pytest tests/unit/test_config.py tests/unit/test_results.py tests/unit/test_artifacts.py`
- **Acceptance criteria**: One deterministic config object reaches the application layer; status and diagnostics are stable; no secret is serializable; failed writes preserve prior valid artifacts.

### 4. Build the Source Port and Tier 1 Adapters

- **Requirements**: R6, R10, R16, R18
- **Files**: `src/survey_scribe/sources/base.py`, `src/survey_scribe/sources/registry.py`, `src/survey_scribe/sources/docling.py`, `src/survey_scribe/sources/tabular.py`, `src/survey_scribe/chunking.py`, `scripts/validate_ocr_artifacts.py`, `tests/contract/sources/`, `tests/integration/test_tier1_sources.py`, `tests/fixtures/sources/`
- **Details**: Implement only local paths and confined `SourceBundle` inputs. Enforce the normative file/page/archive/cell/companion/deadline limits before expensive work. Disable remote resources/services, macro/formula execution, external relationships, and companion path escape. Port Docling with the existing `PyPdfiumDocumentBackend`, selected EasyOCR backend, pinned/prefetched checksummed artifacts, and offline `DOCLING_ARTIFACTS_PATH`. Run Docling in a killable worker process and terminate/join/recreate it on deadline; use threads only for cooperatively cancellable parsers. Stop skipping scans and record coverage/quality warnings. Preserve preamble/short content and actual provenance. Implement DOCX/HTML/Markdown/text and deterministic `openpyxl`/CSV paths. Add `tiktoken`/adapter estimator abstraction, conservative fallback, table-boundary splitting, overlap, repeated-row inventory, and prompt-injection isolation. Real OCR runs only in the designated job; fakes cover the full matrix.
- **Test Scenarios**: Digital/scanned/mixed PDF; absent/corrupt OCR cache; network blocked after prefetch; malformed/encrypted/oversized PDF; archive bomb/ratio; DOCX external relationship; HTML remote asset; XLSX macro/formula; symlink/path escape; cell/page/deadline limit; prompt injection; sparse pages; no headings; dense/multilingual table; unsupported/ambiguous format.
- **Tests**: `uv run python scripts/validate_ocr_artifacts.py`; `uv run pytest tests/contract/sources tests/integration/test_tier1_sources.py`
- **Acceptance criteria**: Every Tier 1 format produces the normalized representation with deterministic ordering and available page/sheet/row provenance; failures use diagnostics rather than `print()` or silent drops.

## Phase 3: Providers and Orchestration

### 5. Implement the Structured Provider Port and Adapters

- **Requirements**: R4, R5, R8, R10, R15
- **Files**: `src/survey_scribe/providers/base.py`, `src/survey_scribe/providers/capabilities.py`, `src/survey_scribe/providers/openai_compatible.py`, `src/survey_scribe/providers/azure.py`, `src/survey_scribe/providers/anthropic.py`, `tests/contract/providers/`, `tests/fakes/providers.py`, `docs/providers/capabilities.md`
- **Details**: Implement `StructuredProvider.generate(...) -> ProviderResponse[T]` and `ModelCapabilities` exactly as the normative contract. Keep Instructor/raw SDK responses internal while retaining normalized usage, finish reason, provider/model identity, response ID, and attempt counts. Implement the OpenAI-compatible adapter and configuration presets; add Azure key/token and optional Anthropic adapters. Claims apply to named tested representative model/version rows; custom or unverified presets are configuration-only until authorized smoke evidence exists. Fail closed on explicit unsupported/unknown settings and truncation. Prefer OpenAI compatibility for Foundry; add `azure-ai-inference` only after an approved deviation backed by fixtures. Document but never import `itsai`; inject token callbacks. Classify retryable/non-retryable failures, bound backoff, and propagate cancellation.
- **Test Scenarios**: Each credential source; custom base URL; extra-header allowlist; named tested model; configuration-only preset; unknown capability; unsupported temperature/seed; truncation finish reason; 401/403; 429 retry then success/exhaustion; timeout/5xx; malformed structured response; validation retry; cancellation during backoff; token refresh callback; error redaction.
- **Tests**: `uv run pytest tests/contract/providers`
- **Acceptance criteria**: Every advertised adapter and named tested model row passes the applicable contract; unverified presets are labeled configuration-only; application/core modules import no SDK/Instructor/`itsai` types; pull-request tests require no live keys.

### 6. Rebuild Extraction as an Async, Deterministic Pipeline

- **Requirements**: R1, R2, R9, R10, R16
- **Files**: `src/survey_scribe/pipeline.py`, `src/survey_scribe/models/svis.py`, `src/survey_scribe/models/quality.py`, `src/survey_scribe/prompts/metadata.py`, `src/survey_scribe/prompts/variables.py`, `src/survey_scribe/prompts/versions.py`, `tests/integration/test_pipeline.py`, `tests/unit/test_quality.py`
- **Details**: Use the packaged SVIS model from Step 2 and version prompts/quality policy separately. Implement metadata extraction, reconciliation, bounded concurrency, stable ordering, cancellation, retry propagation, finish-reason/truncation handling, and failed-block collection. Implement every row of the default quality action table without inventing additional mutation. Exact overlap deduplication must use normalized content plus overlapping provenance; possible duplicates remain and are flagged. Low confidence remains a review state, while missing metadata, unreadable regions, truncation, or failed blocks make a result partial. The sync facade rejects a running event loop.
- **Test Scenarios**: Complete conversion; metadata fallback; one/all blocks fail; out-of-order async completion; concurrency ceiling; cancellation; duplicate names; repeated overlap; categorical variable without categories; confidence 0.69/0.70; unreadable OCR pages; dense repeated rows; running event loop.
- **Tests**: `uv run pytest tests/integration/test_pipeline.py tests/unit/test_quality.py`
- **Acceptance criteria**: Pipeline behavior is deterministic under fake providers; no source/provider SDK coupling crosses the ports; all status and review rules have boundary tests.

## Phase 4: Public API and Core Format Completion

### 7. Publish the SVIS-First API, Custom Pipeline, and Compatibility Shims

- **Requirements**: R1, R2, R3, R9
- **Files**: `src/survey_scribe/client.py`, `src/survey_scribe/__init__.py`, `src/survey_scribe/pipeline.py`, `docling_pipeline.py`, legacy `agents/`, `extractors/`, and `schemas/`, `tests/integration/test_public_api.py`, `tests/compat/`, `tests/architecture/`
- **Details**: Implement the normative signatures, local input limits, raise-versus-result policy, cancellation, batch ordering/concurrency, lifecycle methods, and `result.write()` new-envelope/typed-exception behavior. `SurveyScribe` always returns SVIS. `StructuredPipeline[T]` performs one bounded document-level call; `ChunkedStructuredPipeline[TChunk, TResult]` requires a reducer and defines empty/partial/reducer-failure behavior. Convert root `docling_pipeline.py` to the only required lazy deprecated shim. Update imports/tests, then remove obsolete `agents/`, `extractors/`, and `schemas/` modules or retain only explicitly approved thin re-exports. Remove temporary Pyright exclusions and type-check the final root shim plus complete package. Assert no runtime file imports `itsai`, contains the development endpoint, constructs a client at import, or uses `print()` for runtime logging.
- **Test Scenarios**: Five-line usage; context manager and close; local path/bundle accepted; bytes/file/URL rejected; constructor error raises; operational error returns failed; cancellation propagates; sync/async parity; batch ordering/global ceiling; custom document token overflow; chunk reducer success/failure/empty/partial; legacy CLI/run; missing config migration; warning once; exact compatibility matrix; unsafe legacy code absent.
- **Tests**: `uv run pytest tests/integration/test_public_api.py tests/compat`
- **Acceptance criteria**: Typed public examples pass Pyright; old selected entry points work without import-time auth; custom models do not invoke SVIS-specific reconciliation unless supplied.

### 8. Add the Core XLSForm Adapter

- **Requirements**: R7, R10, R16, R18
- **Files**: `src/survey_scribe/sources/xlsform.py`, `tests/contract/sources/test_xlsform.py`, `tests/fixtures/sources/xlsform/`, `docs/sources/xlsform.md`
- **Details**: Parse supported XLSForm `survey`, `choices`, and `settings` sheets deterministically, preserving names, labels, groups, repeats, relevance, constraints, calculations, and choice references. Confine external-choice companions to the bundle root, apply archive/cell/companion limits, never evaluate formulas/macros, and diagnose unsupported features. Allow LLM enrichment without replacing native names/logic. Survey Solutions is not a dependency of this phase or Phase 5 and is handled only in external-gated Step 12.
- **Test Scenarios**: Multilingual labels; groups/repeats; confined external choices; path escape; relevance/constraints; malformed/oversized workbook; formulas/macros; unsupported question type; missing choice link; deterministic ordering.
- **Tests**: `uv run pytest tests/contract/sources/test_xlsform.py`
- **Acceptance criteria**: The XLSForm support matrix names exact tested features and diagnostics; no Survey Solutions support is claimed by core delivery.

## Phase 5: Delivery and Evidence

### 9. Complete the CLI and Migration Experience

- **Requirements**: R1, R2, R3, R8, R10
- **Files**: `src/survey_scribe/cli.py`, `tests/cli/`, `docs/cli.md`, `docs/migration.md`, `.vscode/tasks.json`, `.github/copilot-instructions.md`, `README.md`, `docs/pipeline_overview.md`
- **Details**: Implement `convert`, `batch`, `providers`, `config check`, and `schema export` using stdlib `argparse` over the public API. Keep secrets in environment variables or non-echo input. Enforce the normative single/batch extraction-plus-artifact outcome table, shared run manifest, collision/overwrite policy, and strict behavior. Print concise status, paths, diagnostics, and failed-block counts. Write sidecars/manifests by default; `--no-sidecar` is allowed only when the main result is successful and must be rejected for partial output. Add resume only after source-digest/checkpoint integrity exists. Update/remove all stale commands/provider guidance.
- **Test Scenarios**: Each subcommand; config precedence; missing/unsupported input; success/partial/failed; failure at each artifact stage; manifest mismatch; strict partial; rejected partial `--no-sidecar`; overwrite/collision; batch combinations and aggregate exits; redacted provider failure; installed and old script invocation.
- **Tests**: `uv run pytest tests/cli tests/compat/test_legacy_cli.py`
- **Acceptance criteria**: CLI behavior is fully executable in tests; docs and editor tasks reference existing paths/commands only; no credential appears in process output.

### 10. Build Cross-Platform CI and the Quality Evaluation Harness

- **Requirements**: R11, R12, R16
- **Files**: `tests/`, `tests/fixtures/`, `tests/golden/`, `tests/security/test_workflow_policy.py`, `scripts/evaluate_quality.py`, `scripts/validate_golden_manifest.py`, `scripts/run_security_gates.py`, `scripts/check_workflow_policy.py`, `security/allowlist.toml`, `.secrets.baseline`, `.github/workflows/ci.yml`, `.github/workflows/provider-smoke.yml`, `docs/evaluation.md`
- **Details**: Organize unit, contract, integration, CLI, compatibility, architecture, package, browser/docs, security, and golden suites. Use fake providers/recorded synthetic payloads in pull requests and block network after explicit OCR setup. Evaluate against the approved manifest and thresholds. `scripts/run_security_gates.py collect` invokes pip-audit, Bandit, and detect-secrets itself, captures machine-readable reports regardless of each tool's finding exit code, enumerates tracked files portably in Python without `xargs`, and labels the bounded pip-audit collection as network-enabled. `scripts/run_security_gates.py verify` runs network-blocked, validates allowlist owner/rationale/expiry, and is the sole authoritative security-policy exit code. `scripts/check_workflow_policy.py` rejects tag triggers, deploy actions, repository-wide write permissions, and unauthorized `id-token: write`/`pages: write`. Phase 5 workflows are build/test-only with read-only permissions and no publication. Scheduled provider smoke is isolated, one bounded request per preset and at most 10,000 total tokens per run. Phase 5 remote CI is provisional only; final V13 runs after Steps 12-13.
- **Test Scenarios**: Full offline suite; clean wheel installs; no-network enforcement; quality regression threshold; missing optional extra; scheduled smoke without secrets; provider cost ceiling; artifact upload on failure.
- **Tests**: `uv run ruff check .`; `uv run ruff format --check .`; `uv run pyright`; `uv run pytest`; `uv build`; `uv run python scripts/validate_golden_manifest.py`; `uv run python scripts/evaluate_quality.py --manifest tests/fixtures/golden/manifest.toml --thresholds tests/fixtures/golden/quality-thresholds.toml --offline`; network-enabled `uv run python scripts/run_security_gates.py collect --output-dir .cache/security`; network-blocked `uv run python scripts/run_security_gates.py verify --reports .cache/security --allowlist security/allowlist.toml`; `uv run twine check --strict dist/*.whl dist/*.tar.gz`; `uv run check-wheel-contents dist/*.whl`; `uv run cyclonedx-py environment --output-file dist/sbom.cdx.json`; `uv run python scripts/check_workflow_policy.py .github/workflows`
- **Acceptance criteria**: All local checks pass; quality output names each threshold and baseline; build-only workflow permissions are verified. Remote cross-platform success is recorded only after the explicit authorized commit/push/resume gate.

### 11. Build Documentation, Website, and Sample Playground

- **Requirements**: R13, R14, R15
- **Files**: `mkdocs.yml`, `docs/index.md`, `docs/getting-started/`, `docs/api/`, `docs/providers/`, `docs/sources/`, `docs/configuration.md`, `docs/svis/`, `docs/custom-schemas.md`, `docs/security.md`, `docs/playground/`, `tests/docs/`, `tests/browser/`, `.github/workflows/docs.yml`
- **Details**: Build MkDocs Material with mkdocstrings and generated API/config/JSON-Schema references. Provider docs distinguish adapter/protocol support, tested model/version rows, configuration-only presets, and unknown capabilities. Document all normative contracts and limitations. Build a static curated-sample explorer with no upload/key/live-call/storage/backend route. Execute snippets/generated-reference tests under `pytest tests/docs`, required offline internal-link/anchor checks with HTTP(S) URLs ignored, and Chromium keyboard/mobile/network-route assertions with `pytest-playwright`; inject axe-core in browser tests. CI installs cached Chromium explicitly. A separate scheduled network-enabled external-link job uses bounded timeout/retries and is advisory, not completion evidence. The docs workflow is build-only/read-only and uploads a site artifact without Pages deployment.
- **Test Scenarios**: Strict site build; every snippet; generated reference drift; broken links; keyboard-only playground; narrow/mobile viewport; search/navigation; route scan for forms/uploads/network calls; no-secret scan.
- **Tests**: `uv run mkdocs build --strict`; `uv run pytest tests/docs`; `uv run linkchecker --ignore-url='^https?://' site/`; `uv run playwright install chromium`; `uv run pytest tests/browser`; advisory scheduled external-link report
- **Acceptance criteria**: A new user can install, configure, convert, understand partial output, and use a custom Pydantic model using only the site; playground is demonstrably static/sample-only.

## Phase 6: External-Gated Integration and Release Hardening

### 12. Add the Survey Solutions Adapter Only from Approved Fixtures

- **Requirements**: R7, R10, R16, R18
- **Files**: `src/survey_scribe/sources/survey_solutions.py`, `scripts/validate_fixture_manifest.py`, `tests/contract/sources/test_survey_solutions.py`, `tests/fixtures/sources/survey_solutions/manifest.toml`, sanitized fixture files, `docs/sources/survey-solutions.md`
- **Details**: Obtain sanitized exports with rights/checksum records and define the exact Survey Solutions artifact/version before implementation. Map supported sections, rosters, questions, categories, conditions, identifiers, and companion files without remote access or path escape. Emit stable diagnostics for unknown versions and unsupported features; never infer universal support from one fixture. If approved fixtures are unavailable, this step is blocked, but completed Phases 1-5 remain valid and no Survey Solutions support is advertised.
- **Test Scenarios**: Supported version; nested roster; category/condition links; unknown version; unsupported feature; malformed/oversized archive; external path/reference; deterministic order; no restricted data in git.
- **Tests**: `uv run --script scripts/validate_fixture_manifest.py tests/fixtures/sources/survey_solutions/manifest.toml`; `uv run pytest tests/contract/sources/test_survey_solutions.py`
- **Acceptance criteria**: An exact versioned support matrix and tests exist, or the plan remains incomplete at Step 12 with core delivery evidence preserved and no false support claim.

### 13. Complete Engineering Release Readiness

- **Requirements**: R3, R11, R12, R13, R15, R17
- **Files**: `LICENSE.md` only after approval, `NOTICE`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `CHANGELOG.md`, `docs/release-checklist.md`, `scripts/check_workflow_policy.py`, `tests/security/test_workflow_policy.py`, `.github/workflows/release.yml`, package metadata, `dist/`, `dist/sbom.cdx.json`
- **Details**: Complete engineering metadata, support/deprecation policy, security contacts, changelog, SBOM, package checks, and local release-candidate artifacts. Keep the legacy shim through 1.x. Run authorized internal compatibility smoke against the World Bank gateway/downstream consumer with strict redaction. Pause for a user-authorized commit and push, then resume `/cg-work` to attach successful Linux/macOS/Windows Python 3.11-3.13 CI URL evidence. An engineering attestation job may use `actions/attest-build-provenance@v3` with `id-token: write` only after the legal disposition permits public CI artifacts; it must not publish a package. The release workflow remains absent or inert unless legal/release approval exists. If later authorized, publication jobs must be `workflow_dispatch` only, use a protected environment with required approval and checklist verification, and request `id-token: write`/Pages permission only in the isolated publish job. Actual TestPyPI/PyPI/Pages publication belongs to a separate authorized release action and is not required for this engineering plan.
- **Test Scenarios**: Exact wheel metadata/content; SBOM; clean install; downstream compatibility; remote CI resume; missing legal approval; workflow permission scan; no tag/deploy trigger; approved protected manual job; rollback/deprecation notice.
- **Tests**: `uv build`; `uv run twine check --strict dist/*.whl dist/*.tar.gz`; `uv run check-wheel-contents dist/*.whl`; `uv run pytest tests/package/test_clean_install.py`; exact security commands from Step 10; `uv run python scripts/check_workflow_policy.py .github/workflows`; `uv run pytest tests/security/test_workflow_policy.py`; full local Verification Surface; successful authorized final-tree CI run URL; `docs/release-checklist.md`
- **Acceptance criteria**: Engineering release-candidate evidence passes locally and in authorized remote CI. Missing legal authorization prevents publication configuration/claims but is not mislabeled as passing release evidence because public release is outside this plan's outcome.

## Testing Strategy

Use an offline-first pyramid:

| Layer | Purpose | Network policy |
| --- | --- | --- |
| Unit | Config, statuses, diagnostics, quality, reconciliation, serialization, redaction | Forbidden |
| Contract | Each source/provider implementation against shared behavior | Mocked/fixture only |
| Integration | Source to provider to result/artifact behavior using fakes | Forbidden |
| Compatibility | Legacy JSON, root CLI, and `run()` behavior | Forbidden |
| Architecture/security | Import boundaries, resource limits, redaction, dependency/secret/static scans | Forbidden |
| Package/CLI | Wheel/sdist install and installed command behavior | Forbidden |
| Docs/browser | Executable snippets, generated references, links, keyboard/mobile/route/accessibility behavior | Local generated site only |
| Golden quality | Recall and field-level regression on approved corpus | Offline recorded responses by default |
| Live smoke | Provider credential/endpoint drift | Scheduled/manual only with protected secrets |
| Remote CI | Linux/macOS/Windows and Python 3.11-3.13 evidence | Runs only after authorized commit/push |

Testing rules:

- Never commit restricted questionnaires, credentials, raw authorization headers, or unsanitized provider traces.
- Use actually executed checks for completion evidence; static code inspection is supplementary.
- Preserve deterministic ordering in tests despite async execution.
- Separate output-schema compatibility from extraction-quality corrections.
- Treat variable recall as a first-class metric because current larger-model experiments dropped repeated variables.
- Use strict assertions for public contracts and diagnostic codes; avoid brittle snapshots of incidental logs.

## Documentation Checklist

- [ ] README describes current package/API rather than the internship PoC.
- [ ] Five-minute BYOK OpenAI-compatible quickstart is executable.
- [ ] Python SDK sync, async, batch, result, and artifact examples exist.
- [ ] CLI command and exit-code reference exists.
- [ ] Tier 1/Tier 2 support matrix names tested versions and limitations.
- [ ] OpenAI, Azure Foundry, Anthropic, OpenRouter, Vercel, custom gateway, and World Bank recipes exist.
- [ ] Credential precedence and secret-handling policy are explicit.
- [ ] Provider capability pages distinguish tested model rows from configuration-only presets.
- [ ] TOML schema and configuration precedence are generated/documented.
- [ ] SVIS field guide and generated JSON Schema are current.
- [ ] Custom Pydantic model guarantees and limitations are explicit.
- [ ] OCR, provenance, chunking, completeness, and quality evaluation are documented.
- [ ] EasyOCR artifact prefetch, checksums, cache size, license, first-run, and offline setup are documented.
- [ ] Untrusted-document limits and archive/path/external-resource controls are documented.
- [ ] Success/partial/failed and default/strict behavior are documented.
- [ ] Migration from `docling_pipeline.py` and 1.x deprecation policy exists.
- [ ] Privacy, retention, no-telemetry, and local-first behavior are documented.
- [ ] Static playground clearly labels precomputed results.
- [ ] Approved licensing, contribution, security, governance, and release language is present before publication.

## Risks & Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Bespoke World Bank license is unsuitable or unapproved | Public release/contributions cannot proceed | Keep publication outside this plan; do not add terms, claims, or publish jobs without a later authorized release decision |
| Already-public unlicensed repository has unresolved provenance | Continued pushes may compound legal exposure | Make current visibility/ownership/contribution disposition the first gate; permit only explicitly authorized local work |
| Tier 1/Tier 2 scope becomes an untestable “all formats” promise | Support burden and silent data loss | Publish exact tiers, versions, fixtures, diagnostics, and extension boundaries |
| Provider differences leak through the abstraction | Incorrect settings or inconsistent failures | Capability declarations, normalized errors, shared contract suite, and explicit unsupported-setting errors |
| OpenAI-compatible gateways diverge | Runtime failures despite common API shape | Test advertised presets and allow custom headers/base URLs through a constrained adapter |
| Custom schemas dilute SVIS purpose | Product becomes a generic extractor | Keep `SurveyScribe` SVIS-only; place custom models behind advanced `StructuredPipeline[T]` guarantees |
| Async implementation harms simple usage | Adoption declines or notebooks fail | Preserve a sync facade and clear running-loop guidance; keep common setup minimal |
| Partial exit code 0 hides data loss | Automation accepts incomplete output | Sidecar status by default, prominent CLI summary, typed SDK status, strict mode |
| Main JSON, sidecar, and manifest diverge | Automation reads stale or cross-run metadata | Shared run ID, staged artifact set, manifest-last publication, exclusive per-survey lock |
| OCR output is plausible but wrong | Silent research/data errors | Page diagnostics, provenance, OCR-specific golden fixtures, review policy, optional normalized artifacts |
| Dense repeated modules lose variables | Severe recall regression | Table-aware chunking, expected-row inventory, completeness diagnostics, separate recall metric |
| Internal `itsai` blocks public users/imports | Package cannot install or show help | Inject token callbacks; keep `itsai` out of public dependencies and import graph |
| New dependencies break Python/OS support | Installation failures | Validate before adoption, isolate extras, and run 3.11-3.13 cross-platform build/install CI |
| Stale documentation returns | Users follow unsafe or missing commands | Generate references, execute snippets, and fail strict docs/link checks |
| Restricted source or secrets enter fixtures/artifacts | Privacy/security incident | Synthetic/sanitized corpus, secret scans, redaction tests, explicit artifact retention |
| Archive bombs, macros, external relationships, or prompt injection abuse local processing | Resource exhaustion, network leakage, or unsafe model behavior | Hard limits, no macro/formula execution, confined bundles, disabled remote services, no model tools, adversarial tests |
| Survey Solutions export semantics are assumed incorrectly | False Tier 2 support claim | Block implementation claim until sanitized versioned fixtures are available |
| Remote CI cannot run from uncommitted `/cg-work` state | Required cross-platform evidence is unavailable | Separate local phase evidence; pause for authorized commit/push and resume to record CI URL |

## Out of Scope

- Managed model credentials or project-funded inference.
- Hosted or multi-tenant API, queues, accounts, quotas, billing, or distributed workers.
- Public user-upload playground or any website that accepts keys.
- Independent review/autofix agents.
- Guaranteed extraction quality for arbitrary custom Pydantic schemas.
- Remote URL ingestion and its SSRF/download policy.
- General-purpose document understanding unrelated to questionnaires.
- Separate provider/source distribution packages before ecosystem evidence justifies them.
- Public PyPI, TestPyPI, or GitHub Pages publication. These require legal/release authorization and a separate release action after this engineering plan.

## Completion Contract

### Outcome

The repository becomes an installable, typed, local-first `survey-scribe` engineering release candidate with SVIS-first sync/async APIs, a CLI, capability-aware provider adapters, fixture-backed questionnaire-source adapters, deterministic quality/status behavior, legacy compatibility, executed cross-platform CI, security/quality evidence, and publishable documentation. Public publication is explicitly excluded and requires a later legally authorized release action.

### Verification Surface

| ID | Phase | Evidence Required | Command/Artifact | Required |
|----|-------|-------------------|------------------|----------|
| V1 | 1 | Current public-repository legal disposition permits continued work; fixture rights/checksums, numeric quality thresholds, and dependency/OCR decisions are recorded | `docs/legal-disposition.md`; `tests/fixtures/golden/manifest.toml`; `tests/fixtures/golden/quality-thresholds.toml`; `docs/dependencies.md`; validation scripts | yes |
| V2 | 1 | Bootstrapped characterization captures current CLI, `run()`, exact schema serialization, legacy failure behavior, and approved corrections; a temporary uv environment installs the wheel and runs import/help without network, credentials, or `itsai` | `uv run pytest tests/characterization tests/test_schema.py`; `uv build`; `uv run pytest tests/package/test_clean_install.py` | yes |
| V3 | 2 | Typed config precedence, secret redaction, result statuses, diagnostics, and atomic artifact writing pass unit tests | `uv run pytest tests/unit/test_config.py tests/unit/test_results.py tests/unit/test_artifacts.py` | yes |
| V4 | 2 | Tier 1 adapters enforce resource/path/remote-service controls and process local digital/structured fixtures plus deterministic OCR fakes; EasyOCR cache checksums and an available local smoke pass without requiring remote CI | `uv run python scripts/validate_ocr_artifacts.py`; `uv run pytest tests/contract/sources tests/integration/test_tier1_sources.py` | yes |
| V5 | 3 | Provider envelopes, capabilities, errors, retries, truncation, redaction, and named tested model rows satisfy the offline adapter contract | `uv run pytest tests/contract/providers`; `docs/providers/capabilities.md` | yes |
| V6 | 3 | Async orchestration proves bounded concurrency, cancellation, retries, stable ordering, deterministic review rules, and `success/partial/failed` semantics | `uv run pytest tests/integration/test_pipeline.py tests/unit/test_quality.py` | yes |
| V7 | 4 | Normative `SurveyScribe`, document-level and reducer-based custom pipelines, lifecycle, batch, legacy JSON/CLI/run, and legacy-code cleanup pass | `uv run pytest tests/integration/test_public_api.py tests/compat tests/architecture` | yes |
| V8 | 4 | XLSForm preserves the named supported semantics, confines companions, and diagnoses unsupported features | `uv run pytest tests/contract/sources/test_xlsform.py` | yes |
| V9 | 5 | Installed CLI commands enforce the single/batch extraction-plus-artifact outcome table, including strict, collision, and staged-write failures | `uv run pytest tests/cli` | yes |
| V10 | 5 | Local lint, format, typing, offline tests, quality thresholds, package metadata/content, dependency/static/secret scans, and SBOM generation pass | Exact Step 10 command set; `dist/sbom.cdx.json`; offline quality report | yes |
| V11 | 5 | MkDocs, executable snippets/references, offline internal links, Chromium keyboard/mobile/network-route assertions, and axe-core checks pass; playground has no upload/live-key path | `uv run mkdocs build --strict`; `uv run pytest tests/docs`; `uv run linkchecker --ignore-url='^https?://' site/`; `uv run pytest tests/browser` | yes |
| V12 | 6 | Survey Solutions adapter is backed by approved versioned sanitized fixtures and explicit unsupported-feature diagnostics | `uv run --script scripts/validate_fixture_manifest.py tests/fixtures/sources/survey_solutions/manifest.toml`; `uv run pytest tests/contract/sources/test_survey_solutions.py` | yes |
| V13 | final | After Steps 12-13 and final local checks, user-authorized remote CI passes on Linux/macOS/Windows and Python 3.11-3.13; the named Linux/Python 3.12 real-EasyOCR offline job passes | Successful final-commit CI URL and all matrix/OCR jobs | yes |
| V14 | final | Engineering release-candidate artifacts, compatibility, SBOM, security/privacy checks, and checklist pass without any unapproved publish/deploy job or claim | `dist/`; `docs/release-checklist.md`; `uv run python scripts/check_workflow_policy.py .github/workflows`; `uv run pytest tests/security/test_workflow_policy.py` | yes |

### Constraints

| ID | Phase | Constraint | Check |
|----|-------|------------|-------|
| C1 | 1 | Default main SVIS JSON retains exact keys/nesting/types/enums/null/default ordering; approved value corrections are separately enumerated | Fixed-clock golden fixture plus intentional-corrections file |
| C2 | 4 | Existing root CLI shape and `run(Path, Path) -> None` remain supported through 1.x | Compatibility tests and deprecation assertion |
| C3 | 1 | Import, CLI help, and offline tests perform no network or credential acquisition | Clean-environment smoke tests with network/provider calls blocked |
| C4 | 3 | Core application code does not import provider SDK, Instructor, Docling, or `itsai` types across its ports | Import-boundary test and architecture scan |
| C5 | 2 | Secrets never enter TOML examples, logs, diagnostics, sidecars, fixtures, or generated docs | Redaction tests and secret scan |
| C6 | final | CPython 3.11, 3.12, and 3.13 remain supported on Linux, macOS, and Windows | Authorized remote CI matrix URL |
| C7 | 4 | Format and model claims are versioned, capability-aware, and fixture-backed; unknown behavior is configuration-only or diagnosed | Source/provider capability matrices and tests |
| C8 | 5 | Website remains static/sample-only with no uploads, stored keys, or live model spending | Route/build inspection and browser checks |
| C9 | final | No OSI/open-source claim, publish/deploy job, tag trigger, PyPI/TestPyPI upload, or Pages deployment exists without legal/release approval | Release checklist and workflow permission/trigger scan |
| C10 | 2 | Local documents cannot trigger remote fetches, macro/formula/script execution, bundle path escape, or unbounded processing | Adversarial source and resource-limit tests |

### Boundaries

- Allowed: package layout, source/provider ports and adapters, Pydantic models, async pipeline, compatibility shims, CLI, tests, approved fixtures, build-only CI, MkDocs site, static sample playground, and engineering release-candidate artifacts.
- Allowed: optional Azure/Anthropic dependencies and documented World Bank token-provider integration without a public `itsai` dependency.
- Out of scope: hosted API, managed credentials, multi-tenant infrastructure, public uploads, reviewer/autofix agents, remote URL ingestion, and guaranteed quality for arbitrary custom schemas.
- Out of scope: public TestPyPI/PyPI/GitHub Pages publication. A separate legally authorized release action is required.

### Iteration Policy

1. Resolve legal permission for continued local work, fixture rights, dependency/OCR choices, and numeric quality thresholds before bootstrapping implementation.
2. Bootstrap the test/package harness before executing characterization; move no orchestration code until characterization passes.
3. Implement phases in dependency order and run phase-local required evidence before recording completion. Survey Solutions fixture unavailability does not invalidate completed Phases 1-5.
4. Prefer the smallest compatible adapter or API change; do not introduce separate plugin distributions, a dependency-injection framework, or a new provider SDK path without an approved deviation.
5. Under `deviation-policy: ask`, pause before changing requirements, normative contracts, support tiers, provider/source claims, compatibility behavior, or quality thresholds.
6. Phase 5 CI is provisional and cannot satisfy V13. After Steps 12-13 and every final local check pass, pause for explicit user authorization to commit/push the complete tree; resume `/cg-work` only after that commit's full matrix and Linux/Python 3.12 real-EasyOCR job pass, then record V13.
7. Completion requires executed checks. Static inspection alone cannot satisfy required evidence, and a legal blocker can never substitute for engineering or release evidence.

### Blocked-Stop Conditions

- Legal disposition does not explicitly permit continued local implementation, fixture use, and any required push/CI visibility.
- Legacy SVIS output cannot be preserved within the exact compatibility contract and approved correction list.
- Dependency/OCR import probes fail on a required Python version with no approved alternative.
- Golden manifest lacks source rights, checksums, expected inventory, field judgments, or numeric thresholds needed by required quality evidence.
- Sanitized Survey Solutions fixtures/specification are unavailable when Step 12 begins. Stop Step 12/final completion, preserve completed core-phase evidence, and do not advertise support.
- A provider path cannot meet the normalized structured-output/error contract and removing it would change approved scope.
- Required artifact sets cannot be written transactionally or concurrent identical IDs cannot be isolated safely.
- Required authorized remote CI cannot be produced after the local handoff.
- Required verification fails after bounded recovery attempts.
- Continuing requires exposing credentials/restricted questionnaires, enabling remote document resources, or making an unapproved push/public artifact/publication.
- A required deviation is discovered and user approval is unavailable.
