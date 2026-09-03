---
date: 2026-09-03
depth: light
parent-review: .cg-docs/reviews/2026-08-31-questionnaire-routing-graph-review.md
type: verification
findings:
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
  P1.11: fixed
  P1.12: fixed
  P2.1: fixed
  P2.2: fixed
  P2.3: fixed
  P2.4: fixed
---

# Verification Review: Production Package Phase 3

**Review mode**: light verification
**Parent review**: `.cg-docs/reviews/2026-08-31-questionnaire-routing-graph-review.md`
**Files reviewed**: 15 current tracked and untracked Phase 3 implementation, test,
documentation, plan, and workflow-state files
**Findings**: 16 (P0: 0, P1: 12, P2: 4, P3: 0)

## P0 - Blocking

No P0 findings.

## P1 - Critical

**[P1.1]** `src/survey_scribe/providers/openai_compatible.py:35` - The OpenAI preset permits an ambient endpoint override.

**Why**: A `None` preset URL lets `AsyncOpenAI` read `OPENAI_BASE_URL`, so a named
OpenAI configuration can send credentials and requests to an unintended endpoint.

**Fix**: Set the OpenAI preset URL explicitly and test with a hostile environment value.

**[P1.2]** `src/survey_scribe/pipeline.py:103` - The SVIS pipeline bypasses deterministic source chunking and overlap provenance.

**Why**: It sends whole blocks and joins all blocks for metadata. Dense tables can fail as
one oversized request, overlap deduplication cannot occur in production, and repeated-row
completeness evidence is discarded.

**Fix**: Use `chunk_document()` with prompt overhead reserved, and carry new-part,
overlap, repeated-row, and source-order evidence into extraction and quality processing.

**[P1.3]** `src/survey_scribe/providers/openai_compatible.py:216` - SDK retry defaults bypass `RetryConfig` and normalized attempt counts.

**Why**: OpenAI, Azure, and Anthropic clients can retry internally, so one reported
transport attempt can perform multiple network requests with unconfigured backoff.

**Fix**: Construct all three SDK clients with `max_retries=0` and test the client options.

**[P1.4]** `src/survey_scribe/providers/openai_compatible.py:314` - Real SDK connection and timeout exceptions are classified as non-retryable.

**Why**: OpenAI and Anthropic connection exception classes do not inherit the built-in
`TimeoutError` or `ConnectionError`, so configured recovery does not run.

**Fix**: Lazily normalize provider SDK connection exception classes and test retry,
exhaustion, and redaction with faithful SDK exceptions.

**[P1.5]** `src/survey_scribe/providers/openai_compatible.py:175` - Real Instructor validation failures become transport failures.

**Why**: Instructor can raise validation/retry exceptions inside the completion call.
The broad exception handler converts them to non-retryable transport errors before the
bounded validation path runs.

**Fix**: Normalize Instructor parse/validation exceptions separately and route them
through the configured validation-retry path.

**[P1.6]** `src/survey_scribe/pipeline.py:275` - Invalid numeric ranges receive no required validation retry.

**Why**: A response with `min_value > max_value` is excluded after one successful call,
although the Phase 3 quality contract requires validation retry before a failed block.

**Fix**: Validate semantic ranges at the response boundary, retry within the configured
limit, and emit one stable failed-block record only after exhaustion.

**[P1.7]** `src/survey_scribe/pipeline.py:103` - Cancellation can leave sibling provider requests running.

**Why**: `asyncio.gather()` propagates a child cancellation without cancelling the other
children. Requests can continue and incur cost after the pipeline is cancelled.

**Fix**: Create tasks explicitly, cancel all siblings on control exceptions, and await
their cleanup before re-raising.

**[P1.8]** `src/survey_scribe/pipeline.py:344` - Authoritative module reconciliation applies only to spreadsheet sheets.

**Why**: PDF, DOCX, HTML, Markdown, and text provenance has no section identity, so an
incorrect model module can remain unchanged and unflagged for those formats.

**Fix**: Preserve source heading/section context and use it during reconciliation.

**[P1.9]** `src/survey_scribe/providers/anthropic.py:57` - Anthropic silently ignores an accepted seed.

**Why**: A capability row can advertise `seed`, but the Anthropic request does not send
it. A determinism setting can therefore succeed without effect.

**Fix**: Reject Anthropic rows or requests that enable `seed` until the selected backend
supports an equivalent setting.

**[P1.10]** `.cg-docs/active-state/current.json:5` - Phase 3 is certified before its requirements pass.

**Why**: The state advances to Phase 4 and marks V5/V6 passed while the defects in this
review contradict retry, cancellation, quality, and orchestration evidence.

**Fix**: Keep Phase 3 active and V5/V6 incomplete until the corrected regression suite passes.

**[P1.11]** `src/survey_scribe/pipeline.py:233` - Truncation loses its stable diagnostic code.

**Why**: `ProviderTruncationError` is caught as generic `ProviderError` and becomes
`PROVIDER_FAILED`, so callers cannot distinguish incomplete output.

**Fix**: Catch truncation first and emit `PROVIDER_TRUNCATED`; test partial and total truncation.

**[P1.12]** `src/survey_scribe/providers/openai_compatible.py:300` - Inconsistent usage totals can escape as raw `ValueError`.

**Why**: A nonnegative total below input plus output reaches `NormalizedUsage` and raises
outside the provider error boundary, which can escape pipeline fallback behavior.

**Fix**: Normalize inconsistent totals safely or raise a redacted `ProviderError`, and
test malformed values including too-small integer totals.

## P2 - Important

**[P2.1]** `src/survey_scribe/pipeline.py:164` - Extraction prompts have no semantic version or digest provenance.

**Why**: Prompt changes can alter extraction behavior without a reproducible identity.

**Fix**: Move prompts to versioned definitions with stable digests and retain their identities.

**[P2.2]** `src/survey_scribe/pipeline.py:384` - Possible-duplicate diagnostics use set iteration order.

**Why**: Diagnostic ordering is not guaranteed across runtimes, which violates stable output ordering.

**Fix**: Preserve source order directly or iterate over sorted pairs and assert full diagnostic order.

**[P2.3]** `tests/unit/test_quality.py:39` - The confidence threshold boundary is not tested.

**Why**: The acceptance criteria require boundary evidence, but tests cover only `0.69`, not exactly `0.70`.

**Fix**: Assert that the exact threshold is not flagged and the immediate lower value is flagged.

**[P2.4]** `tests/contract/providers/test_provider_adapters.py:54` - Advertised adapter paths are not all exercised.

**Why**: The OpenAI preset, successful custom preset, and Azure API-key construction can regress while the contract suite passes.

**Fix**: Exercise every named preset, custom gateway, Azure key, Azure callback, and optional Anthropic path.

## Passed

- Both light verification agents returned usable output.
- Pre-review evidence passed: 939 tests, 5 expected skips; package, Ruff, Pyright,
  strict MkDocs, Twine, artifact validation, and whitespace gates passed.
- The prior fixed distribution, wheel-isolation, provider-documentation, and routing
  findings were suppressed only where the parent review explicitly marked them fixed.
- No files were changed by review agents.
