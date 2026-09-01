---
date: 2026-09-01
depth: light
parent-review: .cg-docs/reviews/2026-08-28-survey-scribe-production-package-refined-review.md
type: verification
findings:
  P0.1: fixed
  P0.2: fixed
  P0.3: fixed
  P0.4: open
  P0.5: open
  P0.6: fixed
  P0.7: fixed
  P0.8: fixed
  P1.1: fixed
  P1.2: fixed
  P1.3: fixed
  P1.4: fixed
  P1.5: fixed
  P1.6: fixed
  P1.7: fixed
  P1.8: fixed
  P1.9: fixed
  P1.10: fixed
  P2.1: fixed
  P2.2: fixed
  P3.1: fixed
---

# Verification Review: Safety-Fix Convergence

**Review mode**: light verification
**Parent review**: `.cg-docs/reviews/2026-08-28-survey-scribe-production-package-refined-review.md`
**Files reviewed**: 39 changed implementation, test, configuration, documentation, benchmark, and review files
**Findings**: 21 (P0: 8, P1: 10, P2: 2, P3: 1)

## P0 - Blocking

### **[P0.1]** `src/survey_scribe/routing/reconcile.py:582` - Independent unmatched sibling branches still become conflicts

The singleton fallback compares one outgoing-only and one incoming-only claim even when their normalized predicates identify different branches. A `Q1=1 -> Q2` outgoing claim plus `Q1=2 -> Q3` incoming claim produces no accepted edge and `CONFLICTING_TARGET`.

**Fix**: Remove the singleton fallback comparison. Keep unmatched outgoing claims accepted and classify unmatched incoming claims as `INCOMING_ONLY`.

### **[P0.2]** `src/survey_scribe/models/routing.py:1017` - Reviewed accepted edges can cite unrelated evidence

Direct edges validate their evidence relation, but confirmed and replacement edges validate only candidate or decision fields. A candidate and decision can cite valid evidence for another route and still produce an accepted edge.

**Fix**: Validate candidate and replacement source, target, kind, condition, and evidence closure against canonical inventory before accepting a reviewed edge. Add confirm, replacement, JSON round-trip, and serializer counterexamples.

### **[P0.3]** `src/survey_scribe/models/routing.py:1134` - Duplicate audit identity logic collapses Unicode references

`_audit_alias()` removes non-ASCII letters, so distinct references such as `é` and `ñ` normalize to the same empty value. This diverges from `IdentityResolver` and can accept or reject the wrong multilingual route.

**Fix**: Use one cycle-safe Unicode-aware identity normalizer for extraction, reconciliation, and final graph validation.

### **[P0.4]** `src/survey_scribe/serialization/artifacts.py:1215` - Secure operations do not retain the complete directory chain

`_secured_directory()` protects only the final component and reopens a multi-component path. Replacing `.survey-scribe`, `surveys`, or a survey directory can redirect generation, transaction, recovery, or projection operations outside the original output root.

**Fix**: Retain the output-root descriptor or handle and open every internal component relative to the retained chain with no-follow or reparse-safe checks. Add ancestor-replacement tests on POSIX and Windows.

### **[P0.5]** `src/survey_scribe/serialization/artifacts.py:693` - Replacing the aliases directory bypasses writer exclusion

The writer locks the current aliases-directory inode. An attacker can rename that directory, create a replacement, and let another writer lock a different object while the first writer continues to verify the old descriptor.

**Fix**: Anchor locking to a stable object reached from a retained root descriptor and verify the aliases-directory entry through that root. Add a hostile directory-replacement process test.

### **[P0.6]** `src/survey_scribe/serialization/artifacts.py:1045` - Recovery journal relations are not validated

The journal parser does not require `pointer.path` to contain `pointer.generation_id`, and recovery does not bind the journal publication set to the generation manifest. A changed journal can publish contradictory generation files and pointers.

**Fix**: Require the exact generation path and validate publication names, kinds, source filenames, and digests against the parsed manifest before recovery writes.

### **[P0.7]** `src/survey_scribe/routing/pipeline.py:374` - Competing identity types can link one question to unrelated variables

Printed-ID and label matches are combined. For `Q1. Age`, a variable named `Q1` and a different variable labeled `Age` both link to the same question.

**Fix**: Apply identity precedence. Use a unique printed-ID match first and use label or question-text matching only when no printed-ID match exists. Test through `QuestionnaireRouter`.

### **[P0.8]** `tests/contract/sources/test_docling_adapter.py:791` - Newline table preservation test does not exercise production parsing

The test passes one string containing a newline directly to `_parse_markdown_table()`. Production callers call `splitlines()` first, so a real cell newline can become a different row.

**Fix**: Test through `DoclingConverter` and `MarkdownAdapter`, and preserve structured or encoded cell newlines before line splitting.

## P1 - Critical

### **[P1.1]** `src/survey_scribe/models/routing.py:1083` - Replacement references can contradict accepted targets during artifact validation

`_edge_matches_replacement()` does not resolve `target_reference`. A final graph can record a replacement reference to `Q1` while accepting target `END`.

**Fix**: Resolve candidate and replacement references during public graph validation and require exact agreement with `target_node_id`.

### **[P1.2]** `src/survey_scribe/routing/extraction.py:901` - Pass B uses a divergent reference resolver

Pass B selection lacks the canonical global unique fallback. A cross-section target can miss independent verification while reconciliation later resolves and accepts it.

**Fix**: Use the canonical `IdentityResolver` behavior in Pass B selection.

### **[P1.3]** `src/survey_scribe/routing/extraction.py:984` - Full Pass B target chunks omit all predecessor context

When target count equals `max_inventory_items_per_call`, the packet is full before predecessor selection and `add()` cannot include any predecessor.

**Fix**: Reserve a separate predecessor-context budget or reduce target batch size. Test an exactly full risky target chunk.

### **[P1.4]** `src/survey_scribe/routing/review.py:103` - Supersession does not continue across reviewer responses

`latest_by_candidate` starts empty for every builder call. A later response for a previously decided candidate gets no predecessor and fails append-only audit validation.

**Fix**: Seed decision construction from existing active review decisions and test a second review round.

### **[P1.5]** `src/survey_scribe/sources/ocr.py:57` - OCR validation is not bound to the bytes EasyOCR consumes

Validated model files are closed and a mutable directory path is returned. EasyOCR reopens the files later, so post-validation replacement remains possible.

**Fix**: Copy approved model bytes into a private worker-owned snapshot and configure EasyOCR to consume only that snapshot.

### **[P1.6]** `src/survey_scribe/sources/base.py:435` - Archive and XML limits can apply after unsafe allocation or recursion

`ZipFile` materializes the central directory before entry-count checks, and DOCX transparent-container traversal remains recursive without an XML-depth limit.

**Fix**: Inspect entry count in a bounded worker or before full materialization, add `max_xml_depth`, and use iterative DOCX container traversal.

### **[P1.7]** `src/survey_scribe/sources/docling.py:588` - PDF preflight leaks its child on process-control exceptions

Timeout and child-exit paths clean up, but `KeyboardInterrupt` and `SystemExit` bypass bounded preflight cleanup.

**Fix**: Apply the same process-control cleanup boundary used by the conversion worker or make final cleanup idempotent and bounded.

### **[P1.8]** `src/survey_scribe/routing/review.py:98` - Replacement identity is resolved against an incomplete packet inventory

The packet contains only candidate endpoints. A duplicate same-name item outside the packet can be omitted, making an ambiguous raw reference appear uniquely resolved.

**Fix**: Validate against complete canonical inventory or include the full identity-collision closure in the packet. Test duplicate IDs across sections with an omitted section path.

### **[P1.9]** `tests/package/test_clean_install.py:24` - Local package evidence can still select a stale wheel

The test selects a repository wheel by static version. A wheel built before current changes can pass during an ordinary local suite.

**Fix**: Build into a test-owned temporary directory from the current checkout and install that exact path, or verify wheel provenance against current tree content.

### **[P1.10]** `.cg-docs/reviews/2026-08-28-survey-scribe-production-package-refined-verify-review-2.md:7` - Fixed statuses and body evidence do not agree

All 32 findings are fixed in frontmatter while the body retains the pre-fix 837-test evidence and says P0/P1 still block readiness. New reproduced failures also remain.

**Fix**: Reopen unresolved statuses and record current command, result, platform, and tree evidence before marking each finding fixed.

## P2 - Important

### **[P2.1]** `docs/guides/sources.md:126` - Chunking documentation contradicts implementation

The guide describes one token per three characters and permits oversized text/table chunks. The implementation uses one token per UTF-8 byte, splits text, and rejects oversized tables. New archive and XML limits are also undocumented.

**Fix**: Document the byte estimator, hard split-or-reject contract, and current archive/XML limits.

### **[P2.2]** `tests/integration/test_routing_pipeline.py:597` - Concurrency tests use host-speed thresholds

The one-second offload assertion and five-second crashed-worker assertion can fail on loaded CI workers despite correct synchronization.

**Fix**: Assert event-loop progress and process-sentinel state without wall-clock correctness thresholds.

## P3 - Minor

### **[P3.1]** `.cg-docs/reviews/2026-08-28-survey-scribe-production-package-refined-verify-review-2.md:1` - Review Markdown is executable

The file mode changed from `100644` to `100755` without executable content.

**Fix**: Restore mode `0644`.

## Passed

- Both light verification reviewers produced usable changed-file-specific findings.
- Current full suite before this review: 882 passed, 5 expected skips.
- Project Pyright: 0 errors and 0 warnings.
- No provider call was made.

## Residual Gaps

- Approved-cache real OCR smoke remains skipped on this host.
- Windows reparse, handle, lock, and directory-flush branches require final-tree Windows evidence.
- Strict schema evidence uses Instructor's local request shaping and not a live provider transport.

## Fix Verification Evidence: 2026-09-01

- Routing, model, source, artifact, package, and preflight changed-area tests: 498 passed, 4 expected skips.
- Full suite before final coverage additions: 901 passed, 5 expected skips.
- Package-excluded branch coverage after additions: 902 passed, 5 expected skips, 95.12%.
- Exact current-tree wheel and distribution tests: 4 passed.
- Ruff lint, Ruff format, Pyright, and `git diff --check`: passed.
- POSIX ancestor replacement and aliases-directory replacement counterexamples passed.
- P0.4 and P0.5 remain open because final-tree Windows handle/reparse and lock-directory evidence is unavailable on this macOS host.
- No provider inference call was made.
