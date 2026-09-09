# Changelog

All notable changes to Survey Scribe are documented in this file. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- PyPI-ready project metadata and MIT license declaration.
- MkDocs documentation with installation, usage, examples, and API reference.
- Coverage enforcement and release-artifact validation in CI.
- Additive routed SVIS models, deterministic directed-multigraph validation,
  source-grounded evidence, and append-only discrepancy review.
- `QuestionnaireRouter` with native XLSForm routing and structured-provider integration.
- Deterministic routing-quality evaluation, routing-schema export, and routing documentation.
- Validated static metadata headers and per-attempt auxiliary secret headers for
  direct `AzureOpenAIProvider` injection through compatible gateways.
- Extraction-first public guides for completed questionnaires, skip patterns,
  Palantir Foundry, Microsoft Foundry, mAI Factory, and AI providers.

### Changed

- Runtime dependencies now use compatible ranges while the committed `uv.lock`
  retains exact engineering versions.

### Fixed

- Native XLSForm `source_format="xlsform"` now binds to its validated XLSX
  snapshot for provider-free questionnaire routing.
- Public installation guidance no longer presents an unavailable PyPI release or
  a stale source revision as the primary installation path.

## 0.1.0 - Unpublished

This version remains a source-tree milestone. No approved package-index or GitHub
release is available.

### Added

- Installable `survey-scribe` package with typed SVIS Pydantic models.
- Bootstrap `survey-scribe` command.
- Legacy schema re-export and characterization suite.
- Cross-platform Python 3.11-3.13 CI and clean-wheel installation checks.

[Unreleased]: https://github.com/GMD-hub/survey-scribe/commits/main
