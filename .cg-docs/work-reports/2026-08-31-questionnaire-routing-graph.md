---
date: 2026-08-31
plan: "../plans/2026-08-31-questionnaire-routing-graph.md"
status: completed
---

# Work Report: Questionnaire Routing Graph

## Run: 2026-08-31

- Started: 2026-08-31T23:20:22Z
- Branch: `feat/questionnaire-skip-pattern-graph`
- Active deviation policy: `ask` (no runtime override)
- Review mode: `auto`
- Project charter: not present; execution continued with the workflow warning

## Completed Steps And Phases

- Plan artifact validation passed.
- Roadmap feature `questionnaire-routing-graph-for-llm-readable-svis` changed from `planned` to `active`.
- Phase 1 Step 1 completed: G1 source completeness, G2 artifact safety, and G5 coverage gates passed.
- Phase 1 Step 2 completed: source-only routing fixtures, rights/provenance manifest, checksum validation, and legacy characterization passed.
- Phase 1 Step 3 completed: strict routed models, extraction contracts, typed legacy projection, and canonical schema passed.
- Phase 1 completed on 2026-09-01.
- Phase 2 Step 4 completed: deterministic inventory, source binding, identity, quote verification, and condition reference resolution passed.
- Phase 2 Step 5 completed: deterministic evidence reconciliation, accepted-only adjacency, candidates, discrepancies, and append-only review passed.
- Phase 2 Step 6 completed: iterative graph integrity, deterministic SCC/loop analysis, and scale evidence passed.
- Phase 2 completed on 2026-09-01.
- Phase 3 Step 7 completed: versioned prompt and strict structured-response contracts passed.
- Phase 3 Step 8 completed: G3 provider contracts, adaptive extraction, shared concurrency, cache isolation, and cited review passed.
- Phase 3 completed on 2026-09-01.
- Phase 4 Step 9 completed: G4 additive native conversion, QuestionnaireRouter pipeline, and real XLSForm relevance/repeat routing passed.
- Phase 4 Step 10 completed: routed manifest v2, durable publication, exact legacy projection, configuration, and stable exports passed.
- Phase 4 completed on 2026-09-01.
- Plan revised on 2026-09-01 to make G6 an optional protected test-capture
  action gate and to separate it from final production configuration.

## Deviations

None.

## Accepted Exceptions

None.

## Evidence

| ID | Phase | Status | Actual evidence |
|---|---:|---|---|
| V1 | 1 | passed | G1/G2 focused suites: 204 passed; exact package-excluded coverage gate: 422 passed, 100.00% coverage; Ruff and Pyright passed |
| V2 | 1 | passed | Routing fixture validator passed; fixture-policy and legacy characterization suites: 38 passed |
| V3 | 1 | passed | Routed model and legacy characterization suite: 129 passed; focused branch coverage 97.04%; schema digest matched |
| V4 | 2 | passed | Identity/inventory/model/characterization verification: 171 passed; focused branch coverage 99.84%; mechanics checksum matched |
| V5 | 2 | passed | Reconciliation/identity/inventory/model verification: 187 passed; focused branch coverage 97.15% |
| V6 | 2 | passed | Validation/reconciliation/model gate: 174 passed; exact coverage: 662 passed at 98.89%; full suite: 666 passed; 1,000-node/3,000-edge scale passed |
| V7 | 3 | passed | Prompt/model/characterization verification: 150 passed; focused prompt branch coverage 100% |
| V8 | 3 | passed | G3 suite: 65 passed, 1 authorized-only skip; exact coverage: 748 passed, 1 skip at 98.34%; full suite: 752 passed, 1 skip |
| V9 | 4 | passed | Exact G4 Step 9 suite: 62 passed; routing regressions: 243 passed; focused branch coverage reported 97.96% |
| V10 | 4 | passed | Routed artifact/public API gate: 66 passed; exact coverage: 833 passed, 1 skip at 97.82%; full suite: 837 passed, 1 skip |
| V11 | 5 | passed | 10 evaluator tests passed; deterministic mechanics command passed; first-pass/post-review separation, unresolved penalties, invention checks, and 1,000-node/3,000-edge scale evidence passed without provider access |
| G6 | 5 | not_run | Optional protected model-quality capture deferred; no real-provider quality claim is permitted |
| V12 | final | passed | Ruff, format, Pyright, exact 95% branch coverage, strict MkDocs, schema drift, build, Twine, exact-wheel, distribution-content, and complete-suite gates passed |

## Constraints Check

| ID | Status | Actual check |
|---|---|---|
| C1 | passed | Legacy characterization, routed projection, exact-wheel, and full suites passed |
| C2 | passed | Routing model, reconciliation, evaluator, and full suites passed |
| C3 | passed | Opaque/unresolved mechanics and invention tests passed; optional provider benchmark remained not_run |
| C4 | passed | Iterative 1,000-node/3,000-edge evaluator and graph tests passed; no graph dependency was added |
| C5 | passed | Provider contract and import-boundary tests passed; provider contract files were unchanged |
| C6 | passed | Extraction orchestration, review audit, evaluator stage-separation, and full suites passed |
| C7 | passed | Native routing and exact-wheel XLSForm zero-provider path passed |
| C8 | passed | Redaction, cache, content-safe evaluator report, artifact, and full suites passed |
| C9 | passed | Public API, dependency boundary, distribution allowlist, and exact-wheel tests passed |
| C10 | passed | Python 3.11 exact-wheel tests and Python 3.11-3.13 metadata/CI policy checks passed; 3.12/3.13 execution remains a CI matrix responsibility |
| C11 | passed | Hierarchy, routing model, validation, pipeline, and full suites passed |
| C12 | passed | Routed version, manifest v1/v2, serialization, and artifact tests passed |
| C13 | passed | Source binding, companion digest, mutation, no-call, pipeline, and exact-wheel tests passed |

## Remaining Uncertainty

- The optional mAI Factory or other live provider capture is deferred. This
  limits model-quality claims but no longer blocks deterministic Phase 5.

## Superseded G6 Block: Phase 5 Step 11

- Time: 2026-09-01T10:07:08Z
- Gate: G6 captured benchmark authorization.
- Decision: no source approved; no model approved; zero budget; no capture approved.
- Effect at the time: no provider call or protected capture was made.
- Revision: G6 now gates only an optional protected live capture. Required V11
  uses deterministic mechanics and scale evidence without provider credentials.
- Resume command: `/cg-work phase5 .cg-docs/plans/2026-08-31-questionnaire-routing-graph.md`.

## Phase 1 Step 1 Evidence

| Finding | Remediation evidence | Result |
|---|---|---|
| P0.7 | Immutable source-unit coverage with complete, partial, and failed states; PDF failed-page tests | passed |
| P0.8 | Final rendered chunk token limit includes overlap; deterministic text split and oversized-table rejection tests | passed |
| P0.9 | Typed table parts preserve pipes, newlines, backslashes, and empty cells | passed |
| P0.11 | Multi-page provenance retained and validated for text and tables | passed |
| P1.8 | Bounded private source snapshots with SHA-256 digest prevent replacement races | passed |
| P0.3 | Staged generations, typed journal, required directory flushes, and hard-exit recovery tests | passed |
| P0.4 | Internal symlink and Windows reparse-point rejection tests | passed on Windows |
| P0.5 | Process-owned lock, contention, crash release, and stale-file tests | passed on Windows |
| P0.6 | Detached identity snapshot, reserved-name, case-alias, and filename safety tests | passed |
| P1.10 | Generic typed serializer/artifact-plan boundary and exact-type SVIS serializer tests | passed |
| P1.13 | Exact `uv run pytest tests --ignore=tests/package --cov=survey_scribe --cov-branch --cov-report=term-missing --cov-fail-under=95` | 422 passed; 100.00% |

Commands:

- `uv run pytest tests/contract/sources tests/integration/test_tier1_sources.py tests/unit/test_artifacts.py tests/unit/test_artifact_serializers.py tests/unit/test_results.py tests/contract/artifacts tests/integration/test_artifact_process_safety.py tests/characterization/test_schema_contract.py tests/characterization/test_legacy_pipeline.py -q` -> 204 passed.
- Exact G5 coverage command -> first run: 289 passed, coverage failed at 91.29%; recovery round 1: 422 passed at 100.00%.
- `uv run ruff check src tests` -> passed.
- `uv run pyright` -> 0 errors, 0 warnings.

Platform note: Windows junction, process lock, crash release, hard-exit recovery, and directory-flush branches executed locally. POSIX-specific `fcntl`, `O_NOFOLLOW`, and directory `fsync` branches require CI evidence.

## Phase 1 Step 2 Evidence

- `uv run python scripts/validate_routing_fixtures.py` -> manifest valid.
- `uv run pytest tests/unit/test_routing_fixture_policy.py tests/characterization/test_schema_contract.py -q` -> 38 passed.
- All 14 required synthetic mechanics cases and the 1,000-item source are present with rights, provenance, SHA-256, path confinement, LF, source-only, and benchmark-ineligible checks.
- No expected evidence, graph, diagnostic, or model-response fixture was added before model and identity contracts were frozen.

## Phase 1 Step 3 And Boundary Evidence

- `uv run pytest tests/unit/test_routing_models.py tests/characterization/test_schema_contract.py -q` -> 129 passed.
- Canonical routing schema SHA-256: `eba98c59a2f66b93369f56d35c9a6b940f631ff50679817097b893aefef998e6`; generated bytes matched the committed fixture.
- Exact package-excluded coverage gate after routed models -> 575 passed; 99.26%.
- Complete suite including package tests -> 579 passed.
- Ruff, Ruff format, Pyright, and diff checks passed.

## Phase 4 Step 9 Evidence

- `uv run --extra tabular pytest tests/contract/sources/test_native_routing.py tests/contract/sources/test_xlsform.py tests/integration/test_routing_pipeline.py -q` -> 62 passed.
- Routing regression verification -> 243 passed.
- XLSForm adapter `survey-scribe/xlsform/1.0`; support matrix `1.0`; supported comparisons, `selected()`, and Boolean operators project exactly; unsupported functions/arithmetic remain typed opaque expressions.
- Real relevance and repeat routing produced zero provider calls; `SourceRegistry.convert()` remains unchanged and `convert_with_native()` is additive.

## Phase 4 Step 10 And Boundary Evidence

- `uv run pytest tests/unit/test_routing_artifacts.py tests/unit/test_artifacts.py tests/characterization/test_schema_contract.py tests/unit/test_public_api.py tests/integration/test_artifact_process_safety.py -q` -> 66 passed.
- Exact package-excluded coverage gate -> 833 passed, 1 protected live smoke skipped; 97.82%.
- Complete suite including package tests -> 837 passed, 1 skip.
- Routed manifest v2 and legacy v1 parsers, typed v1 projection, hard-exit recovery, collision/concurrency, redaction, import, and public API checks passed.
- Ruff, Ruff format, Pyright, and diff checks passed.

## Phase 3 Step 7 Evidence

- `uv run pytest tests/unit/test_routing_prompts.py tests/unit/test_routing_models.py tests/characterization/test_schema_contract.py -q` -> 150 passed.
- Focused prompt branch coverage -> 100%.
- Prompt versions: system, forward, incoming/activation, and reviewer are `1.0.0`; deterministic hashes recorded in tests.
- Ruff and Pyright passed.

## Phase 3 Step 8 And Boundary Evidence

- `uv run --extra openai pytest tests/integration/test_routing_extraction.py tests/contract/providers -q` -> 65 passed, 1 protected live smoke skipped because no explicit authorization was present.
- Canonical/request schema hashes: evidence `2931e8f52efd0667ae72376b950195a9a1a8cb9ae6e5c9078c8320408158009c` / `3cf5f34907c786d203bcf0a66b1c2a675b4c1d5b558c884848d9587eb6736d36`; reviewer `68a1def75af90fcd45127e7c3d66ce244cf30e111137be4935cdedd7d2f2415a` / `e8a95276328f3febbae3b7dc7fccd7ad07b50f86a302eb1ba4938adc69161bc4`.
- Exact package-excluded coverage gate -> 748 passed, 1 skip; 98.34%.
- Complete suite including package tests -> 752 passed, 1 skip.
- Ruff, Ruff format, Pyright, and diff checks passed.
- Legacy package and model exports remain unchanged until the exact-wheel export gate.

## Phase 2 Step 4 Evidence

- `uv run pytest tests/unit/test_routing_inventory.py tests/unit/test_routing_identity.py tests/unit/test_routing_models.py tests/characterization/test_schema_contract.py -q` -> 171 passed.
- Focused identity/inventory coverage -> 42 passed; 99.84%.
- Mechanics fixture SHA-256: `f9b2aaeea7dbc85b6cceebf92d06199e6085eb94e1a68bba8608cc0940a462c3`; manifest matched.
- Ruff and Pyright passed.

## Phase 2 Step 6 And Boundary Evidence

- `uv run pytest tests/unit/test_routing_validation.py tests/unit/test_routing_reconcile.py tests/unit/test_routing_models.py tests/characterization/test_schema_contract.py -q` -> 174 passed.
- Exact package-excluded coverage gate -> 662 passed; 98.89%.
- Complete suite including package tests -> 666 passed.
- Scale test -> 1,000 nodes, 3,000 accepted edges, deterministic across two runs, no recursion, 4.79 MiB peak traced Python allocation; no timing threshold.
- Ruff, Ruff format, Pyright, and diff checks passed.

## Phase 2 Step 5 Evidence

- `uv run pytest tests/unit/test_routing_reconcile.py tests/unit/test_routing_identity.py tests/unit/test_routing_inventory.py tests/unit/test_routing_models.py -q` -> 187 passed.
- Focused reconciliation branch coverage -> 97.15%.
- Ruff and Pyright passed.

## Final Status

Completed on 2026-09-02. V1-V12 passed. Optional G6 remained `not_run`, so this
report makes no live-provider, mAI Factory, gateway-route, or exact-model quality
claim.

## Resume: 2026-09-02

- Started: 2026-09-02T02:42:33Z
- Branch: `feat/questionnaire-skip-pattern-graph`
- Scope: Phase 5 Steps 11 and 12 only
- Active deviation policy: `ask` (no runtime override)
- Review mode: `manual`
- Canonical plan validation: passed
- Roadmap feature status: already `active`; no roadmap write required
- G6: `not_run`; this run uses synthetic fixtures only and permits no live-provider or exact-model quality claim
- Open evidence at resume: V11 and V12

## Phase 5 Step 11 Evidence

- Completed: 2026-09-02T02:58:36Z
- Red phase: `uv run pytest tests/unit/test_evaluate_routing.py -q` failed at collection with `ModuleNotFoundError: No module named 'scripts.evaluate_routing'`.
- Focused evaluator suite: `uv run pytest tests/unit/test_evaluate_routing.py -q` -> 10 passed.
- Required mechanics command: `uv run python scripts/evaluate_routing.py --manifest tests/fixtures/routing/manifest.toml` -> passed without provider access.
- First pass: 5/6 accepted edges matched; edge recall and target accuracy were 0.833333; one unresolved route was retained; normalized condition exact match was 0/1; invented accepted source IDs were 0.
- Post review: 6/6 accepted edges, 6/6 targets, 1/1 normalized conditions, 1/1 terminal classes, and 1/1 loop classes matched; unresolved routes and invented accepted source IDs were 0.
- Review effect: edge recall and target accuracy each increased by 0.166667; condition exact match increased by 1.0; first-pass precision remained visible at 1.0.
- Scale evidence: 1,000 nodes and 3,000 edges; deterministic semantic SHA-256 `77d5fcfc76511c75da06ad5c6a6114b1a3ad4a9ed38be05970975f83b4c8c4c9`; Python 3.11.15 on macOS arm64; 0.107451 seconds; 5,754,435 peak traced bytes; no timing threshold.
- Focused Ruff check and format check passed. Focused Pyright returned 0 errors and 0 warnings.
- G6 remained `not_run`. No provider, credential, gateway, mAI Factory, or exact-model quality operation occurred or is claimed.

## Phase 5 Step 12 And Boundary Evidence

- Completed: 2026-09-02T03:26:29Z
- Red phase: `uv run pytest tests/unit/test_cli.py -q` failed because `schema export routing` was not yet accepted by the CLI.
- Focused schema/evaluator/model suite: 141 passed.
- Routing schema CLI output exactly matched `tests/fixtures/routing/schema/questionnaire-routing-graph-v1.0.json`.
- `uv run ruff check .` -> passed; `uv run ruff format --check .` -> 91 files formatted.
- `uv run pyright` -> 0 errors and 0 warnings.
- `uv run mkdocs build --strict` -> passed.
- Exact package-excluded coverage command -> 913 passed, 5 skipped, total branch coverage 95.12%.
- Removed stale current-version distributions; `uv build` produced one wheel and one sdist.
- `uv run twine check --strict dist/*` -> both distributions passed.
- Credential-free wheelhouse preparation completed with the exact seven constrained dependencies.
- `uv run pytest tests/package` -> 4 passed. The isolated exact wheel ran native XLSForm routing, routed manifest v2 parsing, exact legacy projection validation, CLI help, and routing-schema export with network denied after wheelhouse preparation.
- Complete suite: `uv run pytest tests` -> 917 passed and 5 expected skips.
- Expected skips: optional protected live provider smoke, unavailable approved local OCR cache, and Windows-only durable replacement/directory flush branches.
- Distribution allowlists confirmed that routing/provider-contract/native/serialization runtime modules are present and evaluator code, fixtures, reports, captures, `.cg-docs`, docs, tests, scripts, and `tmp` are absent.
- Ambient `UV_INDEX`, `UV_INDEX_URL`, and `UV_EXTRA_INDEX_URL` were removed from package commands because the inherited private index value was malformed. Repository and user configuration were not changed.
- G6 remained `not_run`; no live provider was called and no mAI Factory, gateway-route, or exact-model quality claim was made.

## Completion Record

- Phase 5 was appended to `completed-phases` before `current-phase` was removed.
- The plan was marked completed with `completed-date: 2026-09-02` and passed canonical artifact validation.
- Roadmap feature `questionnaire-routing-graph-for-llm-readable-svis` was verified as `done`.
- Mechanical self-review found no debug statements, added TODO markers, broken imports, or hardcoded secrets.
- Recommended review mode: `full` because the diff adds schema export and changes package/install evidence boundaries. No review agent was dispatched under `review:manual`.
