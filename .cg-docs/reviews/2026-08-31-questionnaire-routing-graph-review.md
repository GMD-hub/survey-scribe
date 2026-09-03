---
date: 2026-09-02
depth: full
type: standard
plan: .cg-docs/plans/2026-08-31-questionnaire-routing-graph.md
findings:
  P0.1: fixed
  P0.2: fixed
  P0.3: fixed
  P0.4: fixed
  P0.5: skipped
  P1.1: fixed
  P1.2: fixed
  P1.3: fixed
  P1.4: fixed
  P1.5: fixed
  P1.6: fixed
  P1.7: fixed
  P1.8: fixed
  P2.1: fixed
  P2.2: fixed
  P2.3: fixed
  P2.4: fixed
  P2.5: fixed
  P2.6: fixed
  P2.7: fixed
  P2.8: fixed
  P2.9: fixed
  P2.10: skipped
  P2.11: skipped
  P2.12: fixed
  P3.1: skipped
  P3.2: skipped
---

# Review Report: Questionnaire Routing Graph Phase 5

**Review mode**: full
**Files reviewed**: 29
**Findings**: 27 (P0: 5, P1: 8, P2: 12, P3: 2)

## P0 - Blocking

**[P0.1] [manual]** `scripts/evaluate_routing.py:285` - Target and condition metrics are coupled.

**Why**: Target identity includes condition, and condition identity includes target. The two metrics do not isolate wrong-target and wrong-condition errors.

**Fix**: Define deterministic neutral route-slot alignment, then score targets and normalized conditions independently. Add crossed-error tests.

**[P0.2] [manual]** `scripts/evaluate_routing.py:126` - Empty and structurally invalid graph snapshots can certify successfully.

**Why**: Empty stages, terminal outgoing edges, multiple defaults, missing entry/terminal nodes, and invalid loop shapes can match themselves and pass.

**Fix**: Enforce the applicable canonical graph invariants and mandatory nonzero expected evidence before scoring.

**[P0.3] [safe_auto]** `scripts/evaluate_routing.py:343` - Extra or duplicate terminal and loop classifications are not penalized.

**Why**: `AccuracyMetric` omits actual count, and completion checks only expected and matched counts.

**Fix**: Record actual count, reject duplicate loop identities, and require expected, actual, and matched counts to agree.

**[P0.4] [manual]** `scripts/evaluate_routing.py:243` - Opaque and commutative conditions do not have an approved semantic identity.

**Why**: Removing `raw_text` makes all opaque conditions equal, while reordered `all`, `any`, and `in_set` values compare unequal.

**Fix**: Approve and implement type-tagged semantic normalization. Hash normalized opaque source text or exclude opaque conditions from exact-match claims and report their rate.

**[P0.5] [manual]** `scripts/evaluate_routing.py:622` - The evaluated bundle is not bound to the source manifest or production routing output.

**Why**: The source manifest is validated, but the command scores a separate authored snapshot bundle with no source-case or output digest binding.

**Fix**: Bind every evaluation case to source fixture and routed-output digests, and exercise deterministic production routing or independently generated routed artifacts.

## P1 - Critical

**[P1.1] [manual]** `scripts/evaluate_routing.py:373` - Unresolved routes do not reduce precision and have no rate.

**Why**: Unresolved attempts are excluded from the accepted-edge denominator, and the report has no unresolved or opaque rate.

**Fix**: Approve explicit denominators, count unresolved attempts as unmatched predictions where applicable, and report unavailable states.

**[P1.2] [safe_auto]** `scripts/evaluate_routing.py:134` - Accepted condition references are not checked for invention.

**Why**: A condition can reference an unknown question node while accepted source-item invention remains zero.

**Fix**: Recursively validate condition question references against actual and expected inventory identities.

**[P1.3] [safe_auto]** `scripts/evaluate_routing.py:566` - The mechanics manifest boundary is only partially validated.

**Why**: Schema version, artifact kind, provenance, restrictions, unknown keys, strict primitive types, duplicate JSON fields, and manifest symlinks are not all rejected.

**Fix**: Add strict typed manifest validation and duplicate-key JSON parsing with fail-closed path checks.

**[P1.4] [safe_auto]** `scripts/evaluate_routing.py:525` - Scale determinism hashes one object twice and does not run scoring.

**Why**: The check cannot detect nondeterministic construction or evaluator complexity regressions.

**Fix**: Build two independent stages, run full evaluation, compare counts and digests, and retain threshold-free timing and memory evidence.

**[P1.5] [manual]** `scripts/evaluate_routing.py:596` - Report output paths can alias inputs, each other, protected files, or symlinks.

**Why**: Direct writes can overwrite arbitrary files, and identical output paths silently leave only the scale report.

**Fix**: Confine outputs, reject aliases and symlinks, serialize first, and publish both reports atomically.

**[P1.6] [manual]** `tests/package/test_distribution_contents.py:23` - Wheel and sdist checks are broad prefix policies, not exact allowlists.

**Why**: Unapproved files under accepted roots can enter either archive without failing the gate.

**Fix**: Compare normalized regular-file members with exact approved inventories and tightly controlled distribution metadata.

**[P1.7] [manual]** `tests/package/test_clean_install.py:35` - Exact-wheel behavior is not fully bound or isolated.

**Why**: A stale same-version wheel can be selected; schema output is checked only by title; CLI subprocesses retain ambient credentials and lack the socket guard; legacy output is validated but not byte-compared.

**Fix**: Bind the wheel to the current build, compare exact schema and legacy bytes, use a minimal environment, and execute all installed-code checks under network denial.

**[P1.8] [manual]** `tests/fixtures/package/constraints.txt:1` - Wheelhouse dependencies are version-pinned but not hash-bound, and index sanitation is not encoded.

**Why**: Same-version dependency bytes can change, and uv/pip ambient index settings can affect preparation.

**Fix**: Add approved hashes, require hashes, isolate pip configuration, and encode cross-platform index sanitation.

## P2 - Important

**[P2.1] [safe_auto]** `docs/guides/configuration.md:68` - Routing `generation` and `retry` settings are omitted.

**Why**: Top-level and routing-nested values are separate, so users can configure the wrong settings.

**Fix**: Document both fields, nested TOML tables, and router construction.

**[P2.2] [safe_auto]** `docs/evaluation.md:62` - Exact-backend claim language is too broad.

**Why**: Returned metadata from an unpinned dynamic route does not authorize an exact-backend quality claim.

**Fix**: Require a pinned backend; keep dynamic-route claims at gateway-route scope.

**[P2.3] [safe_auto]** `src/survey_scribe/cli.py:18` - Incomplete nested schema commands exit successfully and help text is stale.

**Why**: `survey-scribe schema` returns 0 with top-level help, and parser text says only help/version are supported.

**Fix**: Require the nested command, dispatch the selected exporter explicitly, update docstrings, and add regression tests.

**[P2.4] [safe_auto]** `scripts/evaluate_routing.py:635` - Failed mechanics runs log success.

**Why**: The success message is emitted before the exit status is selected.

**Fix**: Compute status first and emit a fixed success or failure message accordingly.

**[P2.5] [safe_auto]** `scripts/evaluate_routing.py:622` - Source-manifest validation errors can copy untrusted values to logs.

**Why**: Verbatim validator errors can contain fixture identifiers, paths, or line breaks.

**Fix**: Emit fixed error codes or bounded indexes only.

**[P2.6] [manual]** `docs/routing.md:75` - Consumer examples are not complete schema-valid routed examples.

**Why**: Required edge, audit, result, multiple-incoming, default, loop, and outcome fields are absent, and examples use an undefined `survey`.

**Fix**: Add executable synthetic examples or link generated examples that cover the complete routed envelope and outcomes.

**[P2.7] [manual]** `docs/reference/providers.md:1` - The packaged provider adapter and capability construction are not documented.

**Why**: Consumers cannot see safe adapter injection or understand configuration-only capability evidence.

**Fix**: Add a credential-free fake-completion example and document administrator-owned capability rows without claiming live support.

**[P2.8] [safe_auto]** `docs/reference/routing.md:6` - The routing reference omits public serialized types and exact outcome paths.

**Why**: Consumers cannot navigate all enums, audit records, source/evidence models, or routing result status rules.

**Fix**: Add the public graph types, `RoutingConfig`, audit path, routing outcome table, evaluator repository-only note, and separate manifest scopes.

**[P2.9] [manual]** `scripts/evaluate_routing.py:212` - Reports omit exact input and measurement-method provenance.

**Why**: Detached reports do not identify source/mechanics/fixture bytes or state `perf_counter` and `tracemalloc` methods.

**Fix**: Add input digests, evaluator identity, and measurement method fields with tests.

**[P2.10] [manual]** `scripts/evaluate_routing.py:353` - Condition identities are normalized and serialized repeatedly.

**Why**: Complex maximum-size ASTs amplify CPU and memory, and stage hashing builds multiple full-size buffers.

**Fix**: Cache one normalized record per edge and stream canonical hash encoding without changing digest semantics.

**[P2.11] [manual]** `.cg-docs/work-reports/2026-08-31-questionnaire-routing-graph.md:77` - Current-tree Python 3.12 and 3.13 execution evidence is external.

**Why**: Local exact-wheel evidence is Python 3.11 only.

**Fix**: Bind the reviewed commit to successful 3.12 and 3.13 CI matrix runs before merge.

**[P2.12] [manual]** `docs/guides/security.md:185` - The GitHub Actions example uses a nonexistent repository test path.

**Why**: It implies current deterministic tests require provider credentials.

**Fix**: Use a clearly labeled downstream placeholder and state that repository tests are credential-free.

## P3 - Minor

**[P3.1] [advisory]** `.DS_Store` - An ignored macOS metadata file remains tracked from earlier work.

**Why**: Ignore rules do not remove files already in the index.

**Fix**: Remove it from the index in a separate hygiene change.

**[P3.2] [advisory]** `.cg-docs/plans/2026-08-31-questionnaire-routing-graph.md:1115` - The completed plan body retains unchecked documentation checklist boxes, and one old branch commit is nonconventional.

**Why**: These are historical record and branch-hygiene inconsistencies, not Phase 5 runtime defects.

**Fix**: Preserve the approved plan body under current permissions. Use a conventional PR or squash title and avoid rewriting pushed history.

## Passed

- All ten full-route agents produced usable output.
- Full suite before review: 917 passed, 5 expected skips.
- Exact branch coverage before review: 95.12 percent.
- Ruff, Ruff format, Pyright, strict MkDocs, build, Twine, and exact-wheel gates passed before review.
- No live provider call occurred; G6 remains `not_run`.
- `tmp/mai-factory-builder.agent.md` was unchanged.

## Autofix Evidence

- Fixed 10 findings: P0.3, P1.2-P1.4, P2.1-P2.5, and P2.8.
- Added actual classification counts and exact completion checks.
- Added strict mechanics-manifest and duplicate-JSON validation.
- Added recursive condition-reference validation.
- Scale evidence now builds two independent graphs and runs full evaluator scoring.
- Incomplete schema commands now exit with status 2.
- Failed mechanics and source-manifest validation now use fixed failure messages.
- Corrected routing configuration, backend-claim, manifest-scope, result-path, and API-reference documentation.
- Verification: 19 focused tests passed; Ruff passed; Pyright returned 0 errors and 0 warnings; strict MkDocs passed; the deterministic evaluator passed without provider access.
