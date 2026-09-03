---
date: 2026-09-02
title: "Bind Routing Quality Evidence Across Metrics, Fixtures, and Packages"
category: "testing-patterns"
language: "Python"
tags: [routing, evaluation, metrics, provenance, manifests, wheel, sdist, offline-install, counterexamples]
root-cause: "Passing aggregate tests hid coupled metrics, permissive synthetic inputs, unbound source evidence, and package checks that admitted stale or undeclared artifacts."
severity: "P0"
---

# Bind Routing Quality Evidence Across Metrics, Fixtures, and Packages

## Problem

A deterministic routing evaluator, strict documentation build, branch coverage,
wheel build, and exact-wheel smoke test all passed. Full review still found that:

- target accuracy included condition identity and condition accuracy included the target;
- empty snapshots and extra loop classes could certify as perfect;
- unresolved routes did not reduce precision;
- opaque conditions collapsed when raw text was removed;
- the evaluation bundle did not identify the exact source manifest;
- output paths could alias each other or protected repository files; and
- broad archive prefixes admitted undeclared wheel and sdist files.

The evidence looked complete, but several reported values did not measure the
dimension named in the report.

## Root Cause

The initial implementation reused whole-edge identities for several metrics.
This was concise, but it coupled independent error classes. Exact-match helpers
also checked only expected and matched counts, so false-positive classifications
were invisible. Package tests used subset and prefix assertions instead of a
closed inventory, and the isolated install selected a versioned wheel without
proving that its bytes matched the current checkout.

## Solution

Define each metric identity independently:

```python
target_key = (source_node_id, edge_kind, priority, target_node_id)
condition_key = (source_node_id, edge_kind, priority, normalized_condition)
edge_key = (source_node_id, target_node_id, edge_kind, priority, normalized_condition)
```

Use multiset counters and retain `expected_count`, `actual_count`, and
`matched_count`. Exact completion requires all three counts to agree. Add
unresolved attempts to the actual prediction denominator with a nonmatching
target identity, and report unresolved and opaque rates explicitly.

Canonicalize conditions with type-tagged scalar values. Sort `all`, `any`, and
set-valued operands. For `opaque`, keep source prose out of the report but include
a SHA-256 digest of normalized text so unrelated opaque rules do not collapse.

Bind the mechanics bundle and report to:

- the exact source-manifest SHA-256;
- the ordered source fixture IDs;
- the mechanics-manifest SHA-256;
- the evaluation-fixture SHA-256; and
- a versioned evaluator identity.

Use counterexample tests for correct-target/wrong-condition,
wrong-target/correct-condition, extra loops, empty bundles, unknown condition
references, unresolved predictions, reordered commutative conditions, and
distinct opaque rules.

For package evidence, compare archive members to exact file inventories. Compare
every runtime archive member to current checkout bytes. Verify dependency-wheel
hashes against `uv.lock`, install with `--require-hashes`, use a minimal
credential-free environment, deny sockets for installed-code checks, and compare
schema plus legacy projection bytes exactly.

## Prevention

- Do not reuse a whole-object identity for metrics that claim independent dimensions.
- Every exact classification metric needs expected, actual, and matched counts.
- Treat unresolved output as a prediction outcome, not as an omitted denominator.
- Hash restricted prose when identity is required but disclosure is prohibited.
- Bind every report to exact input bytes and ordered case identities.
- Reject duplicate, noncanonical, undeclared, or wrong-type manifest and archive data.
- Test wheel, sdist, and editable checkout as separate filesystems.
- Build once, then prove that the tested artifact matches the current checkout.
- Keep provider-quality capture separate from deterministic mechanics evidence.

## Related

- `.cg-docs/solutions/testing-patterns/2026-09-01-verify-cross-layer-invariants-beyond-coverage.md`
- `.cg-docs/solutions/build-errors/2026-08-26-bound-python-package-artifacts-and-evidence.md`
- `.cg-docs/reviews/2026-08-31-questionnaire-routing-graph-review.md`
- `.cg-docs/plans/2026-08-31-questionnaire-routing-graph.md`
- `scripts/evaluate_routing.py`
- `tests/unit/test_evaluate_routing.py`
- `tests/package/test_clean_install.py`
- `tests/package/test_distribution_contents.py`
