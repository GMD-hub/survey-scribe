# Work Report: Survey Scribe Production Python Package

## Plan Reference

`.cg-docs/plans/2026-08-26-survey-scribe-production-package.md`

## Active Deviation Policy

- Stored policy: `ask`
- Runtime override: none
- Review routing: `auto`

## Runs

### 2026-08-26: Initial Phase 1 Run

- Branch: `feat/survey-scribe-production-package`
- Legacy baseline commit: `6aa09189a9c36165d72dde3c53db0fab9628fce4`
- Legacy dependency source: broad lower bounds in `requirements.txt`; the
  characterized schema ran with Pydantic 2.11.7 in the Phase 1 environment
- Scope: Phase 1, the first incomplete phase
- Plan artifact validation: passed
- Project charter: unavailable; execution proceeds under the plan and workflow contracts
- Brain findings: no Brain index exists
- Roadmap match: none

## Completed Steps And Phases

- 2026-08-26: Phase 1, Step 1 completed. Recorded limited legal authorization,
  synthetic-only fixture rights, checksum policy, numeric thresholds, and exact
  dependency/OCR selections. Standalone probes passed on Python 3.11.15,
  3.12.13, and 3.13.13 on Darwin arm64.
- 2026-08-26: Phase 1, Step 2 completed. Added Hatchling/uv `src/` packaging,
  packaged the unchanged SVIS behavior, retained a temporary legacy re-export,
  captured characterization, added build-only CI, and passed package gates.
- 2026-08-26: Phase 1 completed. Next phase is Phase 2.

## Deviations

- None.

## Accepted Exceptions

- None.

## Evidence

| ID | Phase | Status | Actual Evidence |
| --- | --- | --- | --- |
| V1 | 1 | passed | `docs/legal-disposition.md`; golden manifest and thresholds validated; dependency probes passed on Python 3.11-3.13 |
| V2 | 1 | passed | 43 targeted tests passed; wheel/sdist built; offline clean-install test passed |
| V3 | 2 | pending | Not in current phase |
| V4 | 2 | pending | Not in current phase |
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

## Constraints Check

| ID | Phase | Status | Actual Check |
| --- | --- | --- | --- |
| C1 | 1 | passed | Exact fixed-clock fixture and intentional-corrections policy passed characterization |
| C2 | 4 | pending | Not in current phase |
| C3 | 1 | passed | Package import/help tests passed without provider extras; clean wheel install passed offline |
| C4 | 3 | pending | Not in current phase |
| C5 | 2 | pending | Not in current phase |
| C6 | final | pending | Not in current phase |
| C7 | 4 | pending | Not in current phase |
| C8 | 5 | pending | Not in current phase |
| C9 | final | pending | Not in current phase |
| C10 | 2 | pending | Not in current phase |

## Evidence Runs

- `cg-render-artifact --validate-only <plan>`: passed.
- Golden manifest validator: passed after isolating `uv` from an environment-level index override.
- Dependency API probes: passed on Python 3.11.15, 3.12.13, and 3.13.13 on
  Darwin arm64. OCR model artifacts and real OCR were not exercised.
- Characterization and schema tests: 43 passed.
- Full test suite: 44 passed.
- Ruff: passed after one diagnostics fix plus import-order formatting.
- Pyright: 0 errors, 0 warnings.
- `uv lock --check`: passed.
- `uv build`: produced wheel and sdist.
- Offline clean-install test: 1 passed.
- `git diff --check`: passed.

## Remaining Uncertainty

- Formal copyright, licensing, and contribution provenance remain unresolved;
  the recorded authorization is limited to this engineering branch and pull request.
- No approved real questionnaire corpus exists, so real-document extraction
  quality and dense-table recall are not established by Phase 1.
- OCR package imports passed, but model artifacts and real OCR are later-phase evidence.
- Phases 2-6 remain pending.

## Final Status

`active` - Phase 1 complete; paused before Phase 2.
