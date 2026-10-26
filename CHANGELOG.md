# Changelog

All notable changes to Survey Scribe are documented in this file. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `PdfConversionOptions` for the PDF adapter (`SourceRegistry.default(pdf_options=...)`
  or `SURVEY_SCRIBE_PDF_*` variables): OCR `always | auto | never` (`never` reads the
  text layer alone, any script, no EasyOCR artifacts), OCR languages, inferred heading
  levels with `section_path` ancestors, page furniture, TableFormer mode. Unset options
  keep the established behaviour.
- `SourceRegistry.supported_suffixes()`.

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
- Chunking keeps a table with the text printed above it: a table joins the running
  chunk while the token budget allows (it is still never split) instead of always
  opening a chunk of its own.
- PDF section headings keep their ancestors when heading levels are inferred; with
  the default flat headings the section path is unchanged.
- A numbered question the layout model reads as a list item keeps its number: the
  item's marker is prefixed to its text (`8. How much …`), as the page prints it.
- Variable extraction prompt 1.1.0: `question_text` and `module` are copied verbatim
  with their printed numbering, and a table's repeated slots (members, days, numbered
  blank rows) are one variable per question while rows and columns labelled with
  different things are one variable per cell. The prompt is about 600 tokens longer
  than 1.0.0; a `PipelineConfig.max_request_tokens` tuned tightly to the old prompt
  needs that much more.

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
