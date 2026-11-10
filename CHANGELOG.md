# Changelog

All notable changes to Survey Scribe are documented in this file. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `PdfConversionOptions` for the PDF adapter (`SourceRegistry.default(pdf_options=...)`
  or `SURVEY_SCRIBE_PDF_*` variables): OCR `always | auto | never` (`never` reads the
  text layer alone, any script, no EasyOCR artifacts), inferred heading levels with
  `section_path` ancestors, page furniture, and TableFormer mode. Unset options keep
  the established behaviour. OCR remains limited to approved English model artifacts.
- `SourceRegistry.supported_suffixes()`.
- Legacy binary `.doc` and `.xls` sources (`DoclingOfficeAdapter`): Docling converts
  them with LibreOffice and parses them with its Word and Excel pipelines, in the same
  killable, network-disabled worker as PDF conversion. A workbook's coverage is counted
  by sheet. LibreOffice (`soffice`) must be on PATH; no model artifacts are needed.
- `SourceLimits.external_links` (`"refuse"` by default, or `"strip"`): DOCX and XLSX
  packages with external relationships (hyperlinks, linked workbooks, remote
  templates) can be converted with the links dropped and never followed, reported by
  one `EXTERNAL_LINK_STRIPPED` warning diagnostic with a count. Formulas and macros
  stay refused.
- PDF conversion by page range (`PdfConversionOptions.pages_per_chunk`; the default
  `None` converts in one call, as before): `SourceRegistry.convert(..., progress=...)`
  and `DoclingPdfAdapter(progress=...)` report pages done after each range;
  `partial_on_deadline=True` returns the finished ranges at the deadline
  (`PDF_DEADLINE_PARTIAL` warning, the rest as failed coverage) instead of raising;
  `first_pages=N` converts only the first N pages. Also read from
  `SURVEY_SCRIBE_PDF_PAGES_PER_CHUNK`, `SURVEY_SCRIBE_PDF_FIRST_PAGES`, and
  `SURVEY_SCRIBE_PDF_PARTIAL_ON_DEADLINE`.
- A PDF or legacy Office worker that dies reports its exit code or the signal that
  killed it (a likely out-of-memory kill for signal 9).
- `SourceConversionError.detail`: an unexpected failure inside the PDF or legacy Office
  worker now reports the underlying error type, message, raising location, and up to
  two chained causes (one line, at most 500 characters), also appended to the message,
  instead of a bare "conversion failed". Typed conversion, format, and timeout errors
  raised inside the worker keep their own messages.

### Changed

- PDF inspection distinguishes PDFium failures: a damaged PDF raises
  `SourceFormatError` ("damaged or not a valid PDF") instead of "extension does not
  match file content", a file PDFium cannot open raises `SourceConversionError` with
  the detail, and an unsupported security handler raises `SourceSecurityError`.
- Chunking keeps a table with the text printed above it: a table joins the running
  chunk while the token budget allows instead of always opening a chunk of its own.
- PDF section headings keep their ancestors when heading levels are inferred; with
  the default flat headings the section path is unchanged.
- A numbered question the layout model reads as a list item keeps its number: the
  item's marker is prefixed to its text (`8. How much ...`), as the page prints it.
- Variable extraction prompt 1.1.0: `question_text` and `module` are copied verbatim
  with their printed numbering, and a table's repeated slots (members, days, numbered
  blank rows) are one variable per question while rows and columns labelled with
  different things are one variable per cell. The prompt is about 600 tokens longer
  than 1.0.0; a `PipelineConfig.max_request_tokens` tuned tightly to the old prompt
  needs that much more.

### Fixed

- PDF contract tests now cover text-layer conversion without relying on missing
  optional dependencies. OCR modes keep local model and offline conversion controls.
- Inferred heading paths preserve sibling sections even when heading levels are skipped.
- PDF options reject noninteger heading limits and unsupported OCR language settings.
- Packed extraction requests account for serialized source-part metadata and overlap
  before they are sent to a provider.
- A table larger than the request budget no longer fails the whole document
  ([#18](https://github.com/GMD-hub/survey-scribe/issues/18)). Chunking splits it into
  row groups that each repeat the table's first (header) row, keep the physical table
  id, and carry the group's source row range in `provenance`; the result reports a
  `SOURCE_TABLE_SPLIT` warning with the table id and part count. Only a row that cannot
  fit with the header is an error, a `SOURCE_LIMIT_EXCEEDED` diagnostic naming the
  table and block.
- A merged table cell in a Docling-converted document (PDF, `.doc`, `.xls`) is written
  once instead of in every column it spans: table rows are read from Docling's cell
  grid, the text in the first column of the span and the columns it continues into
  left empty. A cell spanning rows keeps its text in each row, so a row group of a split
  table still carries it. Header rows still join into one header row (`Paid.GEL`); a
  header cell spanning header rows counts once (`Code`, not `Code.Code`). A table's
  rows, and the request budget they take, shrink by the repeated text.

### Security

- Updated vulnerable locked dependencies and the compatible Docling stack. The
  existing time-limited `diskcache` and `accelerate` exceptions are unchanged.

## [0.1.3] - 2026-10-14

### Fixed

- Corrected PyPI author credits to include R. Andres Castaneda and Stephen
  Nwobike alongside the World Bank Global Monitoring Database team.
- Set author and maintainer contact metadata to `acastanedaa@worldbank.org`,
  separate from Stephen's author credit. Stephen is not a package maintainer.
- Added exact distribution metadata checks for author names and contact fields.

## [0.1.2] - 2026-10-13

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
- Added Stephen Nwobike to package author metadata.

### Changed

- Runtime dependencies now use compatible ranges while the committed `uv.lock`
  retains exact engineering versions.

### Fixed

- Updated Docling and multidict minimum versions to include security fixes.
- Native XLSForm `source_format="xlsform"` now binds to its validated XLSX
  snapshot for provider-free questionnaire routing.
- Public installation guidance no longer presents an unavailable PyPI release or
  a stale source revision as the primary installation path.

### Security

- Recorded a time-limited risk acceptance for unresolved `diskcache` and
  `accelerate` findings in optional dependencies. Neither package has a verified
  upstream fix as of 2026-10-13. The acceptance expires on 2026-11-13; see the
  [dependency security review](security/optional-dependency-risk-review-2026-10-13.md).

## [0.1.1] - 2026-10-01

### Changed

- Updated the tested dependency lock to `urllib3 2.8.0` and
  `transformers 5.17.0`, with compatible Hugging Face Hub and tokenizers versions.
- Updated installation guidance and release-artifact examples.

### Fixed

- Resolved new urllib3 and Transformers dependency security findings without
  adding security exceptions, and removed five obsolete Transformers exceptions.
- Package SBOM tests now select the current package version rather than `0.1.0`.
- CI now generates the exact-wheel SBOM before running package tests so that
  generated release evidence is checked rather than skipped.

The public API and SVIS schemas are unchanged from `0.1.0`.

## [0.1.0] - 2026-09-10

Version `0.1.0` is now published to PyPI and the release workflow completed.

### Added

- Installable `survey-scribe` package with typed SVIS Pydantic models.
- Bootstrap `survey-scribe` command.
- Legacy schema re-export and characterization suite.
- Cross-platform Python 3.11-3.13 CI and clean-wheel installation checks.

### Changed

- Release packaging and trust/publishing configuration for PyPI via GitHub workflow.
- Public installation guidance now points to the approved release path.

### Fixed

- Publication metadata and changelog state now reflect the approved 0.1.0 release.

[Unreleased]: https://github.com/GMD-hub/survey-scribe/commits/main
[0.1.3]: https://github.com/GMD-hub/survey-scribe/releases/tag/v0.1.3
[0.1.2]: https://github.com/GMD-hub/survey-scribe/releases/tag/v0.1.2
[0.1.1]: https://github.com/GMD-hub/survey-scribe/releases/tag/v0.1.1
[0.1.0]: https://github.com/GMD-hub/survey-scribe/releases/tag/v0.1.0
