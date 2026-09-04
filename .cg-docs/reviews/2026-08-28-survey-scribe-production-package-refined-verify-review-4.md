---
date: 2026-09-04
depth: light
type: verification
parent-review: .cg-docs/reviews/2026-08-31-questionnaire-routing-graph-review.md
plan: .cg-docs/plans/2026-08-28-survey-scribe-production-package-refined.md
findings:
  P0.1: fixed
  P0.2: fixed
  P0.3: fixed
  P0.4: fixed
  P1.1: fixed
  P1.2: fixed
  P1.3: fixed
  P1.4: fixed
  P1.5: fixed
  P2.1: fixed
  P2.2: fixed
  P2.3: fixed
  P2.4: fixed
  P2.5: skipped
  P2.6: fixed
  P2.7: fixed
  P2.8: fixed
---

# Verification Review: Production Package Phases 4-5

**Review mode**: light verification
**Parent review**: `.cg-docs/reviews/2026-08-31-questionnaire-routing-graph-review.md`
**Files reviewed**: 106 current tracked and untracked Phase 4-5 implementation,
test, documentation, workflow, and state files
**Findings**: 17 (P0: 4, P1: 5, P2: 8, P3: 0)

## P0 - Blocking

### **[P0.1]** `src/survey_scribe/sources/xlsform.py:382` - Calculation rows re-enter the routing graph

`calculate` rows receive native routing items and sequential transitions even though the
support contract says calculations are preserved but do not define flow. Preserve their
variables and expressions, but exclude them from routing items and transitions. Update the
test that currently requires the calculated variable in `native.items`.

Scope: cross-file regression tied to a prior calculation-flow finding; P0 is not suppressed.

### **[P0.2]** `src/survey_scribe/sources/xlsform.py:1007` - Missing metadata reports success with invented values

Missing settings become filename-derived identifiers, `UNK`, and the current year without a
`METADATA_INCOMPLETE` diagnostic. Emit that diagnostic for required fallbacks and make the
public result partial while retaining deterministic placeholders. Cover missing settings and
header-only forms through `SurveyScribe.convert()`.

Scope: new cross-file finding.

### **[P0.3]** `src/survey_scribe/config.py:145` - Custom providers accept credential-bearing HTTP transport

Custom provider URLs permit remote `http://` endpoints, so API keys and questionnaire content
can travel without transport encryption. Require HTTPS. If loopback HTTP is needed for local
development, use a narrow explicit opt-in that cannot accept real credentials.

Scope: new cross-file security finding.

### **[P0.4]** `docling_pipeline.py:39` - Legacy partial conversions lose all failure evidence

The shim writes partial results with `sidecar=False`, which can create a normal-looking legacy
projection without diagnostics for omitted blocks. Add a partial-result compatibility test and
require a diagnostic sidecar or fail without replacing the projection.

Scope: new cross-file finding.

## P1 - Critical

### **[P1.1]** `src/survey_scribe/sources/xlsform.py:910` - XLSForm evidence spans cite the whole sheet

Row-level evidence copies the table-wide row range. Retain physical row indexes while parsing
and attach the exact source row to each evidence span. Add routing-artifact assertions.

Scope: new cross-file finding.

### **[P1.2]** `src/survey_scribe/cli.py:235` - Batch manifest collision handling has a race

Concurrent batches can both pass the pre-conversion existence check, write result artifacts,
and then compete to publish one manifest. Reserve the destination exclusively through
publication or use immutable run manifests with an atomic active pointer.

Scope: new cross-file finding.

### **[P1.3]** `src/survey_scribe/sources/xlsform.py:214` - Duplicate choice codes are accepted silently

A set masks duplicate `(list_name, name)` identities while later SVIS generation preserves
both categories. Reject duplicate internal and external choice identities before producing
native records or categories.

Scope: new cross-file finding.

### **[P1.4]** `src/survey_scribe/client.py:375` - Azure bearer tokens are mapped as API keys

The SDK and CLI accept `bearer_token`, but Azure construction passes it through the API-key
parameter. Route bearer tokens through the Azure token-provider mechanism or reject this form
explicitly. Add SDK and CLI factory tests.

Scope: new cross-file finding.

### **[P1.5]** `scripts/check_workflow_policy.py:56` - Publication policy can be bypassed through secrets and local actions

The policy accepts local actions without inspection and does not reject `${{ secrets.* }}`.
Add fail-closed tests and reject both unless an explicit reviewed workflow/job allowlist permits
them.

Scope: new cross-file finding.

## P2 - Important

### **[P2.1]** `scripts/evaluate_quality.py:220` - Quality evidence removes routing provenance

The wrapper supplies zero digest defaults and omits exact mechanics and fixture identities from
its authoritative report. Compute and pass all routing input digests and record evaluator
identity and measurement provenance.

Scope: cross-file regression tied to prior evaluation-provenance scope.

### **[P2.2]** `scripts/evaluate_quality.py:152` - Approved-corpus metrics still use synthetic fixtures

When `approved_real_corpus` becomes true, variable and field metrics still use synthetic
expected outputs, while dense-table recall is not implemented. Bind sanitized source/output
fixtures by validated IDs and digests, and calculate each metric independently.

Scope: new cross-file finding.

### **[P2.3]** `src/survey_scribe/client.py:224` - Failed provider cleanup cannot be retried

The facade marks itself closed before provider cleanup. If cleanup fails, later calls return
without retrying. Mark closed only after success or retain a retryable failed-cleanup state.

Scope: new single-file finding.

### **[P2.4]** `.cg-docs/work-reports/2026-08-28-survey-scribe-production-package-refined.md:220` - Final status contradicts Phase 5 evidence

The report records Phase 5 completion but ends with Phase 4 in progress. Make its final status
and active-state handoff consistent with the recorded verification state.

Scope: new cross-file state finding.

### **[P2.5]** `.github/workflows/ci.yml:104` - SBOM evidence is not bound to the built wheel

`cyclonedx-py environment` inventories the development environment with all extras. Generate
or verify the SBOM from an isolated exact-wheel installation and test its schema, root package,
version, dependency set, and wheel identity.

Scope: new cross-file finding.

### **[P2.6]** `scripts/run_security_gates.py:143` - Network-blocked scanner collection is only a label

Bandit and detect-secrets run as ordinary subprocesses; only in-process verification has a
socket block. Enforce the child-process network boundary or document it as tool behavior and
test the selected guarantee.

Scope: new cross-file finding.

### **[P2.7]** `tests/integration/test_public_api.py:499` - Custom pipeline public conversion paths are under-tested

Tests mainly call `extract()` directly. Add `convert()` and `aconvert()` coverage for bundles,
invalid local inputs, source failures, running-loop rejection, and stable reducer ordering.

Scope: new cross-file finding.

### **[P2.8]** `tests/browser/test_local_site.py:101` - Accessibility coverage uses a limited custom audit

The current audit can miss ARIA relationships, focus order, and full-page contrast defects.
Add a locally pinned accessibility engine such as axe-core and fail on serious or critical
violations for desktop and mobile routes.

Scope: new cross-file finding.

## Verification Evidence

- Both required light-route agents returned usable output.
- Code-quality focused tests: 138 passed; testing focused suites: 146 passed.
- Ruff passed; Pyright reported 0 errors; `git diff --check` passed.
- Workflow policy and generated-documentation drift checks passed.
- No source file was changed by the review agents.

## Residual Risks

- The full 1,052-test suite was not rerun by the review agents; it passed immediately before
  this review.
- Exact-wheel, browser, real OCR, live-provider, Windows, and concurrent batch-process checks
  were not rerun by the review agents.
