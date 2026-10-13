# Optional Dependency Security Review

**Review date:** 2026-10-13

**Decision:** Time-limited acceptance of two exact dependency findings for optional extras

**Approved by:** Repository maintainer
**Expiry:** 2026-11-13

This review supports the Survey Scribe 0.1.2 release. It does not claim that the
affected packages are fixed. The findings remain in optional provider and PDF
dependency trees until upstream releases verified fixes or Survey Scribe changes
those dependency designs.

## Scope

The release updates `docling` to a minimum of 2.132.0 and `multidict` to a
minimum of 6.9.1. These versions address the reported Docling and multidict
advisories. The base package install does not include the provider or PDF extras
that introduce the two remaining packages.

The temporary acceptance applies only to these existing fingerprints:

| Package | Finding | Optional extra | Fingerprint |
| --- | --- | --- | --- |
| `diskcache` 5.6.3 | PYSEC-2026-2447, CVE-2025-69872 | `openai`, `anthropic` | `46ce96b33fd236434d02ea61f041bc490291544f98a3cc0b55be94bc01981c02` |
| `accelerate` 1.14.0 | PYSEC-2026-3804, CVE-2026-69112 | `pdf` | `9eb6d2524791c88dba4d96a50a4807829fc8412368eba6a82e8774090b1a306d` |

## DiskCache

Instructor brings DiskCache into the optional provider environments. Survey
Scribe uses Instructor for structured provider responses, but repository code
does not configure DiskCache or use its persistent-cache API. The routing cache
in `src/survey_scribe/routing/extraction.py` is in-memory and stores validated
models. The advisory requires an attacker to write a pickle payload to a
DiskCache directory that the application later reads.

No patched DiskCache release was available on 2026-10-13. The accepted exposure
is limited to provider extras. Do not configure a shared or attacker-writable
DiskCache directory. Remove this exception after a verified upstream fix or
after replacing the Instructor dependency design.

## Accelerate

Docling's standard extra brings Accelerate into the optional PDF environment.
The advisory concerns unsafe paths in sharded checkpoint indexes passed to
checkpoint-loading functions. Survey Scribe does not call those functions,
accept arbitrary checkpoint indexes, or treat a questionnaire document as a
model checkpoint. The PDF adapter validates configured OCR artifacts against
expected hashes before conversion and disables network access during
conversion. These checks do not validate every model file that Docling may
manage. Keep Docling model and artifact directories controlled. A hostile
document still requires process isolation and network policy, as described in
`docs/guides/sources.md`.

No verified fixed Accelerate release was available on 2026-10-13. Version 1.15.0
was not accepted as a fix because the reviewed source still lacked the required
checkpoint path validation. The accepted exposure is limited to the optional
PDF extra and controlled model artifacts. Do not load untrusted checkpoint
directories. Remove this exception only after a verified upstream fix or a
tested Docling dependency profile that no longer requires Accelerate.

## Decision And Expiry

The repository maintainer approved a temporary, exact-fingerprint risk
acceptance on 2026-10-13 so the release can proceed without suppressing the
security gate. The entries in `security/allowlist.toml` expire on 2026-11-13.
This decision does not mark either issue fixed and must not be renewed
automatically. Re-run the dependency audit before expiry. Remove each entry
after the affected dependency is fixed or removed; otherwise, obtain a new review
and explicit approval before extending it.

## Evidence

- [DiskCache advisory PYSEC-2026-2447](https://osv.dev/vulnerability/PYSEC-2026-2447)
- [DiskCache GitHub advisory GHSA-w8v5-vhqr-4h9v](https://github.com/advisories/GHSA-w8v5-vhqr-4h9v)
- [Accelerate advisory PYSEC-2026-3804](https://osv.dev/vulnerability/PYSEC-2026-3804)
- [Accelerate GitHub advisory GHSA-4j2p-28q2-5m79](https://github.com/advisories/GHSA-4j2p-28q2-5m79)
- [Accelerate 1.15.0 checkpoint-loading source](https://github.com/huggingface/accelerate/blob/v1.15.0/src/accelerate/utils/modeling.py#L1941-L1944)
- [Upstream Accelerate path-validation proposal](https://github.com/huggingface/accelerate/pull/4138)
