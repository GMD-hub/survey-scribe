---
date: 2026-09-04
depth: full
type: standard
plan: .cg-docs/plans/2026-09-04-azure-gateway-header-compatibility.md
findings:
  P0.1: fixed
  P0.2: fixed
  P0.3: fixed
  P0.4: fixed
  P0.5: fixed
  P1.1: fixed
  P1.2: fixed
  P1.3: fixed
  P1.4: fixed
  P2.1: fixed
  P2.2: fixed
  P2.3: fixed
  P2.4: fixed
  P2.5: fixed
  P2.6: fixed
  P2.7: fixed
  P3.1: fixed
---

# Review Report: Azure Gateway Header Compatibility

**Review mode**: full (verification fallback; no prior fixed review existed)
**Files reviewed**: 16 feature source, test, and documentation files
**Findings**: 17 (P0: 5, P1: 4, P2: 7, P3: 1)

## P0 - Blocking

- **[P0.1]** `src/survey_scribe/providers/openai_compatible.py:187` - Request
  failures can retain sensitive headers in traceback frames.
  **Why**: Process-control exceptions and existing `ProviderTransportError`
  objects preserve completion frames that contain `extra_headers`.
  **Fix**: Clear request data and propagate fresh, detached safe exceptions. Add
  completion-boundary traceback tests for cancellation and exhausted transport
  failures.

- **[P0.2]** `src/survey_scribe/providers/openai_compatible.py:340` - Wire output
  is serialized and validated twice.
  **Why**: Aliases, serializers, computed fields, and non-idempotent validators
  can fail or silently change already validated values.
  **Fix**: Convert the validated wire subclass to the requested model without
  serialization or another validation cycle. Add alias, serializer, computed
  field, and validator-count tests.

- **[P0.3]** `src/survey_scribe/errors.py:49` - Subscription-key redaction is
  incomplete for valid multi-part values and equivalent query spellings.
  **Why**: Plain assignment redaction stops at spaces and delimiters, while
  compact or percent-encoded query names can bypass query classification.
  **Fix**: Add line-oriented subscription-header redaction and one shared
  normalized full-match query rule. Test spaces, commas, semicolons, compact
  names, and percent-encoded names.

- **[P0.4]** `src/survey_scribe/providers/azure.py:66` - Direct provider
  constructors accept credential-bearing endpoint URLs.
  **Why**: HTTPS-only validation still permits user information, fragments, and
  sensitive query parameters that are retained and passed to the SDK.
  **Fix**: Apply the shared safe endpoint policy before storage and add detached,
  non-echoing constructor tests for every sensitive query alias.

- **[P0.5]** `src/survey_scribe/providers/azure.py:74` - Pre-request validation
  and SDK setup failures can retain credentials in traceback locals.
  **Why**: Constructor frames retain `api_key`, static header mappings, and SDK
  client kwargs even when the displayed message is safe.
  **Fix**: Clear package-owned references and raise fresh safe failures outside
  raw handlers. Add traceback-local tests for static validation and failing SDK
  construction.

## P1 - Critical

- **[P1.1]** `src/survey_scribe/providers/openai_compatible.py:203` - Mixed
  failures can report the wrong final error.
  **Why**: Retry eligibility uses validation attempts while the loop is bounded
  by outbound transport attempts, so a retry can be scheduled when no outbound
  allocation remains.
  **Fix**: Check the remaining outbound budget before every delay and raise the
  current failure category on the final attempt.

- **[P1.2]** `src/survey_scribe/providers/openai_compatible.py:329` - The recorded
  schema digest differs from the schema sent to Instructor.
  **Why**: A root `title` is added after descriptor hashing and the test removes
  it before comparison.
  **Fix**: Hash the exact effective wire schema or keep the transport field out of
  transmitted parameters. Compare the captured schema without mutation.

- **[P1.3]** `tests/contract/providers/test_azure_sdk_headers.py:18` - Module-wide
  TEST-NET allowances weaken the claimed offline boundary.
  **Why**: `allow_hosts` takes precedence over `--disable-socket`, leaves DNS and
  some socket operations available, and can conflict with Windows loopback needs.
  **Fix**: Permit only the event-loop mechanism required by the platform and add
  explicit DNS and external-socket canaries.

- **[P1.4]** `tests/contract/providers/test_azure_sdk_headers.py:100` - New
  synthetic secret fingerprints are not approved by the repository scanner.
  **Why**: The security gate matches path, type, and fingerprint and can reject
  the PR even though the values are synthetic.
  **Fix**: Use policy-compliant synthetic forms or the approved suppression
  mechanism without changing the protected baseline.

## P2 - Important

- **[P2.1]** `src/survey_scribe/providers/azure.py:72` - Async sensitive-header
  callbacks are accepted but fail late and can leave unawaited coroutines.
  **Fix**: Reject coroutine functions during construction and safely reject or
  close awaitable callback results.

- **[P2.2]** `tests/contract/providers/test_azure_sdk_headers.py:48` - The real SDK
  test omits token-provider authentication and real retry/failure responses.
  **Fix**: Cover token plus gateway headers, 429/503 or malformed responses,
  exact request counts, refreshed values, and detached final errors.

- **[P2.3]** `tests/contract/providers/test_import_boundaries.py:40` - SDK boundary
  checks ignore constant-string `import_module()` calls.
  **Fix**: Inspect dynamic import calls and enforce a reviewed adapter allowlist.

- **[P2.4]** `tests/package/test_clean_install.py:107` - Exact-wheel verification
  does not exercise the new Azure header API.
  **Fix**: Import, construct, and execute an injected offline Azure provider from
  the exact installed wheel.

- **[P2.5]** `src/survey_scribe/providers/azure.py:46` - Public constructor
  documentation does not describe the three header arguments and safety rules.
  **Fix**: Document copying, callback timing, required names, collisions, reserved
  fields, safe failures, and the supported Azure-compatible API scope. Correct
  callback-retention and freshness wording in the public guides.

- **[P2.6]** `tests/architecture/test_runtime_boundaries.py:75` - Dependency-name
  normalization has PEP 503 and direct-reference bypasses.
  **Fix**: Normalize every `[-_.]+` run or parse requirements with the standard
  packaging parser before applying the deny policy.

- **[P2.7]** `tests/contract/providers/test_provider_adapters.py:244` - The input
  copy/freeze test has no request-level behavioral assertion.
  **Fix**: Generate through a capturing completion and prove original metadata
  and required-header snapshots are used after caller mutation.

## P3 - Minor

- **[P3.1]** `tests/contract/providers/test_azure_sdk_headers.py:130` - The
  `x-stainless-retry-count` assertion relies on an undocumented SDK header.
  **Fix**: Replace it with a failing transport response and assert the exact HTTP
  request count while package attempts equal one.

## Passed

- `cg-architecture`: Provider-neutral facade and SDK import boundaries remain intact.
- Required implementation evidence passed before review, including the exact
  Python 3.11-3.13 isolated offline matrix.
- No public credential value was found in source or documentation.

## Brain Context

- Equivalent credential representations require the same redaction and safe URL
  policy. Source: `.cg-docs/solutions/bugs/2026-08-28-close-credential-redaction-boundaries.md`.
- The implementation remains governed by
  `.cg-docs/plans/2026-09-04-azure-gateway-header-compatibility.md`.
