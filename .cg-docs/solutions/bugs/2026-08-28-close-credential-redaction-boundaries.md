---
date: 2026-08-28
title: "Close Credential Redaction Boundaries"
category: "bugs"
language: "Python"
tags: [credentials, redaction, pydantic, urls, toml, security, testing]
root-cause: "Credential protection covered named model fields but not alternate URL, error, persisted-config, and free-text representations."
severity: "P0"
---

# Close Credential Redaction Boundaries

## Problem

Typed secret fields were excluded from configuration serialization, but equivalent
credentials could still enter output through other representations:

- URL user information and query aliases such as `token`, `key`, and `sig`.
- Pydantic validation errors that included the rejected input value.
- Secret-named keys nested below the top level in TOML.
- `Authorization` and `Proxy-Authorization` values that used different schemes or
  an equals separator.
- Quoted, escaped, or bearer-token assignments in exception text.

The initial tests covered only direct secret fields, Bearer headers with a colon,
and a small query-key set. A verification review found the remaining forms.

## Root Cause

Credential safety was implemented as separate regular expressions and field-level
rules. Each rule recognized a different vocabulary. This created gaps between
configuration validation, URL validation, error rendering, and recursive data
redaction. Pydantic's default validation output also treated invalid input as useful
diagnostic context even when that input was a credential.

## Solution

Use defense in depth at every boundary:

1. Exclude typed secret fields from model dumps and representations.
2. Set `hide_input_in_errors=True` on configuration models and build public
   validation messages with `errors(include_input=False, include_url=False)`.
3. Reject URL user information, fragments, and exact sensitive query keys before
   the configuration can serialize.
4. Recursively reject secret-named keys in persisted TOML before Pydantic validation.
5. Share one normalized exact-key policy for URL query validation and query-string
   redaction.
6. Redact all authorization schemes with both colon and equals separators, plus
   quoted and escaped credential assignments.

The key distinction is between exact URL query keys and broader diagnostic field
names. Exact matching prevents a generic key such as `key` from redacting unrelated
words, while recursive mapping redaction can use a broader field-name policy.

```python
def is_sensitive_query_key(value: str) -> bool:
    normalized = value.strip().lower().replace("-", "_")
    return normalized in SENSITIVE_QUERY_KEYS
```

Tests must use negative assertions against the complete rendered output, not only
check that known model fields are absent. Include constructor, environment, TOML,
URL, free-text exception, nested mapping, and sidecar paths.

## Prevention

- Keep the sensitive query-key vocabulary in one shared policy.
- Add every newly supported credential syntax to both validation and redaction tests.
- Test common aliases, separators, authorization schemes, quoted JSON, escaped JSON,
  URL user information, nested TOML, and invalid typed inputs.
- Run a separate verification review after security autofixes. The first fix often
  closes the reported example but misses an equivalent representation.
- Never claim that heuristic redaction is a general secret or PII detector. Known
  sensitive values and safe diagnostic templates remain necessary.

## Related

- `.cg-docs/reviews/2026-08-28-survey-scribe-production-package-refined-review.md`
- `.cg-docs/reviews/2026-08-28-survey-scribe-production-package-refined-verify-review.md`
- `.cg-docs/plans/2026-08-28-survey-scribe-production-package-refined.md`
