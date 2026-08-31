---
date: 2026-08-28
title: "Survey Scribe Production Package Completion"
status: active
scope: "Deep"
brainstorm: "../brainstorms/2026-08-26-survey-scribe-production-package.md"
language: "Python"
estimated-effort: "large"
deviation-policy: "ask"
artifact-schema-version: 1
phases: 6
completed-phases: [1, 2]
current-phase: 3
execution-report: "../work-reports/2026-08-28-survey-scribe-production-package-refined.md"
supersedes: "2026-08-26-survey-scribe-production-package.md"
tags: [python, packaging, architecture, llm, docling, svis, providers, cli, testing, documentation, release]
---

# Plan: Survey Scribe Production Package Completion

## Objective

Complete the refactor of Survey Scribe from a repository-only questionnaire-to-SVIS proof of concept into a functional, installable, typed, local-first Python package. The finished engineering release candidate will expose SVIS-first synchronous and asynchronous APIs, a complete CLI, provider-neutral bring-your-own-key adapters, fixture-backed questionnaire-source adapters, deterministic quality and artifact behavior, legacy compatibility, cross-platform evidence, and complete documentation.

PyPI Trusted Publishing and GitHub Pages deployment are included as a final conditional release step. This plan does not itself authorize publication: deployment remains blocked until a separate formal approval updates the legal disposition and protected GitHub/PyPI environments are configured.

## Context

This revision supersedes the 2026-08-26 production-package plan while preserving its completed Phase 1 history. The approved architecture remains a single SVIS-first distribution using ports and adapters rather than a plugin microkernel or third-party provider router.

Verified baseline after merged PR #4 (`95ddaf35d3c58b471462bfcdb8d99d58e0133395`):

- Phase 1 legal, dependency, fixture-policy, compatibility, and package-bootstrap evidence is complete.
- The repository has modern Hatchling/uv packaging, PEP 639 MIT metadata, compatible runtime dependency ranges, `py.typed`, a static PEP 440 version, wheel/sdist tests, an isolated offline wheel install, and Twine validation.
- The packaged `src/survey_scribe/` runtime contains the SVIS models and bootstrap help/version CLI only. It has no config, result, source, provider, orchestration, or extraction implementation.
- The legacy `docling_pipeline.py`, `agents/`, and `extractors/` still perform repository-only PDF extraction. They import `itsai`, create a World Bank Azure client at import time, hardcode endpoint/model/retry settings, use `print()`, skip scanned PDFs, and do not provide an installable conversion command.
- CI passes on Linux, macOS, and Windows with Python 3.11-3.13, builds bounded distributions, and uploads build-only package/docs artifacts. The current pinned checkout, setup-uv, and upload-artifact releases emit Node 20 deprecation annotations.
- MkDocs provides installation, schema usage, examples, API reference, and release-readiness pages, but it does not yet document a functional SDK/CLI/provider/source runtime or deploy to Pages.
- MIT licensing is approved. Continued engineering and build-only CI are permitted. PyPI, TestPyPI, GitHub Pages, tag-triggered publication, and deployment permissions remain prohibited until separate approval.
- No `compound-gpid.md` or `compound-gpid.local.md` exists, so charter alignment and project-specific review settings cannot be verified.

Prior knowledge applied:

- Treat editable checkout, wheel, and sdist as separate filesystems; build first and test the exact artifact in an isolated environment. Source: `../solutions/build-errors/2026-08-26-bound-python-package-artifacts-and-evidence.md`.
- Keep provider SDKs, Instructor, Docling, and internal token providers behind adapter boundaries. Source: linked brainstorm and superseded plan.
- Preserve the exact legacy JSON/CLI behavior except for explicitly approved corrections. Source: Phase 1 characterization and compatibility fixtures.

## Requirements

| ID | Requirement | Source |
|----|-------------|--------|
| R1 | Provide a top-level SVIS-first `SurveyScribe` API with sync, async, and batch conversion | Brainstorm: Public API |
| R2 | Return a frozen typed `ExtractionResult[T]` with immutable result-owned collections and `success`, `partial`, and `failed` semantics | Brainstorm and prior plan review |
| R3 | Preserve the current SVIS JSON structure, root CLI shape, and `run(Path, Path) -> None` through 1.x | Phase 1 compatibility contract |
| R4 | Make OpenAI-compatible model, key, and optional base URL the simplest BYOK route | Brainstorm: Provider Flexibility |
| R5 | Support Azure OpenAI/Foundry, Anthropic, OpenRouter, Vercel Gateway, custom gateways, and injected token providers through normalized adapters | Brainstorm: Provider Flexibility |
| R6 | Support Tier 1 digital/scanned PDF, DOCX, XLSX, CSV, HTML, Markdown, and text with fixture-backed provenance | Brainstorm: Input Formats |
| R7 | Support XLSForm in core delivery and add Survey Solutions only from approved sanitized versioned fixtures | Brainstorm and prior plan review |
| R8 | Provide typed Python and TOML configuration for models, generation, retries, concurrency, validation, and artifacts without persisted secrets | Brainstorm: Configuration |
| R9 | Keep SVIS canonical; support document-level custom Pydantic extraction and chunked custom extraction only with a caller-supplied reducer | Brainstorm: Schema and Validation |
| R10 | Apply deterministic review, reconciliation, failure, retry, redaction, and atomic artifact policies | Brainstorm: Failure Behavior |
| R11 | Retain `pyproject.toml`, `src/`, Hatchling, `uv`, `py.typed`, Ruff, Pyright, pytest, and Python 3.11-3.13 | Existing package baseline |
| R12 | Provide unit, source/provider contract, integration, CLI, compatibility, package, docs/browser, security, and golden-quality tests | Brainstorm and testing baseline |
| R13 | Complete MkDocs documentation for API, CLI, providers, sources, configuration, schemas, migration, security, quality, and release | Existing docs plus brainstorm |
| R14 | Provide a static curated-sample playground with no uploads, keys, storage, backend route, or live inference | Brainstorm: Website |
| R15 | Keep runtime local-first with no hosted API, managed credentials, telemetry, or multi-tenant infrastructure | Brainstorm: Product Purpose |
| R16 | Track extraction completeness and quality separately, including dense repeated-table recall | README model-quality findings |
| R17 | Preserve the current legal/release gate: MIT and engineering builds are approved, but publication/deployment requires a separate recorded authorization | `docs/legal-disposition.md` and user-approved contract |
| R18 | Enforce untrusted-document resource, archive, path, external-reference, formula/macro, remote-service, and prompt-injection controls | Prior plan review |
| R19 | Move workflows to reviewed Node 24-compatible action releases pinned by immutable SHA while preserving least privilege and artifact isolation | GitHub Actions annotations and upstream action metadata |
| R20 | After separate release approval, use protected manual OIDC workflows for PyPI Trusted Publishing and GitHub Pages; never use long-lived publication tokens | User-requested final release path and release gate |
| R21 | Track every blocked-stop condition to prevention, owner, bounded resolution action, and executed closure evidence; completion is prohibited while any blocker remains unresolved | User instruction on 2026-08-28 |

## Normative Runtime Contracts

These decisions remain implementation authority. Changes require approval under `deviation-policy: ask`.

### Compatibility Contract

- Legacy JSON compatibility means exact key names, nesting, JSON value types, enum values, null/default serialization, field order, and variable order under a fixed clock. Whitespace is not contractual.
- Value corrections are allowed only when listed in `tests/fixtures/legacy/intentional-corrections.toml`. Initial corrections cover deterministic review flags, real provenance, scan processing, and explicit partial diagnostics.
- Keep `python docling_pipeline.py INPUT [--output-dir DIR]` and `run(Path, Path) -> None` through 1.x as a lazy deprecated shim.
- The shim searches only explicit `--config`, then `./survey-scribe.toml`, then environment values. It never searches parent/home directories or restores import-time World Bank credentials.
- Missing configuration produces one actionable migration error rather than silently selecting a provider.

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
```

- V1 accepts local paths and confined local bundles only. Reject bytes, arbitrary file objects, and remote URLs.
- Invalid constructor/config/programmer inputs raise typed exceptions before conversion. Source/provider/runtime failures return failed results. `asyncio.CancelledError`, `KeyboardInterrupt`, and `SystemExit` propagate.
- Batch results preserve input order and share one global concurrency ceiling.
- Support sync/async context managers and explicit close methods. The sync facade rejects use inside a running event loop.
- Conversion has no write side effect. `result.write(..., overwrite=False)` returns a new frozen result and raises typed artifact exceptions without mutating the original.
- `StructuredPipeline[T]` performs one bounded document-level call. `ChunkedStructuredPipeline[TChunk, TResult]` requires a reducer and passes stable source-order successful responses plus failed-block diagnostics.

### Configuration Precedence

| Rank | CLI | Python SDK |
| --- | --- | --- |
| 1 | Explicit flags and non-echo credential prompt | Explicit constructor arguments |
| 2 | `SURVEY_SCRIBE_*` environment values | Explicit `SurveyScribeConfig` values |
| 3 | Provider-standard environment values | Environment values only when `resolve_environment=True` |
| 4 | Explicit `--config PATH` | Explicit requested TOML path |
| 5 | `./survey-scribe.toml` only | No implicit TOML unless `from_config()` is used |
| 6 | Package defaults | Package defaults |

- Do not search parent or home directories.
- Support generic `SURVEY_SCRIBE_API_KEY`, `SURVEY_SCRIBE_MODEL`, `SURVEY_SCRIBE_BASE_URL`, and `SURVEY_SCRIBE_PROVIDER`, plus provider-standard OpenAI, OpenRouter, Vercel, Anthropic, and Azure variables.
- Simultaneous key, bearer token, and token-callback forms are errors unless the adapter defines one unambiguous precedence.
- Serialization always omits secrets.

### Provider Contract

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

- `StructuredProvider.generate()` returns the normalized envelope, never a bare model or raw SDK response.
- Do not retain raw response bodies, headers, tokens, or questionnaire text in provenance.
- `ModelCapabilities` records structured-output support, token estimator, input/output limits, supported generation settings, and evidence state (`verified`, `configuration-only`, or `unknown`).
- Claims apply only to named tested model/version rows. Explicit unknown or unsupported settings fail closed.
- Truncation/length finish reasons cannot be treated as complete structured output.

### Default Quality Action Table

| Condition | Diagnostic/action | `needs_review` | Extraction status |
| --- | --- | --- | --- |
| Confidence below threshold | `QUALITY_LOW_CONFIDENCE`; preserve fields | true | unchanged |
| Categorical variable lacks categories | `QUALITY_MISSING_CATEGORIES`; preserve record | true | unchanged unless structurally invalid |
| Numeric range has min greater than max | Validation retry, then failed block | n/a | partial if other blocks are usable |
| Same raw name on distinct questions | `QUALITY_DUPLICATE_RAW_NAME`; retain both | true | unchanged |
| Exact repeated question caused by overlapping blocks | Remove later duplicate by source order; `QUALITY_OVERLAP_DEDUPED` | unchanged | unchanged |
| Similar question without overlap proof | `QUALITY_POSSIBLE_DUPLICATE`; retain both | true | unchanged |
| Model module conflicts with authoritative source section | Source section wins; `QUALITY_MODULE_RECONCILED` | true | unchanged |
| Missing required metadata | Preserve legacy placeholder; `METADATA_INCOMPLETE` | unchanged | partial |
| Unreadable page, truncation, or failed block | Record provenance diagnostic; fabricate nothing | affected records true where applicable | partial |

CLI `--strict` concerns partial execution, not review warnings. Changing the default table is a public-policy deviation.

### Artifact and Command Outcome Contract

- Write main JSON, sidecar, and manifest into an immutable run-specific generation, validate/fsync it, then atomically replace one active-generation pointer.
- Write the legacy `<survey_id>_svis.json` as a separate atomically replaced compatibility projection. A projection/pointer failure must not corrupt the prior generation.
- Default `overwrite=False`; `overwrite=True` creates a new generation. Use an exclusive per-survey lock and typed collision errors.
- Any required artifact write failure exits nonzero regardless of extraction status.
- Single default CLI: success `0`, partial `0`, failed/write failure nonzero. Single strict: only success `0`.
- Batch default exits nonzero if any input fails; partial-only batch exits `0`. Batch strict exits nonzero for any partial, failed, or write failure.

### Untrusted-Document and OCR Contract

- Configurable default ceilings: 250 MB source, 2,000 pages, 1 GB archive expansion, 100:1 archive ratio, 2,000,000 tabular cells, 100 companion files, and 30-minute source conversion.
- Never execute formulas, macros, embedded scripts, or external relationships. Ignore HTML remote resources. Confine companions to `SourceBundle.root` after symlink resolution.
- Disable Docling remote services. Treat questionnaire text as untrusted data in fixed system instructions, with no model tools.
- Pin and checksum the approved EasyOCR artifacts. Set `DOCLING_ARTIFACTS_PATH`, then block network during extraction tests.
- Run Docling in a killable worker process. On deadline, terminate, join, recreate, and emit a stable timeout diagnostic.
- Use deterministic fakes across the full matrix and one designated Linux/Python 3.12 real-OCR job after artifact setup.

## Dependency Graph

| Phase | Depends on | Unlocks |
| --- | --- | --- |
| 1. Completed foundation | Approved prior plan | Runtime implementation |
| 2. Runtime and sources | Phase 1 package/compatibility baseline | Providers and orchestration |
| 3. Providers and orchestration | Phase 2 contracts | Public API migration |
| 4. Public API and core formats | Phases 2-3 | CLI and delivery evidence |
| 5. Delivery and evidence | Phases 1-4 | Engineering release-candidate decision |
| 6. External-gated hardening | Phase 5 evidence and approved external fixtures | Final readiness and conditional release activation |

Phases are sequential at their gates. Within Phase 2, result/config work can proceed alongside source fixture preparation. Within Phase 5, CI and documentation can proceed in parallel after the public API stabilizes.

## Phase 1: Completed Legal, Package, and Compatibility Foundation

### 1. Preserve Legal, Fixture, Dependency, and Quality Baselines

- **Requirements**: R3, R10, R16, R17, R18, R21
- **Files**: `docs/legal-disposition.md`, `docs/dependencies.md`, `docs/compatibility.md`, `docs/evaluation.md`, validation scripts, golden/legacy fixture policy
- **Details**: Treat the completed Phase 1 evidence as immutable baseline. MIT and continued engineering are approved; the separate publication gate remains. Do not add real/restricted fixtures without rights, approval, provenance, and checksums.
- **Test Scenarios**: Legal gate regression, checksum drift, malformed provenance, weakened thresholds, unsupported dependency/Python combination.
- **Tests**: Existing Phase 1 evidence and manifest/dependency validation scripts.
- **Acceptance criteria**: Existing V1 remains passed. Any change to legal scope, dependency/OCR choice, fixture rights, or quality minima requires a deviation decision.

### 2. Preserve the Packaged Schema, Characterization, and Distribution Baseline

- **Requirements**: R3, R11, R12, R15, R16
- **Files**: `pyproject.toml`, `uv.lock`, `src/survey_scribe/models/`, compatibility re-export, characterization/package tests, CI/docs workflows
- **Details**: Preserve PR #4's PyPI metadata, MIT license, typed schema, coverage gate, docs bootstrap, bounded wheel/sdist contents, exact-artifact offline install, and build-only artifacts. The temporary root `schemas` re-export remains only until Step 7.
- **Test Scenarios**: Import/help without extras or credentials, omitted wheel namespace, leaked sdist files, ambient-cache/index dependence, malformed metadata, missing `py.typed`.
- **Tests**: Existing characterization, schema, unit, package, Twine, docs, and CI evidence.
- **Acceptance criteria**: Existing V2 remains passed and no later phase weakens artifact isolation or import safety.

## Phase 2: Runtime and Source Foundation

### 3. Implement Configuration, Results, Errors, and Transactional Artifacts

- **Requirements**: R2, R8, R10, R15, R17, R21
- **Files**: `src/survey_scribe/config.py`, `results.py`, `errors.py`, `serialization/legacy.py`, `serialization/artifacts.py`, `tests/unit/test_config.py`, `test_results.py`, `test_artifacts.py`
- **Details**: Implement the normative precedence matrix, reject ambiguous credentials, and validate unknown TOML keys/config versions. Define typed exceptions and stable diagnostic codes. Implement a frozen generic result whose diagnostics, failed blocks, and artifacts are tuples; document that caller-owned `T` can remain mutable. Separate conversion from writes. Implement immutable generation directories, atomic active pointer and legacy projection, exclusive lock, overwrite policy, and redaction for keys, auth headers, endpoint query secrets, and questionnaire text.
- **Test Scenarios**: Every precedence rank; parent/home config ignored; ambiguous credentials; invalid URL/threshold/concurrency/version; secret serialization; result immutability; success/partial/failed derivation; collision; concurrent same survey; failure at generation/projection/pointer stage; path traversal survey ID; nested exception redaction.
- **Tests**: `uv run pytest tests/unit/test_config.py tests/unit/test_results.py tests/unit/test_artifacts.py`
- **Acceptance criteria**: One deterministic config object reaches the application layer; statuses/diagnostics are stable; no secret serializes; failed writes preserve the prior valid generation.

### 4. Build the Source Port and Tier 1 Adapters

- **Requirements**: R6, R10, R16, R18
- **Files**: `src/survey_scribe/sources/base.py`, `registry.py`, `docling.py`, `tabular.py`, `chunking.py`, OCR validator, source contracts/integration fixtures
- **Details**: Accept only local paths and confined bundles. Enforce file/page/archive/cell/companion/deadline limits before expensive work. Disable remote resources/services, executable workbook/document content, and path escape. Port Docling with `PyPdfiumDocumentBackend`, approved EasyOCR setup, and a killable worker. Process scans rather than skipping them; preserve preamble, short content, and actual page provenance. Implement DOCX/HTML/Markdown/text and deterministic openpyxl/CSV sources. Add token/table-aware chunking, overlap provenance, repeated-row inventory, and prompt-injection isolation.
- **Test Scenarios**: Digital/scanned/mixed PDF; corrupt/missing OCR cache; network blocked; encrypted/oversized input; archive bomb; DOCX/HTML external resource; XLSX macro/formula; symlink escape; resource/deadline limit; prompt injection; no headings; dense/multilingual table; unsupported/ambiguous format.
- **Tests**: `uv run python scripts/validate_ocr_artifacts.py`; `uv run pytest tests/contract/sources tests/integration/test_tier1_sources.py`
- **Acceptance criteria**: Every Tier 1 format produces a deterministic normalized representation with available page/sheet/row provenance; failures return diagnostics rather than prints or silent drops.

## Phase 3: Providers and Orchestration

### 5. Implement the Structured Provider Port and BYOK Adapters

- **Requirements**: R4, R5, R8, R10, R15, R21
- **Files**: `src/survey_scribe/providers/base.py`, `capabilities.py`, `openai_compatible.py`, `azure.py`, `anthropic.py`, provider contracts/fakes, `docs/providers/capabilities.md`
- **Details**: Implement the normalized `ProviderResponse[T]` and `ModelCapabilities`. Keep Instructor/raw SDK responses internal. Implement OpenAI-compatible endpoints and tested presets for OpenAI/OpenRouter/Vercel/custom gateways, Azure key/token callbacks, and optional Anthropic. Prefer OpenAI compatibility for Foundry unless fixtures justify another SDK. Remove all runtime `itsai` imports and inject World Bank token callbacks. Classify retryable/non-retryable errors, bound backoff, propagate cancellation, redact failures, and fail closed on unknown explicit settings or truncation.
- **Test Scenarios**: Every credential source; custom base URL/header allowlist; verified/configuration-only model; unsupported setting; truncation; 401/403; 429 success/exhaustion; timeout/5xx; malformed structured response; validation retry; cancellation; token refresh; redaction.
- **Tests**: `uv run pytest tests/contract/providers`
- **Acceptance criteria**: Every advertised adapter/model row passes shared contracts; application/core modules import no SDK, Instructor, or `itsai` types; pull-request tests need no keys.

### 6. Rebuild Extraction as an Async Deterministic Pipeline

- **Requirements**: R1, R2, R9, R10, R16
- **Files**: `src/survey_scribe/pipeline.py`, quality models/policy, versioned prompts, pipeline integration and quality tests
- **Details**: Implement metadata extraction/reconciliation, bounded concurrency, stable ordering, cancellation, retries, truncation handling, and failed-block collection. Apply every default quality-table row without unapproved mutation. Exact overlap deduplication requires normalized content plus provenance; possible duplicates remain flagged. Missing metadata, unreadable regions, truncation, or failed blocks produce partial results. Keep custom schemas outside SVIS reconciliation unless explicitly supplied.
- **Test Scenarios**: Complete conversion; metadata fallback; one/all blocks fail; out-of-order completion; global ceiling; cancellation; duplicate names; overlap; missing categories; confidence boundary; unreadable OCR; dense repeated rows; running event loop.
- **Tests**: `uv run pytest tests/integration/test_pipeline.py tests/unit/test_quality.py`
- **Acceptance criteria**: Fake-provider behavior is deterministic; ports prevent source/provider coupling; all statuses/review rules have boundary tests.

## Phase 4: Public API and Core Format Completion

### 7. Publish the SDK, Custom Pipelines, and Compatibility Shim

- **Requirements**: R1, R2, R3, R9
- **Files**: `src/survey_scribe/client.py`, package exports, pipelines, root shim, legacy directories, public API/compatibility/architecture tests
- **Details**: Implement normative signatures, local-input limits, raise-versus-result behavior, cancellation, batch ordering/concurrency, lifecycle methods, and new-envelope writes. Keep `SurveyScribe` SVIS-only. Implement bounded `StructuredPipeline[T]` and reducer-required `ChunkedStructuredPipeline`. Convert `docling_pipeline.py` to the only required lazy deprecated shim. Remove obsolete `agents/`, `extractors/`, and `schemas/` or retain only approved re-exports. Remove temporary Ruff/Pyright exclusions and assert no runtime file imports `itsai`, contains the development endpoint, creates clients at import, or uses `print()` for runtime logging.
- **Test Scenarios**: Five-line use; context managers; path/bundle accepted; bytes/file/URL rejected; constructor error raises; operational error returns failed; cancellation; sync/async parity; batch ordering; custom token overflow; reducer success/failure/empty/partial; legacy invocation/config migration/warning; unsafe legacy code absent.
- **Tests**: `uv run pytest tests/integration/test_public_api.py tests/compat tests/architecture`
- **Acceptance criteria**: Typed examples pass Pyright; legacy selected entry points work without import-time auth; custom models do not receive implicit SVIS policy.

### 8. Add the Core XLSForm Adapter

- **Requirements**: R7, R10, R16, R18
- **Files**: `src/survey_scribe/sources/xlsform.py`, XLSForm contracts/fixtures, `docs/sources/xlsform.md`
- **Details**: Deterministically parse supported `survey`, `choices`, and `settings` sheets while preserving names, multilingual labels, groups, repeats, relevance, constraints, calculations, and choice references. Confine external-choice companions, enforce limits, never evaluate formulas/macros, and diagnose unsupported features. LLM enrichment cannot replace native names or logic.
- **Test Scenarios**: Multilingual labels; groups/repeats; external choices; path escape; relevance/constraints; malformed/oversized workbook; formula/macro; unsupported type; missing choice; deterministic order.
- **Tests**: `uv run pytest tests/contract/sources/test_xlsform.py`
- **Acceptance criteria**: The support matrix names exact tested features/limitations; no Survey Solutions claim appears here.

## Phase 5: Delivery and Evidence

### 9. Complete the Installed CLI and Migration Experience

- **Requirements**: R1, R2, R3, R8, R10, R13
- **Files**: `src/survey_scribe/cli.py`, `tests/cli/`, `docs/cli.md`, `docs/migration.md`, README and editor instructions
- **Details**: Implement `convert`, `batch`, `providers`, `config check`, and `schema export` with stdlib `argparse` over the public API. Keep credentials in environment variables or non-echo input. Enforce the command outcome, artifact, overwrite, collision, strict, and shared-manifest contracts. Emit concise redacted summaries with paths, diagnostics, and failed-block counts. Write sidecars/manifests by default; reject `--no-sidecar` for partial output. Update every stale path/provider command.
- **Test Scenarios**: Every subcommand; config precedence; missing/unsupported input; success/partial/failed; write failures; strict partial; invalid no-sidecar; overwrite/collision; batch aggregate exits; redacted provider error; installed/legacy invocation.
- **Tests**: `uv run pytest tests/cli tests/compat/test_legacy_cli.py`
- **Acceptance criteria**: CLI behavior is executable under fakes; docs/editor tasks reference real commands; no credential enters output.

### 10. Complete CI, Security, Quality Evaluation, and Node 24 Maintenance

- **Requirements**: R11, R12, R16, R17, R19, R21
- **Files**: test suites/fixtures, quality/security scripts, allowlists/baselines, `.github/workflows/ci.yml`, optional provider smoke, `docs/evaluation.md`
- **Details**: Organize unit, contract, integration, CLI, compatibility, architecture, package, docs/browser, security, and golden suites. Preserve the exact-artifact offline install and bounded archives. Add quality evaluation and security collection/verification with explicit network boundaries and one authoritative policy exit. Replace current Node 20 action pins with reviewed Node 24-compatible releases pinned to immutable SHAs (upstream research observed checkout/upload-artifact v7.0.1 and setup-uv v10.0.1 on 2026-08-28; re-resolve and review at implementation). Keep read-only workflow permissions and reject tags/deploy/OIDC until Step 13 authorization. Optional provider smoke is scheduled/manual, protected, bounded, and never required in pull requests.
- **Test Scenarios**: Full offline suite; clean wheel; no-network enforcement; quality regression; missing extra; absent smoke secrets; cost ceiling; failure artifacts; mutable action tag; Node 20 annotation; unauthorized trigger/permission/deploy.
- **Tests**: Ruff; format; Pyright; full pytest; build/Twine/archive tests; quality evaluator; security collect/verify; SBOM; workflow schema and policy checks; warning-free remote CI.
- **Acceptance criteria**: Local gates and quality outputs pass; action SHAs are reviewed/Node 24-compatible; build-only permissions are enforced; CI has no Node runtime deprecation annotation.

### 11. Complete Documentation, Website, and Static Sample Playground

- **Requirements**: R13, R14, R15
- **Files**: `mkdocs.yml`, organized docs for getting started/API/providers/sources/config/SVIS/custom schemas/security/quality, playground, docs/browser tests, docs workflow
- **Details**: Generate API/config/JSON-Schema references and execute examples. Distinguish verified model rows from presets/unknowns. Document all contracts, supported versions, limits, offline OCR setup, migration, privacy, and result statuses. Build a curated precomputed sample explorer with no upload, key, storage, backend, or network inference path. Keep build-only/read-only docs artifacts until Step 13 authorization.
- **Test Scenarios**: Strict build; snippets; generated drift; internal links/anchors; keyboard/mobile/search/navigation; route scan; accessibility; secret scan.
- **Tests**: `uv run mkdocs build --strict`; docs tests; offline internal link checker; Playwright Chromium browser/accessibility suite.
- **Acceptance criteria**: A new user can install, configure, convert, interpret partial output, and use a custom model from the site; the playground is demonstrably static.

## Phase 6: External-Gated Integration and Release Hardening

### 12. Add Survey Solutions Only from Approved Fixtures

- **Requirements**: R7, R10, R16, R18, R21
- **Files**: Survey Solutions adapter, fixture validator/manifest, sanitized fixtures, source contract, support docs
- **Details**: Obtain sanitized exports with rights/checksum/version records before implementation. Map only fixture-defined sections, rosters, questions, categories, conditions, IDs, and companions. Enforce resource/path/network controls and stable unsupported-version/feature diagnostics. Never infer universal support from one export.
- **Test Scenarios**: Supported version; nested roster; links; unknown version; unsupported feature; malformed/oversized archive; external reference; deterministic order; restricted data scan.
- **Tests**: Fixture-manifest validator and `uv run pytest tests/contract/sources/test_survey_solutions.py`.
- **Acceptance criteria**: Exact versioned support matrix and tests exist. If fixtures are unavailable, stop this step/final completion without weakening completed core evidence or advertising support.

### 13. Complete Release Readiness and Conditional PyPI/Pages Activation

- **Requirements**: R3, R11, R12, R13, R15, R17, R19, R20, R21
- **Files**: governance/release docs, package metadata, SBOM, workflow policy, release workflow only after approval, docs workflow only after approval, built artifacts
- **Details**: Finish support/deprecation policy, security contacts, changelog, checklist, SBOM, package checks, and internal compatibility smoke. Preserve the legacy shim through 1.x. Record final authorized CI evidence. Without separate publication approval, keep release/deploy jobs absent and provide an exact activation checklist. After explicit approval: configure protected `pypi` and `github-pages` environments; register PyPI Trusted Publisher; add manual `workflow_dispatch` jobs using reviewed SHA-pinned actions; scope `id-token: write` only to PyPI/Pages jobs and `pages: write` only to Pages; verify version/commit/changelog/artifact digest; use environment approval; never use long-lived tokens or tag triggers. Actual publish/deploy invocation remains a separate explicit release action.
- **Test Scenarios**: Metadata/archive/SBOM; missing approval; workflow remains absent; wrong environment/branch/version; OIDC failure; duplicate PyPI version; Pages failure; rerun; rollback/yank guidance; unauthorized permissions/tags/deploy.
- **Tests**: Full local verification; final CI URLs; package/Twine/archive/install tests; security/workflow policy; release checklist. If authorized, manual workflow dry run and explicit publish/deploy evidence.
- **Acceptance criteria**: Engineering release-candidate evidence passes. Publication remains disabled without approval. If approval exists, protected manual workflows satisfy least privilege and produce traceable release/deploy evidence.

## Blocked-Stop Resolution Matrix

No blocker can be silently waived, relabeled as passed, or satisfied by static inspection. `/cg-work` must record each row in the execution report as `not-triggered`, `resolved`, or `blocked`, with the executed evidence or user-approved plan revision that supports the state.

| ID | Blocked condition | Prevention | Bounded resolution action | Owner | Closure evidence |
| --- | --- | --- | --- | --- | --- |
| B1 | Legal disposition, fixture rights, secret rules, or publication gate would be violated | Check disposition and fixture manifests before each affected phase; enforce workflow/secret policies in CI | Stop the affected action; obtain written approval or replace/remove the prohibited fixture/action through an approved plan revision | Maintainer/legal approver | Updated disposition/approval, validated fixture manifest, policy tests, execution-report decision |
| B2 | Exact legacy SVIS or CLI compatibility cannot be preserved | Characterization/golden tests run before and after each migration slice; keep root shim isolated | Minimize the change; add only an intentional correction with rationale and explicit user approval, or revise the public compatibility requirement | Implementation lead and downstream owner | Passing compatibility suite plus approved correction/revision record |
| B3 | Required provider/source adapter cannot satisfy the normalized contract on supported Python versions | Run dependency/API spikes and shared contract tests before advertising support | Fix the adapter within two bounded recovery rounds; select an already-approved compatible SDK path; otherwise request a scoped requirement revision and remove the unsupported claim | Adapter owner | Python 3.11-3.13 contract/import evidence and capability matrix update |
| B4 | OCR, quality, or Survey Solutions fixtures lack rights, checksums, or versioned semantics | Synthetic-first fixtures; manifest validation before tests; no restricted files in git | Obtain approved sanitized fixtures and complete provenance/checksum metadata; if unavailable, keep the affected support claim blocked until an explicit scope revision | Data steward and maintainer | Approved manifest, checksum validation, rights record, restricted-data scan |
| B5 | Transactional artifact writes or concurrency isolation cannot be proven | Design immutable generations, locks, atomic pointers, and injected failure tests before CLI integration | Reproduce with deterministic fault injection; correct the write protocol within two rounds; do not expose write commands until collision/failure tests pass | Runtime owner | Passing artifact concurrency/fault suite and no-corruption evidence |
| B6 | Required local or remote verification fails after bounded recovery | Run phase-local gates continuously and keep CI equivalent to local commands | Perform up to two root-cause/fix/retest rounds scoped to the failure; if still failing, record exact evidence and stop for plan revision | Phase owner | Successful rerun URL/log, or blocked report with failing command and root cause |
| B7 | PyPI/Pages activation lacks explicit approval or protected environments | Keep deploy actions, OIDC, Pages permission, and tag triggers prohibited by policy until Step 13 | Obtain separate authorization; configure protected environments and Trusted Publisher; review least privilege; otherwise leave deployment disabled without blocking engineering-release-candidate evidence | Release approver and repository administrator | Approval record, environment settings, policy validation, authorized manual run evidence |
| B8 | A required deviation is discovered while user approval is unavailable | Use `deviation-policy: ask`; surface deviations before mutation | Stop at the decision boundary; record options/impact; resume only after explicit approval or a revised plan | User and implementation lead | Conversation approval or superseding validated plan, recorded in execution report |

Resolution rules:

1. Internal engineering blockers B2, B3, B5, and B6 require executed passing evidence before their phase can complete.
2. External blockers B1, B4, B7, and B8 require the named approval/artifact or an explicit validated scope revision. Absence is never treated as success.
3. The two-round recovery budget limits repeated fixes; it does not permit lowering tests, deleting required assertions, broadening permissions, or weakening contracts.
4. Final completion requires V16: every B1-B8 row is `not-triggered` or `resolved`; no row can remain `blocked`.

## Testing Strategy

Use an offline-first pyramid:

| Layer | Purpose | Network policy |
| --- | --- | --- |
| Unit | Config, statuses, diagnostics, quality, serialization, redaction | Forbidden |
| Contract | Every source/provider adapter against shared behavior | Fixtures/fakes only |
| Integration | Source-provider-result-artifact behavior | Forbidden |
| Compatibility | Legacy JSON, root CLI, and `run()` | Forbidden |
| Architecture/security | Boundaries, limits, redaction, dependencies, secrets, workflows | Forbidden except explicit collection |
| Package/CLI | Exact wheel/sdist install and installed commands | Forbidden after wheelhouse preparation |
| Docs/browser | Snippets, references, links, keyboard/mobile/routes/accessibility | Generated local site only |
| Golden quality | Recall and field-level regressions on approved corpus | Recorded responses by default |
| Live smoke | Provider/OCR drift | Protected scheduled/manual only |
| Remote CI | Python/OS evidence and release-candidate artifacts | Authorized pushes only |

Rules:

- Never commit restricted questionnaires, credentials, raw auth headers, or unsanitized traces.
- Preserve stable ordering despite async execution.
- Separate schema compatibility from extraction-quality corrections.
- Treat dense repeated-row recall as a first-class metric.
- Use stable public contracts and diagnostic codes; avoid snapshots of incidental logs.
- Treat editable checkout, wheel, and sdist as distinct evidence surfaces.

## Documentation Checklist

- [ ] README shows a working five-minute BYOK conversion.
- [ ] Sync, async, batch, result, artifact, and custom model examples execute.
- [ ] CLI commands, configuration precedence, exits, and migration are complete.
- [ ] Tier 1/Tier 2 formats and exact limitations are explicit.
- [ ] OpenAI, Azure, Anthropic, OpenRouter, Vercel, custom gateway, and token-callback recipes exist.
- [ ] Provider capability pages separate verified models from configuration-only presets.
- [ ] Generated configuration, API, and JSON-Schema references are current.
- [ ] OCR artifacts, provenance, chunking, completeness, and quality evaluation are documented.
- [ ] Untrusted-document limits and path/network/executable-content controls are explicit.
- [ ] Success/partial/failed and default/strict behavior are explicit.
- [ ] Legacy migration and 1.x deprecation policy are explicit.
- [ ] Privacy, retention, no telemetry, and local-first behavior are explicit.
- [ ] Static playground clearly labels precomputed results.
- [ ] Release checklist separates engineering readiness from authorized publication.

## Risks & Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Scope expands across too many formats/providers | Delayed or unverifiable delivery | Enforce explicit tiers, named versions, fixtures, shared contracts, and phase gates |
| Provider differences leak into core | Inconsistent behavior and hard coupling | Normalize envelopes/capabilities/errors and enforce architecture tests |
| OpenAI-compatible gateways diverge | Runtime failures despite common protocol | Test named presets; classify custom gateways as configuration-only |
| Internal `itsai` remains reachable | Public import/CLI failure | Remove it from runtime imports and inject token callbacks |
| Async complexity harms simple use | Notebook/event-loop failures | Keep a tested sync facade with explicit running-loop rejection |
| Partial exit code hides data loss | Automation accepts incomplete extraction | Sidecar/status summaries by default and strict mode |
| OCR output is plausible but wrong | Silent extraction errors | Provenance, diagnostics, OCR fixtures, quality thresholds, review flags |
| Dense repeated modules lose variables | Severe recall regression | Table-aware chunks, repeated-row inventory, separate completeness metrics |
| Artifact generations diverge | Stale/cross-run output | Immutable generations, active pointer, lock, atomic projection |
| Restricted data or secrets leak | Privacy/security incident | Approved synthetic/sanitized fixtures, redaction, secret scans, bounded artifacts |
| Untrusted files trigger unsafe behavior | Resource exhaustion or network/code execution | Limits, process timeout, disabled remote resources, confined paths, no formulas/macros/tools |
| Actions remain on Node 20 | Future workflow breakage | Review and pin Node 24-compatible releases; assert annotation-free CI |
| Artifact tests regress to editable-only evidence | Broken published package | Preserve bounded archive and exact isolated install tests |
| Publication occurs before approval | Governance/security breach | Workflow policy gate; no deploy actions/OIDC until approval; protected manual environments afterward |
| Survey Solutions semantics are assumed | False support claim | Block on approved versioned sanitized fixtures |

## Out of Scope

- Hosted or multi-tenant API, accounts, quotas, billing, queues, or managed credentials.
- Public user-upload playground or website accepting keys.
- Remote URL ingestion and SSRF/download policy.
- Independent review/autofix agents.
- Guaranteed quality for arbitrary custom Pydantic schemas.
- General document understanding unrelated to questionnaires.
- Separate provider/source distributions before ecosystem evidence justifies them.
- Any PyPI/TestPyPI/Pages publication before separate explicit approval.

## Completion Contract

### Outcome

The repository becomes a functional, installable, typed, local-first `survey-scribe` release candidate that converts supported questionnaire sources through SVIS-first sync/async APIs and a complete CLI, with provider-neutral BYOK adapters, deterministic quality/status behavior, legacy compatibility, security controls, cross-platform evidence, and complete documentation. PyPI and GitHub Pages activation is included as a conditional release step but cannot execute without separate formal authorization.

### Verification Surface

| ID | Phase | Evidence Required | Command/Artifact | Required |
|----|-------|-------------------|------------------|----------|
| V1 | 1 | Legal, fixture, dependency, and quality foundations remain valid | Existing Phase 1 report and validation artifacts | yes |
| V2 | 1 | Packaged schema, characterization, isolated install, metadata/docs bootstrap, and CI baseline remain valid | Existing Phase 1 evidence plus merged PR #4 CI | yes |
| V3 | 2 | Config precedence, redaction, result envelopes, diagnostics, and atomic artifacts pass | Config/result/artifact unit suites | yes |
| V4 | 2 | Tier 1 source adapters enforce resource/path/network controls and preserve provenance | Source contracts/integration and OCR validator | yes |
| V5 | 3 | Provider adapters satisfy normalized envelopes, capabilities, retries, errors, truncation, and redaction | Provider contract suite and capability matrix | yes |
| V6 | 3 | Async pipeline proves bounded concurrency, cancellation, stable order, quality policy, and statuses | Pipeline integration and quality unit suites | yes |
| V7 | 4 | SDK/custom pipelines/lifecycle/batches/legacy shim pass without `itsai` or import-time clients | Public API, compatibility, architecture suites | yes |
| V8 | 4 | XLSForm preserves documented semantics and confines companions | XLSForm source contract suite | yes |
| V9 | 5 | Installed CLI implements required commands and outcome/exit contracts | CLI and legacy CLI suites | yes |
| V10 | 5 | Local quality/package/security/SBOM/workflow gates pass with reviewed Node 24-compatible pinned actions | Step 10 commands and warning-free CI | yes |
| V11 | 5 | Docs/examples/links/browser/accessibility/static-playground checks pass | MkDocs, docs, link, browser suites | yes |
| V12 | 6 | Survey Solutions claim is backed by approved versioned sanitized fixtures | Fixture validator and adapter contract | yes |
| V13 | final | Final Python 3.11-3.13 Linux/macOS/Windows CI and designated real OCR pass | Final authorized CI URLs | yes |
| V14 | final | Release-candidate artifacts, compatibility, security, privacy, and checklist pass | `dist/`, SBOM, release checklist, policy tests | yes |
| V15 | 6 | If separately authorized, protected manual PyPI/Pages workflows use OIDC/environment approval; otherwise deployment remains disabled | Approval record, environments, workflow evidence | no |
| V16 | final | Every B1-B8 blocked-stop row is closed as `not-triggered` or `resolved` with executed evidence or an approved validated scope revision | Execution-report blocker matrix and referenced evidence | yes |

### Constraints

| ID | Phase | Constraint | Check |
|----|-------|------------|-------|
| C1 | 1 | Default SVIS JSON keeps exact legacy structure/order except approved corrections | Golden compatibility tests |
| C2 | 4 | Root CLI shape and `run(Path, Path) -> None` remain through 1.x | Compatibility suite |
| C3 | 1 | Import/help/offline tests acquire no credentials or network | Isolated wheel smoke |
| C4 | 3 | Core imports no provider SDK, Instructor, Docling, or `itsai` types | Architecture checks |
| C5 | 2 | Secrets/questionnaire text do not enter serialization, logs, diagnostics, fixtures, or docs | Redaction and secret scans |
| C6 | final | Python 3.11-3.13 remains supported on Linux/macOS/Windows | CI matrix |
| C7 | 4 | Format/model claims are versioned, capability-aware, and fixture-backed | Capability matrices/tests |
| C8 | 5 | Playground stays static with no upload, key, storage, or live inference | Browser/route checks |
| C9 | final | No publish/deploy permission/action exists without recorded approval | Workflow policy and checklist |
| C10 | 2 | Documents cannot trigger remote fetches, executable content, path escape, or unbounded work | Adversarial source tests |
| C11 | 5 | Actions remain SHA-pinned, least-privilege, Node 24-compatible, and artifact-isolated | Workflow schema/policy and CI annotations |
| C12 | final | No blocked-stop condition is waived, hidden, or converted to success by static inspection | V16 blocker-closure audit and execution report |

### Boundaries

- Allowed: runtime, source/provider adapters, Pydantic models, async pipeline, compatibility shim, CLI, approved fixtures, tests, build-only CI, docs, static playground, and release-candidate artifacts.
- Allowed conditionally: manual protected PyPI Trusted Publishing and Pages deployment after a separate approval record.
- Out of scope: hosted API, managed credentials, multi-tenant infrastructure, public uploads, remote URL ingestion, review/autofix agents, and guaranteed arbitrary-schema quality.
- Out of scope: unapproved publication/deployment, restricted fixtures, credential disclosure, or live provider spending in pull-request tests.

### Iteration Policy

1. Treat Phase 1 and PR #4 as baseline; do not reimplement completed packaging work.
2. Execute remaining phases in dependency order and satisfy each phase evidence gate before advancing.
3. Keep core ports independent from provider/source SDKs.
4. Prefer deterministic fixtures/fakes and isolate approved live/OCR checks.
5. Refresh actions only to reviewed Node 24-compatible immutable SHAs.
6. Under `deviation-policy: ask`, pause before changing public contracts, support tiers, compatibility, quality thresholds, dependencies, or release boundaries.
7. Apply the Blocked-Stop Resolution Matrix with at most two bounded engineering recovery rounds per failure.
8. Require executed evidence; static inspection alone cannot complete required rows.

### Blocked-Stop Conditions

- Continuing would violate legal disposition, fixture rights, secret rules, or publication gate.
- Exact legacy SVIS/CLI compatibility cannot be preserved within approved corrections.
- A required provider/source cannot satisfy the normalized contract on supported Python versions.
- Required OCR, quality, or Survey Solutions fixtures lack rights, checksums, or versioned semantics.
- Transactional artifacts or concurrency isolation cannot be proven.
- Required verification fails after bounded recovery.
- PyPI/Pages activation lacks explicit approval and protected environments; this blocks activation, not prior engineering evidence.
- A required deviation is discovered while user approval is unavailable.
- Any B1-B8 row remains `blocked` at the relevant phase or final evidence gate.
