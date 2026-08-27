---
date: 2026-08-26
depth: full
type: standard
plan: .cg-docs/plans/2026-08-26-survey-scribe-production-package.md
findings:
  P0.1: fixed
  P1.1: fixed
  P1.2: fixed
  P1.3: fixed
  P1.4: fixed
  P1.5: fixed
  P1.6: fixed
  P1.7: fixed
  P2.1: fixed
  P2.2: fixed
  P2.3: fixed
  P2.4: fixed
  P2.5: fixed
  P2.6: fixed
  P2.7: fixed
  P2.8: fixed
  P2.9: fixed
  P2.10: skipped
  P3.1: fixed
  P3.2: fixed
---

# Review Report: Survey Scribe Production Package Phase 1

**Review mode**: full (verification fallback; no prior fixed review existed)
**Files reviewed**: 29 implementation, test, policy, and workflow files plus related execution records
**Findings**: 20 (P0: 1, P1: 7, P2: 10, P3: 2)

## P0 - Blocking

### **[P0.1]** `pyproject.toml:56` - Source distribution includes unrestricted local workspace state `[safe_auto]`

The wheel is bounded, but the sdist contained more than 1,500 entries including
local `.kilo/` and `.cg-docs/` state. This can disclose internal or machine-local
material and makes builds nondeterministic.

**Fix**: Add explicit Hatch sdist contents and an archive-content assertion.

## P1 - Critical

### **[P1.1]** `pyproject.toml:56` - Installed wheel omits the promised `schemas.svis` shim `[safe_auto]`

Editable-checkout tests see the root `schemas/` directory, but the wheel contains
only `survey_scribe`. Existing imports fail after installation.

**Fix**: Include the existing compatibility namespace in the wheel and verify it
from a clean installed environment.

### **[P1.2]** `docs/dependencies.md:9` - Phase 1 closed before the OCR artifact and license decision `[manual]`

The plan requires an EasyOCR model bundle, artifact licenses, URLs, sizes,
checksums, cache/offline setup, and platform decision before locking. The record
explicitly defers these items while V1 and Phase 1 are marked passed.

**Fix**: Complete an institutionally approved artifact/license inventory or
reopen Phase 1 and V1 until that evidence exists.

### **[P1.3]** `tests/package/test_clean_install.py:24` - Clean-install evidence is stale-wheel and warm-cache dependent `[manual]`

The test discovers an arbitrary existing wheel and `uv pip install` relies on an
ambient cache rather than a lock-derived wheelhouse. It also inherits credentials,
and `UV_OFFLINE` does not deny application sockets.

**Fix**: Build one exact reviewed wheel, prepare a checksummed lock-derived
wheelhouse, use a fresh cache, scrub credentials, and deny application network.

### **[P1.4]** `.github/workflows/ci.yml:25` - CI omits manifest and installed-artifact gates `[safe_auto]`

CI neither validates fixture rights/checksums nor installs the artifact it builds.

**Fix**: Validate the manifest, build before package tests, run clean-install
coverage, and inspect archive contents.

### **[P1.5]** `scripts/probe_dependencies.py:43` - Native OCR dependencies are version-checked but not imported `[safe_auto]`

EasyOCR and PyMuPDF can have ABI/import failures while the probe still passes.

**Fix**: Import representative non-downloading public APIs and rerun all three
interpreters.

### **[P1.6]** `scripts/validate_golden_manifest.py:38` - Rights and manifest validation is not a sufficient trust boundary `[manual]`

The validator trusts caller CWD, accepts rights labels without approval evidence,
permits malformed/empty fields and booleans as counts, lacks uniqueness/schema
checks, and does not verify semantic inventory.

**Fix**: Define and test a strict typed manifest rooted at the repository, with
authorship/approval/sanitization provenance and inventory validation.

### **[P1.7]** `tests/characterization/test_schema_contract.py:53` - Legacy compatibility characterization is incomplete `[manual]`

One newly authored numeric fixture cannot establish every enum, union branch,
default/null path, category code type, ordering behavior, intentional correction,
metadata fallback, and CLI outcome promised by C1/V2.

**Fix**: Add independent baseline-derived fixtures and an executable legacy
outcome/correction matrix tied to the baseline commit.

## P2 - Important

### **[P2.1]** `docs/dependencies.md:25` - Probe commands are not isolated and omit explicit script mode `[safe_auto]`

`--no-project` still honors user config and index variables. Explicit `--script`
is needed to guarantee the selected interpreter for cached inline scripts.

**Fix**: Document cross-platform index/config isolation, explicit PyPI policy,
and `--script` for Python 3.11-3.13.

### **[P2.2]** `.cg-docs/work-reports/2026-08-26-survey-scribe-production-package.md:15` - Baseline and evidence context are incomplete `[safe_auto]`

The report omits the baseline commit and legacy dependency source and overstates
the deferred OCR model evidence.

**Fix**: Record the commit/dependency baseline and narrow executed evidence to
the APIs and platform actually checked.

### **[P2.3]** `README.md:99` - Packaged metadata embeds stale legacy setup guidance `[manual]`

The README still directs users to `requirements.txt` and mandatory `itsai`, which
does not install the new package or compatibility shim.

**Fix**: Document `uv sync`/editable install as the bootstrap path and clearly
label the legacy provider setup as deprecated and unavailable publicly.

### **[P2.4]** `.github/workflows/ci.yml:20` - Actions use mutable tags and retained credentials `[manual]`

Mutable major tags can drift, and checkout retains credentials by default.

**Fix**: Pin verified action commit SHAs and set `persist-credentials: false`.

### **[P2.5]** `.gitignore:12` - Secret variants and placeholder reinclusions are incomplete `[safe_auto]`

`.env.*` files are not ignored, and ignoring parent directories defeats the
`.gitkeep` exceptions.

**Fix**: Ignore environment variants except templates and ignore directory
contents rather than parent directories.

### **[P2.6]** `tests/test_schema.py:31` - Ruff formatting is not enforced `[safe_auto]`

Five scoped test files fail `ruff format --check`, while CI runs lint only.

**Fix**: Format the files and add the format check to CI.

### **[P2.7]** `scripts/validate_golden_manifest.py:67` - Fixture hashing materializes whole files `[safe_auto]`

Future questionnaire fixtures may be hundreds of megabytes.

**Fix**: Stream SHA-256 with `hashlib.file_digest`.

### **[P2.8]** `src/survey_scribe/__init__.py:23` - Package version is duplicated `[safe_auto]`

The distribution and runtime version can drift.

**Fix**: Derive the runtime version from installed distribution metadata and
test equality.

### **[P2.9]** `src/survey_scribe/models/svis.py:11` - Schema move dropped field-level public documentation `[manual]`

The compact packaged model omits most semantic descriptions needed by generated
schema/API docs.

**Fix**: Restore the established field semantics as docstrings and Pydantic
descriptions without changing validation or serialization.

### **[P2.10]** `.github/workflows/ci.yml:12` - Phase 1 matrix repeats expensive platform-independent work `[advisory]`

Every matrix cell installs the full development group and repeats static checks
and builds.

**Fix**: Separate one quality/build job from a bounded compatibility matrix while
retaining the final full V13 matrix requirement.

## P3 - Minor

### **[P3.1]** `tests/characterization/test_schema_contract.py:53` - Snapshot contracts whitespace `[advisory]`

The plan excludes indentation and whitespace from compatibility.

**Fix**: Compare parsed values/types and explicit recursive key order separately.

### **[P3.2]** `tests/package/test_clean_install.py:42` - Smoke subprocesses are indirect and unbounded `[safe_auto]`

Two extra `uv run` launchers are unnecessary after environment creation and
subprocesses have no timeout.

**Fix**: Invoke the installed interpreter/entry point directly with a timeout.

## Passed

- All ten reviewers produced usable changed-file findings.
- Existing full suite: 44 passed.
- Ruff lint passed; Pyright reported zero errors.
- Lock check, manifest validation, wheel/sdist build, and warm-cache offline
  install passed.
- No committed credentials or restricted questionnaire data were found.
- Workflow permissions are read-only and no publish/deploy/tag trigger exists.

## Autofix Results

Applied 11 safe fixes:

- Bounded sdist contents and added wheel/sdist content tests.
- Shipped and clean-installed the legacy `schemas.svis` namespace.
- Added manifest, formatting, build, installed-package, and distribution checks to CI.
- Imported EasyOCR and PyMuPDF APIs in all Python 3.11-3.13 probes.
- Documented isolated explicit-script probe commands.
- Recorded the legacy baseline commit and narrowed OCR evidence language.
- Hardened environment-file ignores and placeholder exceptions.
- Streamed fixture hashes and derived the runtime package version from metadata.
- Formatted the scoped Python tree and bounded smoke-test subprocesses.

Verification after autofix: 46 tests passed; Ruff lint and format passed;
Pyright reported zero errors; lock check passed; native API probes passed on
Python 3.11-3.13; wheel and sdist rebuilt with bounded contents.
