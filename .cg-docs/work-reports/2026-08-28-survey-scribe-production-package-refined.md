# Work Report: Survey Scribe Production Package Completion

## Plan Reference

`.cg-docs/plans/2026-08-28-survey-scribe-production-package-refined.md`

## Active Deviation Policy

- Stored policy: `ask`
- Runtime override: none
- Review routing: `auto`

## Runs

### 2026-09-03: Phase 4-5 Resume

- Branch: `production-package-phase4-5`
- Scope: Phases 4 and 5, as explicitly requested
- Plan artifact validation: passed
- Project charter: unavailable; execution proceeds under the plan and workflow contracts
- Brain findings: preserve provider boundaries and test editable checkout, wheel, and sdist as separate filesystems
- Roadmap feature: `complete-survey-scribe-production-package` remains `active`
- Baseline: Phase 3 is complete; Phase 4 starts with the public SDK, custom pipelines,
  compatibility shim, and core XLSForm adapter.

### 2026-09-03: Phase 3 Resume

- Branch: `provider-runtime-phase3`
- Scope: Phase 3 only, as explicitly requested
- Plan artifact validation: passed
- Project charter: unavailable; execution proceeds under the plan and workflow contracts
- Brain findings: preserve provider SDK adapter boundaries and exact-artifact isolation
- Roadmap feature: `complete-survey-scribe-production-package` remains `active`
- Baseline: the clean branch contains the merged routing provider port and orchestration work;
  Azure/Anthropic adapters, named OpenAI-compatible presets, and the SVIS quality pipeline
  remain open for V5/V6 completion.

### 2026-08-28: Phase 2 Run

- Branch: `main`
- Scope: Phase 2, the first incomplete phase
- Plan artifact validation: passed
- Project charter: unavailable; execution proceeds under the plan and workflow contracts
- Brain findings: apply exact-artifact isolation and preserve SVIS-first adapter boundaries
- Roadmap feature: `complete-survey-scribe-production-package` set to `active`

## Completed Steps And Phases

- Phase 1 was completed under the superseded plan and is preserved as baseline.
- 2026-08-28: Phase 2, Step 3 completed. Added strict configuration resolution,
  frozen typed results and diagnostics, typed errors, legacy serialization, and
  transactional generation-based artifact writes with redaction and locking.
- 2026-08-28: Phase 2, Step 4 completed. Added local-only Tier 1 source ports,
  document/tabular/PDF adapters, deterministic provenance and chunking, resource
  and path controls, killable PDF conversion, and offline OCR artifact validation.
- 2026-08-28: Phase 2 completed. The full suite passed with 158 tests; next phase is Phase 3.
- 2026-09-03: Phase 3, Step 5 completed. Added reviewed OpenAI/OpenRouter/Vercel/custom
  presets, an Azure OpenAI adapter with refreshable token callbacks, an optional Anthropic
  adapter, strict capability checks, lazy SDK boundaries, and provider capability docs.
- 2026-09-03: Phase 3, Step 6 completed. Added deterministic async SVIS metadata/block
  extraction, one global concurrency ceiling, stable source ordering, cancellation,
  failure accounting, and the fixed quality-action policy.
- 2026-09-03: Phase 3 completed. The full suite passed with 939 tests; next phase is Phase 4.
- 2026-09-03: Phase 4, Step 7 completed. Added the typed sync/async `SurveyScribe`
  facade, stable bounded batch conversion, provider lifecycle management, generic custom
  structured pipelines, and the sole lazy deprecated root compatibility shim.
- 2026-09-03: Phase 4, Step 8 completed. Promoted XLSForm to package-native core support
  with deterministic native SVIS semantics, shared deadlines, strict nesting, explicit
  unsupported-feature diagnostics, versioned fixtures, and a dedicated support matrix.
- 2026-09-03: Phase 4 completed. The full suite passed with 989 tests and 5 expected
  skips; next phase is Phase 5.
- 2026-09-04: Phase 5, Step 9 completed. Added the installed `convert`, `batch`,
  `providers`, `config check`, and `schema export` commands with redacted summaries,
  deterministic batch manifests, artifact controls, and strict/default exit contracts.
- 2026-09-04: Phase 5, Step 10 completed locally. Added deterministic quality evidence,
  scanner collection plus one authoritative offline security-policy exit, SBOM and archive
  checks, reviewed Node 24 action pins, and workflow-policy enforcement with the recorded
  Pages-only exception.
- 2026-09-04: Phase 5, Step 11 completed. Added current executable guides and generated
  schemas plus a synthetic precomputed static playground with offline link, route,
  keyboard, mobile, network, storage, and WCAG-focused Chromium checks.
- 2026-09-04: Phase 5 local completion gate passed with 1,052 tests and 5 expected
  skips at 95.26% branch coverage. Remote CI status remains deferred until the requested
  commit, push, PR, wait, and `/cg-verify-pr` operations.

## Deviations

- None.

## Accepted Exceptions

- None.

## Evidence

| ID | Phase | Status | Actual Evidence |
| --- | --- | --- | --- |
| V1 | 1 | passed | Preserved Phase 1 report and merged PR #4 baseline |
| V2 | 1 | passed | Preserved Phase 1 package, compatibility, and CI evidence |
| V3 | 2 | passed | 40 config/result/artifact unit tests passed on Python 3.11.15 |
| V4 | 2 | passed | 47 source contract/integration tests passed; both approved OCR archive sizes and SHA-256 digests validated in a temporary local cache |
| V5 | 3 | passed | 34 provider contract tests passed with one protected live-smoke skip; OpenAI-compatible, Azure callback, Anthropic, capability, retry, truncation, redaction, and lazy-import contracts passed |
| V6 | 3 | passed | 5 direct pipeline/quality tests and 66 combined orchestration tests passed; final full suite passed 939 tests with stable ordering, bounded concurrency, cancellation, quality, and status evidence |
| V7 | 4 | passed | 34 focused public API, compatibility, architecture, and characterization tests passed; the final full suite passed 989 tests; Ruff and Pyright passed; wheel/sdist and all 6 package tests passed |
| V8 | 4 | passed | 70 direct XLSForm contract tests passed with native-authority, deterministic fixture, logic, nesting, workbook-security, and diagnostics coverage; strict MkDocs build passed |
| V9 | 5 | passed | 24 required CLI tests and 38 combined CLI/compatibility/package tests passed; all installed commands, redaction, artifact, collision, strict, and aggregate-exit contracts passed |
| V10 | 5 | local-passed | 1,052 offline tests passed with 5 expected skips and 95.26% branch coverage; Ruff, format, Pyright, deterministic quality, authoritative offline security verification, workflow policy, wheel/sdist, Twine, wheel contents, package install, SBOM, lock, and golden-manifest gates passed; remote CI annotation evidence deferred until PR verification |
| V11 | 5 | passed | Three generated schema artifacts were current; strict MkDocs passed; 12 offline docs/browser tests covered 31 routes; 238 internal URLs passed; Chromium verified mobile/desktop, keyboard, accessibility, static-playground, no-storage, and no-network contracts |
| V12 | 6 | pending | Not in current phase |
| V13 | final | pending | Not in current phase |
| V14 | final | pending | Not in current phase |
| V15 | 6 | optional | Conditional release activation is not authorized |
| V16 | final | pending | Blocker matrix remains open until final completion |

## Constraints Check

| ID | Phase | Status | Actual Check |
| --- | --- | --- | --- |
| C1 | 1 | passed | Preserved Phase 1 compatibility baseline |
| C2 | 4 | passed | Top-level public API is SVIS-only; generic structured extraction remains in opt-in custom pipeline classes |
| C3 | 1 | passed | Preserved Phase 1 import/help/offline evidence |
| C4 | 3 | passed | AST import-boundary contracts passed for the SVIS and routing pipelines; provider SDK imports remain lazy inside adapters |
| C5 | 2 | passed | Recursive redaction, config secret omission, and artifact tests passed |
| C6 | final | pending | Not in current phase |
| C7 | 4 | passed | `docling_pipeline.py` is the sole lazy deprecated compatibility shim; unsafe legacy agents, extractors, and schema bridges were removed |
| C8 | 5 | passed | Source and Chromium route tests reject upload/key/storage/backend/network/live-inference paths; the playground uses only embedded synthetic precomputed data |
| C9 | final | pending | Not in current phase |
| C10 | 2 | passed | Source tests covered remote paths/resources, formulas, macros, archive limits, path escape, timeout, and prompt-injection isolation |
| C11 | 5 | local-passed | Workflow policy passed with reviewed immutable Node 24-compatible action pins, read-only build/test permissions, bounded artifacts, and the recorded Pages-only permission exception; remote annotation check deferred to PR verification |
| C12 | final | pending | Not in current phase |

## Blocked-Stop Matrix

| ID | Status | Closure Evidence |
| --- | --- | --- |
| B1 | not-triggered | Engineering-only Phase 2 scope; publication remains disabled |
| B2 | resolved | The final Phase 4 compatibility, architecture, and full regression suites passed after the approved legacy-to-package cutover |
| B3 | resolved | Provider contracts passed for named OpenAI-compatible presets, Azure key/token callback, and optional Anthropic adapters |
| B4 | resolved | Synthetic fixtures passed; approved EasyOCR archives were downloaded only to a temporary local cache and validated against recorded sizes/digests |
| B5 | resolved | Artifact collision, concurrent lock, overwrite, and failure-preservation tests passed |
| B6 | resolved | Required Phase 5 suites passed after one environment-index recovery and one test-run timeout retry; no assertion or policy was weakened |
| B7 | resolved | PyPI publication remains absent; the existing Pages-only workflow is covered by the separate recorded 2026-08-31 authorization and passed least-privilege workflow policy |
| B8 | not-triggered | Phases 4-5 completed without an approval-requiring deviation |

## Evidence Runs

- Phase 4 plan validation: passed.
- Phase 4 required-path red phase: failed because `tests/integration/test_public_api.py`,
  `tests/compat`, and `tests/architecture` do not exist yet.
- Phase 4 baseline: 941 tests passed and 5 expected skips; six package tests initially
  failed because build artifacts were absent.
- Baseline Ruff and Pyright checks: passed.
- Recovery: built the exact wheel/sdist and prepared the locked offline wheelhouse with
  ambient `UV_INDEX` removed; all 6 package tests passed.
- Existing XLSForm contract baseline: 36 passed.
- Step 7 focused public API, compatibility, architecture, and characterization gate:
  34 passed; Ruff and Pyright passed.
- Step 8 direct XLSForm contract suite: 70 passed.
- Final Phase 4 exact gate: 91 passed.
- Final Phase 4 full suite: 989 passed, 5 expected skips.
- Final Phase 4 package evidence: wheel and sdist built; 6 package tests passed;
  both distributions passed strict Twine checks.
- Final Phase 4 strict MkDocs build and `uv lock --check`: passed.
- Step 9 required CLI and legacy CLI gate: 24 passed; combined CLI, compatibility,
  and package gate: 38 passed.
- Step 10 focused security, quality, workflow, package, docs, and browser gate:
  29 passed; deterministic quality and authoritative offline security policy passed.
- Step 11 generated-reference check: 3 artifacts current; strict MkDocs passed;
  offline docs/browser gate: 12 passed; internal link checker: 238 URLs, 0 errors.
- Final Phase 5 product-contract gate: 132 passed.
- Final Phase 5 offline suite: 1,052 passed, 5 expected skips, 95.26% branch coverage.
  The first run exceeded the 120-second runner limit at 97%; the unchanged rerun passed
  with a 300-second limit.
- Final Phase 5 security collection and network-blocked verification: passed.
- Final Phase 5 artifact evidence: wheel and sdist built; strict Twine and
  check-wheel-contents passed; 6 exact-artifact package tests passed; CycloneDX SBOM generated.
- Final Phase 5 Ruff lint/format, Pyright, workflow policy, lockfile, golden manifest,
  generated-reference, strict MkDocs, and `git diff --check` gates: passed.
- Phase 4-5 light verification review: 17 open findings (P0: 4, P1: 5, P2: 8).
  Report: `.cg-docs/reviews/2026-08-28-survey-scribe-production-package-refined-verify-review-4.md`.
- `cg-render-artifact --validate-only .cg-docs/plans/2026-08-28-survey-scribe-production-package-refined.md`: passed.
- `uv run pytest tests/unit/test_config.py tests/unit/test_results.py tests/unit/test_artifacts.py`: 40 passed.
- Targeted Ruff lint/format checks: passed.
- Targeted Pyright check: 0 errors and 0 warnings.
- `git diff --check`: passed; Git emitted only line-ending conversion warnings.
- Initial `uv run python scripts/validate_ocr_artifacts.py`: exited 2 because no local OCR cache was configured.
- Recovery: downloaded the two plan-approved EasyOCR release archives to an external temporary cache without adding them to the repository.
- `SURVEY_SCRIBE_OCR_CACHE=<temporary-cache> uv run python scripts/validate_ocr_artifacts.py`: 2/2 artifacts valid.
- `uv run pytest tests/contract/sources tests/integration/test_tier1_sources.py`: 47 passed.
- `uv run --extra tabular` real openpyxl adapter smoke: passed with two deterministic rows.
- Phase 2 Ruff lint and format checks: passed across 23 files.
- Project Pyright check: 0 errors and 0 warnings.
- Phase 2 full-suite gate: 158 passed.
- Phase 3 plan validation: passed.
- Provider adapter red phase: collection failed because Azure and Anthropic modules did not exist.
- Pipeline/quality red phase: collection failed because `survey_scribe.pipeline` did not exist.
- `uv run pytest tests/contract/providers`: 34 passed, 1 protected live-smoke skip.
- Phase 3 orchestration gate: 102 passed, 1 protected live-smoke skip.
- Exact wheel/sdist build and Twine checks: passed; package tests: 6 passed.
- Phase 3 Ruff lint/format, project Pyright, strict MkDocs, and `git diff --check`: passed.
- Final Phase 3 full-suite gate: 939 passed, 5 expected skips.
- `review:auto` resolved to `full` because the diff changes credential, filesystem,
  process, path, and schema contracts. All 10 routed agents returned usable output.
- Review report: `.cg-docs/reviews/2026-08-28-survey-scribe-production-package-refined-review.md`.
- Safe autofix: 13 findings fixed; post-fix full suite 190 passed; package tests 4 passed;
  Ruff and Pyright passed.
- Branch coverage check: 190 tests passed, but total branch coverage was 85.65% against
  the configured 95% gate. Finding P1.13 remains open for triage.

## Remaining Uncertainty

- Phase 6 and final release hardening remain pending.
- Remote CI and Node-runtime annotation evidence will be collected after this branch is
  committed, pushed, and opened as a pull request.
- Live provider schema smoke remains optional and protected; no live model row is advertised as verified.
- Real-document accuracy metrics remain unavailable until an approved evaluation corpus exists;
  deterministic quality output reports those rows as unavailable rather than passing them.
- No project charter or local project settings file exists.

## Final Status

`handoff` - Phases 4-5 implementation is complete; verification findings await fix triage.
