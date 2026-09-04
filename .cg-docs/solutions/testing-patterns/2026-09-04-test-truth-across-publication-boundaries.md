---
date: 2026-09-04
title: "Test Truth Across Publication Boundaries"
category: "testing-patterns"
language: "Python"
tags: [partial-results, metadata, provenance, authentication, cli, manifests, sbom, accessibility]
root-cause: "Happy-path tests validated components independently but did not prove that status, provenance, credentials, and evidence stayed truthful when outputs crossed public boundaries."
severity: "P0"
---

# Test Truth Across Publication Boundaries

## Problem

The public SDK, CLI, package artifacts, security gates, and documentation passed
large test suites. Verification still found cases where a valid-looking public
output did not tell the full truth:

- an XLSForm with missing required metadata reported success with placeholders;
- calculation rows preserved as variables also became routing nodes;
- row evidence cited a whole worksheet instead of the physical source row;
- a deprecated shim wrote a partial projection without its diagnostic sidecar;
- Azure bearer tokens entered the API-key path;
- a batch manifest was checked before work but not reserved through publication;
- a development-environment SBOM was not bound to the exact wheel; and
- custom accessibility checks missed a real serious contrast violation.

## Root Cause

Tests concentrated on local function behavior and successful fixtures. They did
not consistently challenge the transition from one representation or subsystem
to the next. Defaults, placeholders, compatibility projections, credential
adapters, manifests, and generated evidence could therefore look valid while
describing a different state from the source or runtime.

## Solution

Define a truth-preservation assertion for every publication boundary:

| Boundary | Required assertion |
|---|---|
| native source to result | required placeholders add diagnostics and force `partial` |
| XLSForm row to routing evidence | the span identifies the exact physical row |
| semantic record to graph | non-flow records never create routing nodes or edges |
| partial result to legacy output | diagnostics publish atomically with the projection |
| credential field to provider | bearer tokens and API keys use different authentication paths |
| batch start to manifest | destination ownership remains exclusive through publication |
| wheel to SBOM | root name, version, direct dependencies, closure, and SHA-256 match the exact wheel |
| generated site to accessibility claim | a pinned standards engine reports no serious or critical violations |

Use negative fixtures that differ from a valid fixture in one meaningful fact.
Examples include a settings sheet without country/year, duplicate choice codes,
a calculated field between two questions, a second process targeting one batch
manifest, a failed first provider close, and a known low-contrast token.

Keep evidence generation close to the artifact it certifies. Build the wheel once,
install it in an isolated offline environment, generate the SBOM from that
environment, and attach the wheel digest before validation. Preserve unavailable
real-corpus metrics as unavailable; never substitute synthetic metrics under a
real-corpus label.

## Prevention

- Test `success`, `partial`, and `failed` at every public and compatibility entry point.
- Treat placeholders as incomplete evidence, not successful extraction.
- Test exact physical provenance, not only a matching quote or valid identifier.
- Reserve shared publication destinations before side effects begin.
- Test each credential type through the concrete adapter field it reaches.
- Reject insecure credential-bearing transports before provider construction.
- Bind generated evidence to exact input bytes and dependency closure.
- Use pinned standards tools for accessibility and security when a local heuristic can miss defects.
- Rerun cross-layer fixtures after strengthening one subsystem; older success fixtures may
  need complete metadata rather than weaker assertions.

## Related

- `.cg-docs/solutions/testing-patterns/2026-09-01-verify-cross-layer-invariants-beyond-coverage.md`
- `.cg-docs/solutions/testing-patterns/2026-09-02-bind-routing-quality-evidence.md`
- `.cg-docs/solutions/testing-patterns/2026-09-03-bound-provider-retries-and-chunk-provenance.md`
- `.cg-docs/solutions/build-errors/2026-08-26-bound-python-package-artifacts-and-evidence.md`
- `.cg-docs/reviews/2026-08-28-survey-scribe-production-package-refined-verify-review-4.md`
