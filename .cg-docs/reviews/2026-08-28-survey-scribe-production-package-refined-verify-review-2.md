---
date: 2026-09-01
depth: light
parent-review: .cg-docs/reviews/2026-08-28-survey-scribe-production-package-refined-review.md
type: verification
findings:
  P0.1: open
  P0.2: open
  P0.3: open
  P0.4: open
  P0.5: open
  P0.6: open
  P0.7: open
  P0.8: open
  P0.9: open
  P0.10: open
  P1.1: open
  P1.2: open
  P1.3: open
  P1.4: open
  P1.5: open
  P1.6: open
  P1.7: open
  P1.8: open
  P1.9: open
  P1.10: open
  P1.11: open
  P1.12: open
  P1.13: open
  P1.14: open
  P1.15: open
  P1.16: open
  P2.1: open
  P2.2: open
  P2.3: open
  P2.4: open
  P2.5: open
  P2.6: open
---

# Verification Review: Questionnaire Routing Graph

**Review mode**: light verification
**Parent review**: `.cg-docs/reviews/2026-08-28-survey-scribe-production-package-refined-review.md`
**Files reviewed**: all current tracked and untracked implementation, test, fixture, documentation, and workflow-state changes
**Findings**: 32 (P0: 10, P1: 16, P2: 6, P3: 0)

## P0 - Blocking

### **[P0.1]** `src/survey_scribe/serialization/artifacts.py:1048` - Internal path checks have check-use races

Parent components are checked with `lstat()` and then used through separate path-based operations. A concurrent symlink or Windows reparse-point replacement can redirect generation, journal, projection, or recovery writes. Use retained descriptor-relative POSIX operations and reparse-safe Windows handles, with hostile concurrent-swap tests.

### **[P0.2]** `src/survey_scribe/serialization/artifacts.py:518` - A hard exit can expose mismatched public generations

Stable projections are replaced before `active.json`. A hard exit can leave new stable JSON with an old pointer until another writer performs recovery. Use one authoritative reader-visible commit marker or run recovery before every public read, and inspect consistency immediately after process exit without a recovery write.

### **[P0.3]** `src/survey_scribe/sources/docling.py:299` - DOCX containers can disappear while coverage reports success

Only direct paragraphs and tables under `w:body` are traversed. Nonempty content controls and other common containers can be omitted. Traverse supported containers in document order or return failed-unit diagnostics for every unsupported nonempty container.

### **[P0.4]** `src/survey_scribe/sources/docling.py:703` - Markdown table parsing corrupts escaped cells

Direct splitting on `|` changes escaped pipes into extra cells, including Docling table Markdown. Use an escape-aware parser or Docling structured cells and add round-trip cases for escaped pipes, backslashes, newlines, and code spans.

### **[P0.5]** `src/survey_scribe/routing/reconcile.py:536` - Independent sibling branches are treated as conflicts

Every outgoing claim is compared with every incoming claim from the same source. Two valid predicate/target branches can therefore become `CONFLICTING_TARGET` candidates with no accepted edges. Match evidence by normalized predicate, kind, priority, and branch identity before comparing targets.

### **[P0.6]** `src/survey_scribe/routing/pipeline.py:267` - Document variables receive fabricated positional links

Question-like references are collected in source order and zipped to variables. Instructions can supply the wrong `Qn`, and missing candidates can create questions from arbitrary blocks. Require exact source-verified identity matching and leave unmatched variables null with `UNLINKED_VARIABLE`.

### **[P0.7]** `src/survey_scribe/sources/xlsform.py:258` - XLSForm calculations become flow questions

`calculate` rows default to question nodes and can receive variable links and sequential edges, although the support matrix marks calculations as preserved but not flow. Keep calculations in native records only and exclude them from logical flow inventory.

### **[P0.8]** `src/survey_scribe/models/routing.py:562` - Accepted edges can cite unrelated evidence

Final graph validation checks that evidence IDs exist but not that evidence source, target, kind, and condition match the accepted edge. Cross-check each edge against its evidence or active review decision and add negative round-trip/artifact tests.

### **[P0.9]** `src/survey_scribe/models/routing.py:865` - Routed variable links can disagree with inventory

`routing_node_id` is checked only for an existing question node. It is not required to match the variable-index link recorded in the inventory. Derive the inventory link map and require exact agreement, including missing-record rejection.

### **[P0.10]** `src/survey_scribe/serialization/artifacts.py:693` - The process lock pathname can be replaced

The OS lock protects an opened inode or handle, not a pathname that another process can replace. Lock a secured stable object, verify its identity through the transaction, and add a hostile lock-replacement process test.

## P1 - Critical

### **[P1.1]** `src/survey_scribe/serialization/artifacts.py:787` - Legacy and generic sidecars can retain source prose

Redaction derives sensitive values mainly from successful `question_text`. Failed blocks and diagnostics can contain labels, raw references, quotes, expressions, or adapter text. Use fixed operational templates or carry every request-boundary source string into redaction, with adversarial legacy/generic tests.

### **[P1.2]** `src/survey_scribe/sources/docling.py:97` - OCR artifact integrity is not enforced at runtime

Conversion accepts an existing artifact directory without proving the exact files Docling consumes or the intended English-only configuration. Use one validated resolver, verify required paths and digests, configure languages explicitly, and keep a network-blocked real smoke.

### **[P1.3]** `src/survey_scribe/sources/docling.py:468` - PDF byte-pattern preflight is not authoritative

Raw page and encryption searches can miss object-stream metadata. Use a bounded PDFium preflight worker and enforce page and encryption limits before OCR starts.

### **[P1.4]** `src/survey_scribe/sources/docling.py:404` - A crashed PDF worker can consume the full deadline

Queue waiting does not observe the process sentinel, and cleanup lacks a fully bounded terminate/kill/join sequence. Wait on both result IPC and process exit and bound every cleanup stage.

### **[P1.5]** `src/survey_scribe/sources/docling.py:299` - Table cell ceilings do not cover all formats

DOCX, HTML, Markdown, and PDF tables can exceed `max_cells`; only CSV and XLSX enforce the cumulative limit. Apply one shared cumulative cell budget during parsing and before worker transfer.

### **[P1.6]** `src/survey_scribe/sources/base.py:419` - Archive and XML resource bombs remain possible

ZIP entries and DOCX XML are materialized without entry-count, filename, depth, element, or relevant-part byte ceilings. Add bounded streaming checks under the conversion deadline.

### **[P1.7]** `src/survey_scribe/results.py:61` - Frozen diagnostics contain mutable arbitrary details

`details` remains a mutable `dict[str, Any]` and can hold nondeterministic or non-JSON data. Validate finite string-keyed JSON values and recursively freeze mappings and sequences.

### **[P1.8]** `src/survey_scribe/routing/extraction.py:973` - Cross-section Pass B omits predecessor context

Pass B receives the target section but not the possible predecessor section or source window. Include a bounded predecessor neighborhood that is selected independently of Pass A, and assert packet contents.

### **[P1.9]** `src/survey_scribe/routing/review.py:136` - Replacement references can contradict canonical targets

Endpoint IDs are validated for existence, but `target_reference` need not resolve to `target_node_id`. Resolve the reference through `IdentityResolver` and require an exact match before applying the decision.

### **[P1.10]** `src/survey_scribe/sources/registry.py:153` - Source bindings exclude companion-file content

The binding uses only the primary digest, although XLSForm companion data changes native records. Bind a canonical framed digest of the primary source plus ordered companion roles, paths, and digests; test mutation, addition, removal, and reordering.

### **[P1.11]** `src/survey_scribe/providers/openai_compatible.py:159` - Recorded strict schema is not sent on the wire

The inspected transformed schema is not used by the Instructor request, which receives only the response model and no explicit strict schema mode. Configure the exact provider mode and compare a transport-spied wire schema to the recorded hash.

### **[P1.12]** `src/survey_scribe/routing/review.py:95` - Overlapping decisions can violate append-only supersession

Multiple discrepancies for one candidate create decisions with no predecessor link. Coalesce overlaps or assign deterministic `supersedes_decision_id` values within and across packets.

### **[P1.13]** `src/survey_scribe/routing/reconcile.py:225` - Public validation does not receive known category codes

Finite category coverage works only in direct validator tests. Map SVIS category codes to linked question nodes and pass them through reconciliation/final validation, with exhaustive and missing-code end-to-end tests.

### **[P1.14]** `src/survey_scribe/routing/pipeline.py:93` - `aroute()` blocks the event loop during source conversion

Synchronous PDF, DOCX, and XLSX conversion runs directly in the async method. Offload it through `asyncio.to_thread()` or provide an async source boundary, with ticker and cancellation tests.

### **[P1.15]** `tests/package/test_clean_install.py:93` - Exact-wheel smoke is stale for the current runtime

The estimator assertion expects `1` for `"abc"`, but current behavior is `3`, and the smoke does not exercise XLSForm routing or routed serialization. Update the assertion, add representative new APIs, rebuild, and test the exact current wheel.

### **[P1.16]** `.cg-docs/work-reports/2026-08-31-questionnaire-routing-graph.md:48` - G2 is marked passed without real POSIX evidence

The report records V1 as passed while its platform note says POSIX lock, no-follow, and directory-sync evidence still requires CI. Run the process, recovery, lock, and symlink suites on a real POSIX filesystem before claiming complete G2 evidence.

## P2 - Important

### **[P2.1]** `src/survey_scribe/routing/pipeline.py:169` - Broad exception handling hides implementation defects

Unexpected normal exceptions become `ROUTING_PROVIDER_FAILED`. Catch only defined provider, validation, reconciliation, and source errors; let programming defects propagate.

### **[P2.2]** `src/survey_scribe/sources/chunking.py:133` - Runtime token limits accept Boolean values

Because `bool` is an `int`, `True` can become a one-token limit. Explicitly reject Boolean and non-integer runtime limits.

### **[P2.3]** `.cg-docs/benchmarks/2026-09-01-routing-validation-scale.md:19` - Benchmark evidence has machine-specific identifiers

The report stores an internal host name and a user-specific temporary path. Replace these with generic host metadata and `<external-temp>`.

### **[P2.4]** `src/survey_scribe/routing/validate.py:134` - Unreachable nodes are also reported as reachable dead ends

Dead-end calculation does not filter through the reachable set. Require reachability and assert exact diagnostic node IDs.

### **[P2.5]** `tests/integration/test_routing_extraction.py:1046` - Critical reviewer rejection paths are weakly tested

Unknown discrepancy, candidate, evidence, span-closure, and replacement-endpoint paths remain uncovered. Parameterize each failure and assert no decision or graph mutation.

### **[P2.6]** `pyproject.toml:140` - Routing fixture validator is outside configured Pyright scope

Add `scripts/validate_routing_fixtures.py` to the normal Pyright include list so the passing project check proves this script.

## Passed

- Code-quality and testing reviewers produced usable, changed-file-specific reports.
- Package-excluded coverage gate: 833 passed, 1 protected live-smoke skip, 97.82%.
- Complete suite: 837 passed, 1 protected live-smoke skip.
- Ruff lint and formatting passed.
- Pyright reported 0 errors and 0 warnings for its configured scope.
- `git diff --check` passed with line-ending warnings only.
- No files were modified by review agents.

## Verification Notes

- P0/P1 findings were not suppressed.
- Duplicate findings from both agents were merged at their highest reported severity.
- P2/P3 suppression was applied only to exact prior fixed-finding scope.
- Phase 5 remains blocked by G6, but the new P0/P1 findings also block merge readiness.
