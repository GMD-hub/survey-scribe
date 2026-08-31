---
date: 2026-08-28
depth: full
type: standard
plan: .cg-docs/plans/2026-08-28-survey-scribe-production-package-refined.md
findings:
  P0.1: fixed
  P0.2: fixed
  P0.3: open
  P0.4: open
  P0.5: open
  P0.6: open
  P0.7: open
  P0.8: open
  P0.9: open
  P0.10: open
  P0.11: open
  P0.12: fixed
  P0.13: fixed
  P0.14: fixed
  P1.1: open
  P1.2: fixed
  P1.3: open
  P1.4: open
  P1.5: open
  P1.6: open
  P1.7: open
  P1.8: open
  P1.9: open
  P1.10: open
  P1.11: fixed
  P1.12: fixed
  P1.13: open
  P1.14: fixed
  P2.1: fixed
  P2.2: fixed
  P2.3: fixed
  P2.4: fixed
  P2.5: open
---

# Review Report: Survey Scribe Production Package Completion

**Review mode**: full
**Files reviewed**: 29 implementation, test, script, configuration, and workflow-state files
**Findings**: 33 (P0: 14, P1: 14, P2: 5, P3: 0)

## P0 - Blocking

### **[P0.1]** `src/survey_scribe/config.py:73` - Configuration can expose credentials `[safe_auto]`

`base_url` accepts user information and secret query or fragment values, malformed
credential inputs can appear in Pydantic errors, and nested TOML secret keys bypass the
top-level check. Reject secret-bearing URLs and recursively reject secret-named TOML
keys before validation; hide input values in validation errors.

### **[P0.2]** `src/survey_scribe/errors.py:16` - Free-text redaction misses credentials `[safe_auto]`

Non-Bearer authorization schemes, proxy authorization, quoted JSON assignments, URL
user information, and keys such as `client_secret` can pass through unchanged. Redact
all authorization values and use one shared sensitive-key policy.

### **[P0.3]** `src/survey_scribe/serialization/artifacts.py:85` - Publication is not process-crash consistent `[manual]`

A crash between compatibility projection and active-pointer replacement can publish two
different generations. Directory sync errors are suppressed, and the generations parent
is not durably synchronized. Use a durable recoverable transaction or journal, staging
rename, authoritative pointer recovery, and platform-specific required directory flushes;
test hard process exits at every publication stage.

### **[P0.4]** `src/survey_scribe/serialization/artifacts.py:60` - Internal symlinks can escape the output root `[manual]`

Pre-created symlinks or Windows reparse points under `.survey-scribe/<survey_id>` can
redirect writes outside `output_dir`. Use no-follow, descriptor-relative operations and
reject reparse points for every internal component.

### **[P0.5]** `src/survey_scribe/serialization/artifacts.py:145` - Lock ownership is bypassable and crash-stale `[manual]`

The lock descriptor closes before the transaction. Deleting the marker permits concurrent
writers, while process death leaves a permanent lock. Hold an OS-released lock for the
complete transaction and add crash/concurrency tests.

### **[P0.6]** `src/survey_scribe/results.py:104` - Survey identities can diverge or alias `[manual]`

The envelope ID can differ from a mutable output ID, and case-insensitive or trailing-dot
filesystem aliases can share artifact paths. Validate a detached write snapshot, use an
exact-ID internal key, and reject legacy filename aliases and reserved names.

### **[P0.7]** `src/survey_scribe/sources/base.py:117` - Partial source conversion cannot be represented `[manual]`

The normalized document has no diagnostics, failed units, or coverage. Docling status,
errors, and page coverage can be discarded, so missing pages appear successful. Add
immutable source diagnostics and coverage or failed-unit metadata.

### **[P0.8]** `src/survey_scribe/sources/chunking.py:89` - `max_tokens` is not a hard limit `[manual]`

Oversized blocks and tables remain intact and overlap is added outside the budget. Split
text deterministically, split or explicitly reject oversized tables, reserve overlap, and
validate every final estimate.

### **[P0.9]** `src/survey_scribe/sources/base.py:291` - Rendered table text is lossy `[manual]`

Pipes and embedded newlines are not escaped, so cells and rows change before extraction.
Pass structured rows to the pipeline or use a lossless canonical representation.

### **[P0.10]** `src/survey_scribe/sources/docling.py:220` - Common DOCX content is silently dropped `[manual]`

Only direct body paragraphs and tables are processed. Content controls and other permitted
containers can disappear without a diagnostic. Walk supported containers in document order
and fail or diagnose unsupported nonempty content.

### **[P0.11]** `src/survey_scribe/sources/docling.py:635` - PDF multi-page provenance is truncated `[manual]`

Only the first Docling provenance item is retained. Extend normalized provenance to carry
all pages or a page range and test multi-page blocks and tables.

### **[P0.12]** `src/survey_scribe/sources/tabular.py:193` - Stale XLSX dimensions can omit cells `[safe_auto]`

Openpyxl read-only mode can trust a stale worksheet dimension and silently truncate later
cells. Validate observed row/cell coordinates against declared dimensions and Excel limits
before loading the workbook.

### **[P0.13]** `src/survey_scribe/sources/base.py:127` - Provenance consistency is not validated `[safe_auto]`

Documents accept duplicate table IDs, table/block provenance mismatches, and source names
that differ from the document. Enforce unique IDs and consistent source/provenance ranges.

### **[P0.14]** `src/survey_scribe/results.py:119` - Provider failure can report `success` `[safe_auto]`

`PROVIDER_FAILED` with usable output and default warning severity does not affect status.
Treat provider failure as completeness-affecting and test output-plus-failure behavior.

## P1 - Critical

### **[P1.1]** `src/survey_scribe/serialization/artifacts.py:201` - Failed questionnaire text can enter sidecars `[manual]`

Redaction derives questionnaire text only from successful output. Failed-block or diagnostic
text can remain. Build diagnostics from safe templates and carry all sensitive source spans
through approved redaction before serialization.

### **[P1.2]** `src/survey_scribe/config.py:37` - Numeric and Boolean controls coerce unsafe values `[safe_auto]`

Booleans, strings, NaN, and infinity can be accepted for concurrency, retries, ratios, and
deadlines. Use strict fields, finite checks, and explicit environment parsing.

### **[P1.3]** `src/survey_scribe/sources/docling.py:73` - OCR integrity is not enforced by conversion `[manual]`

Runtime accepts any existing artifact directory, validator and converter can select different
caches, and validated ZIPs do not prove Docling's extracted `EasyOcr/*.pth` layout. Use one
resolver and preparation path, verify exact consumed artifacts, configure English-only OCR,
disable downloads, and run a real network-blocked smoke.

### **[P1.4]** `src/survey_scribe/sources/docling.py:389` - PDF preflight is not authoritative `[manual]`

Raw byte patterns miss object-stream pages and encryption. Use PDFium in a bounded preflight
worker and enforce the page ceiling before OCR.

### **[P1.5]** `src/survey_scribe/sources/docling.py:325` - Worker crash and cleanup are not bounded `[manual]`

A child exit without a queue result waits for the full deadline, and joins can block without
a timeout. Wait on result IPC and process sentinel, then use bounded terminate/kill cleanup.

### **[P1.6]** `src/survey_scribe/sources/docling.py:193` - Cell ceilings do not cover all table formats `[manual]`

DOCX, HTML, Markdown, and PDF can create tables above `max_cells`. Apply one cumulative cell
budget during parsing and before PDF worker transfer.

### **[P1.7]** `src/survey_scribe/sources/base.py:250` - Archive entry and parser resource bombs remain `[manual]`

Entry-count bombs, full XML materialization, and checks outside the deadline can exhaust
memory before existing byte/ratio controls apply. Add entry, filename, XML depth/element,
and relevant-part ceilings and stream parsing under one deadline.

### **[P1.8]** `src/survey_scribe/sources/base.py:244` - Source validation has replacement races `[manual]`

Files are checked and reopened later, so content or size can change. Process an already
validated handle or a private bounded snapshot with a content digest.

### **[P1.9]** `src/survey_scribe/results.py:58` - Frozen diagnostics contain mutable or unordered details `[manual]`

Nested dictionaries, lists, sets, NaN, and arbitrary objects can mutate or serialize
nondeterministically. Restrict details to finite JSON data and recursively freeze it.

### **[P1.10]** `src/survey_scribe/results.py:139` - Generic result writes are coupled to SVIS `[manual]`

Every generic result writes an `_svis.json` compatibility projection. Add an artifact-plan
or serializer port and restrict legacy projection to SVIS output.

### **[P1.11]** `src/survey_scribe/serialization/legacy.py:13` - JSON key coercion can lose entries `[safe_auto]`

Non-string keys such as `1` and `"1"` collapse in JSON mode. Reject non-string mapping keys
recursively before JSON conversion and add collision tests.

### **[P1.12]** `tests/package/test_clean_install.py:64` - Exact-wheel tests omit Phase 2 runtime `[safe_auto]`

The isolated install does not require or import new modules. Assert wheel members, import
representative APIs under isolation, and run an offline text-source conversion.

### **[P1.13]** `.cg-docs/work-reports/2026-08-28-survey-scribe-production-package-refined.md:108` - Coverage gate is not met `[manual]`

The 158-test run did not enable coverage; a branch-coverage run reports 84.11%, below the
configured 95% gate. Add missing branch tests and extend the existing CI selection without
lowering the threshold.

### **[P1.14]** `src/survey_scribe/sources/base.py:216` - Windows drive paths can be mistaken for URLs `[safe_auto]`

Forward-slash drive paths such as `E:/project/questionnaire.txt` match the URL pattern.
Recognize native drive paths before remote-scheme rejection and add Windows coverage.

## P2 - Important

### **[P2.1]** `.gitignore:18` - Sensitive local outputs are not ignored `[safe_auto]`

Ignore local TOML, internal artifact directories, compatibility JSON outputs, and approved
OCR archive names while retaining versioned test fixtures.

### **[P2.2]** `pyproject.toml:132` - Pyright omits new tests and the validator `[safe_auto]`

Include contract and integration tests plus the OCR script in normal type checks.

### **[P2.3]** `.cg-docs/work-reports/2026-08-28-survey-scribe-production-package-refined.md:102` - Report stores a user-specific path `[safe_auto]`

Replace the absolute account path with a generic external temporary-cache reference.

### **[P2.4]** `src/survey_scribe/sources/tabular.py:46` - CSV is fully buffered before limits apply `[safe_auto]`

Stream UTF-8-SIG input into `csv.reader` and apply NUL, deadline, and cell checks as rows
arrive instead of creating multiple complete buffers.

### **[P2.5]** `README.md:12` - User documentation still describes Phase 2 APIs as future work `[manual]`

Document the available low-level config, result, artifact, source, chunking, optional-extra,
and OCR validation APIs without claiming that later provider/client work exists.

## Passed

- Ruff lint and format checks passed.
- Pyright reported no type errors before the scope finding above.
- The non-coverage full suite passed with 158 tests.
- No credential file, private key, live API token, or repository-local OCR archive was found.
- Lazy optional imports and wheel inclusion of the new package modules were confirmed.
- All 10 routed review agents produced usable, changed-file-specific output.

## Autofix Result

- Applied 13 safe fixes: credential URL/error validation, authorization and text
  redaction, stale XLSX-dimension rejection, normalized provenance invariants,
  provider-failure status, strict finite controls, non-string JSON key rejection,
  exact-wheel runtime checks, Windows drive-path handling, sensitive-output ignore
  rules, expanded Pyright scope, generic cache-path reporting, and streaming CSV input.
- Verification after autofix: 190 tests passed; package tests 4 passed; Ruff passed;
  Pyright reported 0 errors and 0 warnings; `git diff --check` passed with line-ending
  warnings only.
- Branch coverage remains open under P1.13: 190 tests passed but coverage was 85.65%,
  below the configured 95% gate.
- 20 manual findings remain open for fix triage.
