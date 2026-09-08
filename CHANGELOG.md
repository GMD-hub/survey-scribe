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

### Changed

- Runtime dependencies now use compatible ranges while the committed `uv.lock`
  retains exact engineering versions.

## [0.1.0] - 2026-08-26

### Added

- Installable `survey-scribe` package with typed SVIS Pydantic models.
- Bootstrap `survey-scribe` command.
- Legacy schema re-export and characterization suite.
- Cross-platform Python 3.11-3.13 CI and clean-wheel installation checks.

[Unreleased]: https://github.com/GMD-hub/survey-scribe/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/GMD-hub/survey-scribe/releases/tag/v0.1.0
