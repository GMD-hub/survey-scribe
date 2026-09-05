---
date: 2026-09-05
title: "Detach Provider Secrets and Preserve Wire Contracts"
category: "bugs"
language: "Python"
tags: [providers, azure, credentials, tracebacks, pydantic, retries, redaction, offline-testing]
root-cause: "Safe messages were emitted while raw exception frames and a second model-validation cycle still retained or changed sensitive request state."
severity: "P0"
---

# Detach Provider Secrets and Preserve Wire Contracts

## Problem

Request-level gateway credentials were absent from normal messages and object
representations, but failure tracebacks could still retain the completion frame
and its header mapping. Re-raising a provider exception or cancellation kept
those frames available to debuggers and error collectors.

The installed Instructor path also returned a validated temporary Pydantic
subclass. Serializing that instance and validating it again could reject aliases,
include computed fields, run validators twice, or apply serializers to the
returned data. Separately, subscription-key text redaction stopped at spaces and
some equivalent URL query spellings were not classified.

## Root Cause

Error-message safety and exception-state safety were treated as the same
boundary. Clearing one outer header variable did not remove inner traceback
frames. Existing normalized transport exceptions were reused instead of replaced
with fresh safe instances.

The schema adapter also treated an already validated wire-model instance as
untrusted input. Its dump-and-revalidate conversion crossed the serialization
and validation boundaries a second time. Finally, mapping keys, URL query names,
and text assignments used separate normalization rules.

## Solution

Keep only safe scalar state from raw failures, leave the originating exception
handler, and then raise a fresh normalized exception:

```python
except ProviderTransportError as error:
    failure = fresh_transport_error(error)

if failure is not None:
    raise failure from None
```

Use the same pattern for process-control exceptions when request-local secrets
can be present. Preserve the control category, but do not preserve the raw
traceback or a secret-bearing message.

An Instructor wire model is already an instance of the requested base model.
Return it without serialization or a second validation cycle:

```python
if isinstance(output, response_model):
    return cast(T, output)
return response_model.model_validate(output)
```

Build the exact effective strict schema, including its deterministic root title,
before canonicalization and hashing. The transport test must compare the
captured schema without removing fields.

Normalize query names once after percent decoding. Use both normalized and
separator-free forms for exact membership. Apply a line-oriented pattern for
unquoted subscription-header values before the generic assignment pattern.

For offline async SDK tests, permit only literal loopback addresses during event
loop setup. An autouse fixture then blocks DNS, TCP connection methods, and UDP
send methods before test code runs. Real SDK tests use `httpx.MockTransport` and
assert request counts so SDK-owned retries cannot hide package retry behavior.

## Prevention

- Inspect traceback locals, `__cause__`, and `__context__`; checking only
  `str(error)` is insufficient for credential-bearing operations.
- Never re-raise third-party or completion-supplied transport exceptions after
  secret headers enter their frames. Create a new normalized package error.
- Do not dump and revalidate an already validated Pydantic subtype. Test aliases,
  serializers, computed fields, and non-idempotent validators.
- Use one query-key classifier for URL validation and textual redaction, including
  compact and percent-encoded spellings.
- Hash the exact schema sent on the wire and compare it without test-side mutation.
- Disable SDK retries and test a real retryable response followed by a
  package-owned retry with refreshed attempt-local headers.
- Exercise new public constructor behavior from the built wheel, not only from
  the source tree.

## Related

- `.cg-docs/solutions/bugs/2026-08-28-close-credential-redaction-boundaries.md`
- `.cg-docs/solutions/testing-patterns/2026-09-03-bound-provider-retries-and-chunk-provenance.md`
- `.cg-docs/reviews/2026-09-04-azure-gateway-header-compatibility-review.md`
- `.cg-docs/plans/2026-09-04-azure-gateway-header-compatibility.md`
- `src/survey_scribe/errors.py`
- `src/survey_scribe/providers/openai_compatible.py`
- `src/survey_scribe/providers/azure.py`
