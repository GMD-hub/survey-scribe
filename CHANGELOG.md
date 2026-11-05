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
  the established behaviour, except OCR (see Changed). OCR remains limited to approved
  English model artifacts.
- `SourceRegistry.supported_suffixes()`.
- `SourceCoverage.blank_units` lists the units with no content to read, such as a
  blank PDF page. A blank unit is not a failure. The other adapters leave it empty.

### Changed

- PDF OCR defaults to `auto`. The PDF adapter now decides the read page by page.
- Before conversion, a page check gives each page one status. The first match wins:
  1. `unreadable`: the page does not load.
  2. `blank`: fewer than 0.012% dark pixels in a 72 dpi grayscale render, and fewer
     than 32 visible characters. A pixel is dark under gray level 230.
  3. `needs_ocr`: one image covers half the page or more.
  4. `needs_ocr`: the text layer has fewer than 32 visible characters.
  5. `machine_readable`: any other page.
- The test for blank comes first. A blank page gets no read in any mode, also with
  `ocr="always"`. It goes in `coverage.blank_units` with no block and no diagnostic.
- A page with only a one-digit page number is blank. A page with only a longer page
  number or one short word can be blank too. Then that word is lost.
- `auto` reads the text-layer pages in one Docling call with no OCR. It reads each
  `needs_ocr` page alone with OCR. `always` runs full-page OCR on each page that is
  not blank. `never` reads the text layer of each page that is not blank.
- In `auto` mode, OCR reads a `needs_ocr` page in the Docling default mode, as the
  `auto` option did before. The text layer of the page stays, and OCR reads the areas
  that it does not cover. Only `always` runs full-page OCR, which replaces the text
  layer.
- A `machine_readable` page gets no OCR. Text inside an image under half of the page
  is not read, also when another page of the file needs OCR.
- The blocks of both reads go in page order. A heading on an OCR page is the section
  of the later pages too. The text-layer blocks keep the order of the Docling read.
- Docling can join text across a page break. If the joined block crosses a page that
  the text-layer read does not keep, the adapter cuts it at each page break. Each
  part goes to its own page.
- A Docling failure on one page does not stop the conversion. Only that page fails,
  and the other pages keep their blocks. A failed read whose errors do not name every
  page of the read still stops the conversion, as before.
- Each page that OCR reads gets a `PDF_PAGE_OCR` warning with the reason. In `never`
  mode, a `needs_ocr` page gets a `PDF_PAGE_TEXT_INCOMPLETE` warning.
- The adapter needs the EasyOCR artifacts only when a page gets an OCR read. If they
  are missing, the error names the pages.
- The page check measures an image in a scaled form XObject at its size on the page.
- On a 19-page questionnaire with a text layer, forced OCR kept 88 of 113 question
  numbers and the text layer kept 112.
- Chunking keeps a table with the text printed above it: a table joins the running
  chunk while the token budget allows (it is still never split) instead of always
  opening a chunk of its own.
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
- Variable extraction chunking counts each part as the request sends it: the escaped
  text, the JSON label and the block id. The first chunking now fits the request limit,
  also for documents with many short OCR blocks. The overlap still counts the plain
  text, so each chunk repeats the same prior text as before. `chunk_document` has a new
  optional `part_cost` argument. Without it, the chunks do not change.

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
