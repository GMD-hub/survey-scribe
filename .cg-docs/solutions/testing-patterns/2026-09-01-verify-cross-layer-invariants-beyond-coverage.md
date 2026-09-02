---
date: 2026-09-01
title: "Verify Cross-Layer Invariants Beyond Coverage"
category: "testing-patterns"
language: "Python"
tags: [verification, branch-coverage, invariants, counterexamples, routing, artifacts, source-integrity]
root-cause: "High aggregate coverage executed local branches but did not prove that evidence, identities, source bindings, graph edges, artifacts, and package outputs agreed across module boundaries."
severity: "P0"
---

# Verify Cross-Layer Invariants Beyond Coverage

## Problem

The package passed 837 tests, Ruff, Pyright, and a 97.82 percent
statement-plus-branch coverage gate. A light verification review still found
blocking semantic failures. Examples included:

- Accepted graph edges could cite evidence for a different route.
- Routed variables could disagree with inventory links.
- Independent conditional branches were compared as if they were one branch.
- Source bindings omitted companion-file content.
- Stable artifact projections could disagree with the active pointer after a
  hard process exit.
- Exact-wheel tests did not exercise the changed routing runtime.

The aggregate gates proved that code paths executed. They did not prove that
facts remained consistent across layers.

## Root Cause

Most tests validated one function or model at a time. Local validators checked
that referenced IDs existed, but not that the referenced objects described the
same fact. Happy-path integration tests reused internally consistent fixtures,
so they did not challenge cross-layer identity and provenance boundaries.

Coverage percentages also hid weak critical modules. A high package total can
coexist with low coverage and missing negative tests at a reviewer, publication,
or provider-schema boundary.

## Solution

Define each cross-layer invariant as a relation, then test a minimally changed
counterexample that keeps every referenced object valid but makes the relation
false.

| Boundary | Required relation | Counterexample |
|---|---|---|
| Evidence to edge | source, target, kind, and condition agree | cite valid evidence for another edge |
| Inventory to variable | variable index maps to the same question node | link to a different existing question |
| Source to binding | digest covers primary and all companions | mutate only an external choices file |
| Incoming to outgoing evidence | normalized branch identity agrees | use two valid sibling predicates |
| Projection to pointer | every public file identifies one generation | inspect immediately after hard exit |
| Schema record to provider request | recorded hash equals wire schema | compare a transport spy with metadata |
| Checkout to wheel | built artifact contains and executes new APIs | run representative routing from exact wheel |

Use the following test pattern:

```python
def test_edge_rejects_unrelated_existing_evidence(valid_graph):
    edge = valid_graph.edges[0]
    unrelated = valid_graph.routing_audit.evidence[1]
    corrupted = edge.model_copy(update={"evidence_ids": (unrelated.evidence_id,)})

    with pytest.raises(ValidationError):
        valid_graph.model_copy(update={"edges": (corrupted,)})
```

For process and filesystem contracts, test the observable state before a second
writer performs recovery. Recovery tests alone can hide an invalid public state
that readers can observe after the crash.

Record both aggregate and critical-module coverage. Coverage remains a useful
regression gate, but it is not completion evidence for a semantic invariant.

## Prevention

- Write an invariant matrix before implementation and map each row to a negative
  cross-layer test.
- Prefer counterexamples that use valid IDs with wrong relationships. Missing-ID
  tests prove namespace validation only.
- Test one-to-many cases such as sibling branches, multiple discrepancies for one
  candidate, and companion files.
- Inspect crash state immediately, then test recovery separately.
- Spy on transmitted provider requests instead of hashing an unused local schema.
- Run exact-wheel behavior tests for each new public runtime slice.
- Report critical-module branch coverage in addition to the package total.
- Do not mark platform-specific evidence passed until it runs on that platform.

## Related

- `.cg-docs/reviews/2026-08-28-survey-scribe-production-package-refined-verify-review-2.md`
- `.cg-docs/solutions/build-errors/2026-08-26-bound-python-package-artifacts-and-evidence.md`
- `.cg-docs/plans/2026-08-31-questionnaire-routing-graph.md`
- `tests/unit/test_routing_models.py`
- `tests/integration/test_artifact_process_safety.py`
- `tests/package/test_clean_install.py`
- `.cg-docs/solutions/testing-patterns/2026-09-02-bind-routing-quality-evidence.md`
