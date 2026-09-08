---
date: 2026-09-03
title: "Bound Provider Retries and Preserve Chunk Provenance"
category: "testing-patterns"
language: "Python"
tags: [providers, retries, instructor, chunking, overlap, provenance, cancellation, validation, coverage]
root-cause: "Fake-provider tests modeled invalid values as returned data, while real SDK and Instructor failures occur inside adapter calls; the extraction pipeline also bypassed the source chunk ownership model."
severity: "P1"
---

# Bound Provider Retries and Preserve Chunk Provenance

## Problem

Provider and pipeline tests passed, but verification found that production
behavior could still violate the public contracts:

- SDK clients could retry internally in addition to package retries;
- SDK connection and Instructor validation exceptions crossed different
  boundaries than the test doubles;
- whole-block extraction discarded overlap and repeated-row evidence;
- cancellation could leave sibling requests running;
- invalid numeric ranges skipped the required validation retry; and
- prompt, source, and response identities were not retained together.

## Root Cause

The tests injected return values and built-in exceptions after the SDK boundary.
Real OpenAI, Azure, Anthropic, and Instructor clients raise package-specific
exceptions inside the completion call and can run their own retry loops.

The pipeline also treated a normalized `SourceBlock` as the provider request
unit. This bypassed `chunk_document()`, so tests could manually create overlap
metadata that production code never produced.

## Solution

Make one layer authoritative for each behavior:

```python
client = SDKClient(max_retries=0, ...)
response = await provider.generate(retry=RetryConfig(...))
```

- Disable retries in every SDK client and keep retry counts in the provider port.
- Normalize SDK connection, timeout, truncation, and Instructor validation
  exceptions before the generic transport handler.
- Test faithful SDK exception instances, not only built-in exceptions or invalid
  dictionaries.
- Use `chunk_document()` as the only provider request partitioner.
- Require each extracted variable to cite source block IDs from its active chunk.
- Carry overlap block IDs and repeated-row inventory into the request and quality
  policy.
- Validate semantic rules, such as numeric range order, in the structured response
  model so they use the normal validation-retry budget.
- Create child tasks explicitly, cancel siblings on control exceptions, await
  cleanup, and then re-raise.
- Record versioned prompt digests with source and model-response digests.

Verification must include the configured branch-coverage gate, not only focused
tests. The Phase 3 fix passed 947 tests, exact package checks, and 95.00 percent
branch coverage.

## Prevention

- Test at the same exception boundary used by each real optional SDK.
- Never let both the SDK and the application own retries.
- Do not synthesize overlap provenance directly in quality-policy unit tests as
  the only evidence; require an end-to-end chunked test.
- Bind extracted records to source-owned identifiers before deduplication.
- Keep request envelope overhead outside the content token budget.
- Require explicit tests for cancellation cleanup, validation exhaustion,
  truncation diagnostics, threshold boundaries, and deterministic order.
- Run exact-artifact and full branch-coverage gates after formatting and before
  recording phase completion.

## Related

- `.cg-docs/solutions/testing-patterns/2026-09-02-bind-routing-quality-evidence.md`
- `.cg-docs/solutions/build-errors/2026-08-26-bound-python-package-artifacts-and-evidence.md`
- `.cg-docs/reviews/2026-08-31-questionnaire-routing-graph-verify-review.md`
- `.cg-docs/plans/2026-08-28-survey-scribe-production-package-refined.md`
- `.cg-docs/solutions/bugs/2026-09-05-detach-provider-secrets-and-preserve-wire-contracts.md`
- `src/survey_scribe/pipeline.py`
- `src/survey_scribe/providers/openai_compatible.py`
