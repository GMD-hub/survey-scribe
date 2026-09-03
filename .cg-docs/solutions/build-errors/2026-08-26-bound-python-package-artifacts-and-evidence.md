---
date: 2026-08-26
title: "Bound Python Package Artifacts and Evidence"
category: "build-errors"
language: "Python"
tags: [hatchling, uv, packaging, sdist, wheel, offline-install, ci, provenance]
root-cause: "Editable-checkout tests and default build discovery hid missing wheel contents, leaked local state into the sdist, and overstated non-hermetic evidence."
severity: "P0"
---

# Bound Python Package Artifacts and Evidence

## Problem

The package worked in an editable checkout and its wheel built successfully, but
review found several release-boundary failures:

- Hatchling's default sdist discovery included local `.kilo/` and `.cg-docs/`
  state.
- The wheel omitted a required root compatibility namespace that remained
  visible during checkout-based tests.
- CI built artifacts after tests and never installed what it built.
- An offline install passed only with an ambient warm cache and arbitrary wheel
  discovery.
- Dependency probes inherited user index configuration and did not import native
  OCR modules.
- Fixture checksum validation lacked typed provenance and negative tests.

## Root Cause

Source-tree success was treated as package evidence. Editable installs expose
repository paths that a wheel may omit, while build backends can collect more
files into an sdist than a wheel. The evidence commands also relied on ambient
cache, index, and working-directory state rather than explicit trust boundaries.

## Solution

Define every boundary explicitly:

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/survey_scribe", "schemas"]

[tool.hatch.build.targets.sdist]
include = [
  "/README.md",
  "/pyproject.toml",
  "/schemas",
  "/src/survey_scribe",
  "/uv.lock",
]
```

Build before package tests, inspect wheel and sdist member allowlists, install the
exact current-version wheel into a fresh environment, and import both canonical
and compatibility namespaces. Prepare exact dependency wheels in a separate
network-enabled step, then install with a fresh uv cache, `--no-index`, and
`--find-links`. Scrub provider credentials and deny sockets during import/help.

Run standalone probes with explicit script mode and isolated index configuration:

```bash
env -u UV_INDEX -u UV_INDEX_URL -u UV_EXTRA_INDEX_URL \
  uv run --no-config --no-project \
  --default-index https://pypi.org/simple \
  --python 3.11 --script scripts/probe_dependencies.py
```

Probe representative public APIs, not distribution metadata alone. For fixture
policy, anchor paths to the repository, validate typed non-empty provenance,
rights basis, approvals, SHA-256 shape, unique IDs/paths, semantic inventory,
and approved threshold minima. Add negative tests for checksum drift, malformed
counts, empty provenance, and threshold weakening.

## Prevention

- Treat wheel, sdist, and editable checkout as three different filesystems.
- Never infer installed-artifact correctness from source-tree tests.
- Allowlist distribution contents and test the archive members.
- Build once, select one exact versioned artifact, and test that artifact.
- Separate network-enabled dependency preparation from network-denied execution.
- Clear ambient package-index variables and use `--no-config` for evidence runs.
- Import native/binary dependencies on every claimed Python/OS target.
- Do not mark legal, fixture, OCR, or quality evidence passed from metadata
  presence alone.

## Related

- `.cg-docs/reviews/2026-08-26-survey-scribe-production-package-review.md`
- `.cg-docs/plans/2026-08-26-survey-scribe-production-package.md`
- `docs/dependencies.md`
- `tests/package/test_clean_install.py`
- `tests/package/test_distribution_contents.py`
- `scripts/validate_golden_manifest.py`
- `.cg-docs/solutions/testing-patterns/2026-09-01-verify-cross-layer-invariants-beyond-coverage.md`
- `.cg-docs/solutions/testing-patterns/2026-09-02-bind-routing-quality-evidence.md`
