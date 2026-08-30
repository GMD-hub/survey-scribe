---
date: 2026-08-28
depth: light
parent-review: .cg-docs/reviews/2026-08-28-survey-scribe-production-package-refined-review.md
type: verification
findings:
  P0.1: fixed
  P0.2: fixed
  P0.3: fixed
  P0.4: fixed
  P1.1: fixed
  P1.2: fixed
---

# Verification Review: Survey Scribe Production Package Completion

**Review mode**: light verification
**Parent review**: `.cg-docs/reviews/2026-08-28-survey-scribe-production-package-refined-review.md`
**Findings**: 6 (P0: 4, P1: 2, P2: 0, P3: 0)

## P0 - Blocking

### **[P0.1]** `src/survey_scribe/config.py:124` - Base URLs still accept secret aliases

The shared sensitive-key policy does not recognize `token`, `key`, or `sig` as complete
query parameter names. These values pass validation and serialize unchanged. Use one shared
query-key policy for validation and redaction and add the aliases to regression tests.

### **[P0.2]** `src/survey_scribe/errors.py:17` - Authorization assignment syntax is not redacted

`Authorization=Basic ...`, `Proxy-Authorization=Custom ...`, and
`bearer_token=...` remain visible. Cover both colon and equals separators and include all
shared authorization and bearer-token keys in free-text tests.

### **[P0.3]** `src/survey_scribe/sources/tabular.py:203` - Duplicate or foreign XLSX dimensions bypass validation

Any local-name `dimension` overwrites the prior bound. A second or foreign-namespace element
can hide the stale SpreadsheetML dimension that openpyxl uses. Match the exact namespace,
accept only one direct worksheet dimension, and reject duplicates.

### **[P0.4]** `src/survey_scribe/sources/base.py:91` - One-sided provenance ranges remain valid

`row_start` or `row_end` can be set alone, which bypasses the table row-span invariant.
Require both endpoints or neither and test each one-sided case.

## P1 - Critical

### **[P1.1]** `src/survey_scribe/serialization/legacy.py:31` - Nested models bypass key validation

Recursive checking handles containers but not nested Pydantic models. Convert the complete
object graph to Python mode before checking mappings, then perform JSON-mode conversion.

### **[P1.2]** `tests/package/test_distribution_contents.py:27` - Exact-wheel checks omit Phase 2 modules

The member set and isolated smoke omit `sources/chunking.py`, `sources/ocr.py`, and public
subpackage initializers. Require all Phase 2 modules and import representative chunking and
OCR APIs under isolated wheel execution.

## Verification Evidence

- Both routed agents produced usable changed-file-specific output.
- One agent ran 101 fixed-area tests; all passed.
- The other ran 186 non-package tests; all passed.
- Ruff passed and Pyright reported 0 errors and 0 warnings.
- No files were modified by review agents.

## Result

Verification did not converge. All six findings remain open for `/cg-fix-triage`.
