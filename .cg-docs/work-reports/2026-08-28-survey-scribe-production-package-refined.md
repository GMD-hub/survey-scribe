# Work Report: Survey Scribe Production Package Completion

## Plan Reference

`.cg-docs/plans/2026-08-28-survey-scribe-production-package-refined.md`

## Active Deviation Policy

- Stored policy: `ask`
- Runtime override: none
- Review routing: `auto`

## Runs

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
| V5 | 3 | pending | Not in current phase |
| V6 | 3 | pending | Not in current phase |
| V7 | 4 | pending | Not in current phase |
| V8 | 4 | pending | Not in current phase |
| V9 | 5 | pending | Not in current phase |
| V10 | 5 | pending | Not in current phase |
| V11 | 5 | pending | Not in current phase |
| V12 | 6 | pending | Not in current phase |
| V13 | final | pending | Not in current phase |
| V14 | final | pending | Not in current phase |
| V15 | 6 | optional | Conditional release activation is not authorized |
| V16 | final | pending | Blocker matrix remains open until final completion |

## Constraints Check

| ID | Phase | Status | Actual Check |
| --- | --- | --- | --- |
| C1 | 1 | passed | Preserved Phase 1 compatibility baseline |
| C2 | 4 | pending | Not in current phase |
| C3 | 1 | passed | Preserved Phase 1 import/help/offline evidence |
| C4 | 3 | pending | Not in current phase |
| C5 | 2 | passed | Recursive redaction, config secret omission, and artifact tests passed |
| C6 | final | pending | Not in current phase |
| C7 | 4 | pending | Not in current phase |
| C8 | 5 | pending | Not in current phase |
| C9 | final | pending | Not in current phase |
| C10 | 2 | passed | Source tests covered remote paths/resources, formulas, macros, archive limits, path escape, timeout, and prompt-injection isolation |
| C11 | 5 | pending | Not in current phase |
| C12 | final | pending | Not in current phase |

## Blocked-Stop Matrix

| ID | Status | Closure Evidence |
| --- | --- | --- |
| B1 | not-triggered | Engineering-only Phase 2 scope; publication remains disabled |
| B2 | not-triggered | Compatibility baseline is unchanged at Phase 2 start |
| B3 | not-triggered | Provider adapters are not in current phase |
| B4 | resolved | Synthetic fixtures passed; approved EasyOCR archives were downloaded only to a temporary local cache and validated against recorded sizes/digests |
| B5 | resolved | Artifact collision, concurrent lock, overwrite, and failure-preservation tests passed |
| B6 | resolved | Required Phase 2 suites and the 158-test full-suite gate passed |
| B7 | not-triggered | PyPI and Pages activation is not in current phase |
| B8 | not-triggered | No deviation is known at Phase 2 start |

## Evidence Runs

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
- `review:auto` resolved to `full` because the diff changes credential, filesystem,
  process, path, and schema contracts. All 10 routed agents returned usable output.
- Review report: `.cg-docs/reviews/2026-08-28-survey-scribe-production-package-refined-review.md`.
- Safe autofix: 13 findings fixed; post-fix full suite 190 passed; package tests 4 passed;
  Ruff and Pyright passed.
- Branch coverage check: 190 tests passed, but total branch coverage was 85.65% against
  the configured 95% gate. Finding P1.13 remains open for triage.

## Remaining Uncertainty

- Phases 3-6 remain pending.
- The Phase 2 full review has 20 open manual findings, including crash consistency,
  path/lock hardening, source completeness, OCR runtime integrity, resource controls,
  and coverage.
- No project charter or local project settings file exists.

## Final Status

`active` - Phase 2 is complete; paused before Phase 3.
