# Local Sources

The source API converts untrusted local files into deterministic
`SourceDocument` records. It preserves block order, complete tables, and physical
provenance without calling a model provider.

## Supported formats

| Suffix | Adapter | Extra |
| --- | --- | --- |
| `.pdf` | Docling PDF conversion with local models; OCR only on the pages that need it | `pdf` |
| `.docx` | Inert DOCX XML parsing | Base |
| `.xlsx` | Read-only XLSForm parsing with native SVIS and routing semantics | `tabular` |
| `.csv` | UTF-8 CSV parsing | Base |
| `.html`, `.htm` | Visible text and table extraction | Base |
| `.md`, `.markdown` | Markdown paragraphs and tables | Base |
| `.txt` | UTF-8 text split at blank lines | Base |

## Convert a source

```python
from pathlib import Path

from survey_scribe.sources import SourceRegistry

registry = SourceRegistry.default()
document = registry.convert(Path("questionnaire.md"))

assert document.trust == "untrusted"
assert tuple(block.order for block in document.blocks) == tuple(
    range(len(document.blocks))
)
```

The registry verifies PDF, DOCX, and XLSX signatures against their suffixes.
Unsupported, missing, remote, and malformed sources raise typed source errors.

## Exact source binding and native routing

Routing uses the additive `convert_with_native()` method. Existing `convert()`
behavior is unchanged.

```python
conversion = registry.convert_with_native(
    Path("questionnaire.xlsx"),
    survey,
)

binding = conversion.source_binding
native = conversion.native
```

The binding covers the validated primary snapshot and confined companions.
`QuestionnaireRouter` requires this exact binding and fails before a provider
call if the source name, format, digest, survey ID, or binding version differs.
An XLSForm `survey` sheet can supply complete typed native routing and therefore
make zero provider calls.

## Normalized model

A `SourceDocument` contains:

- `source_name: str`
- `media_type: str`
- `blocks: tuple[SourceBlock, ...]`
- `coverage: SourceCoverage`
- `diagnostics: tuple[SourceDiagnostic, ...]`
- `snapshot_sha256: str`
- `trust: Literal["untrusted"]`

Each block has a stable ID, zero-based order, text or table kind, rendered text,
and `SourceProvenance`. Table blocks preserve complete cell rows in a
`SourceTable`.

`document.tables` returns tables in source order.

## Resource limits

Default `SourceLimits` protect local processing:

| Limit | Default |
| --- | ---: |
| `max_source_bytes` | 250 MiB |
| `max_pages` | 2,000 |
| `max_archive_expanded_bytes` | 1 GiB |
| `max_archive_ratio` | 100.0 |
| `max_archive_entries` | 10,000 |
| `max_archive_filename_chars` | 512 |
| `max_archive_path_depth` | 20 |
| `max_xml_part_bytes` | 64 MiB |
| `max_xml_elements` | 2,000,000 |
| `max_xml_depth` | 256 |
| `max_cells` | 2,000,000 |
| `max_companions` | 100 |
| `deadline_seconds` | 1,800 seconds |

Set smaller limits for internet-facing or multi-tenant workloads:

```python
from pathlib import Path

from survey_scribe.sources import SourceLimits, SourceRegistry

limits = SourceLimits(
    max_source_bytes=25 * 1024 * 1024,
    max_pages=300,
    max_archive_expanded_bytes=100 * 1024 * 1024,
    max_archive_ratio=20.0,
    max_cells=250_000,
    max_companions=10,
    deadline_seconds=120.0,
)

document = SourceRegistry.default().convert(
    Path("questionnaire.docx"),
    limits=limits,
)
```

## Source bundles

`SourceBundle` confines a primary file and companion files to one resolved root:

```python
from pathlib import Path

from survey_scribe.sources import SourceBundle, resolve_local_source

bundle = SourceBundle(
    root=Path("survey-files"),
    primary=Path("questionnaire.pdf"),
    companions=(Path("codebook.csv"),),
)

resolved = resolve_local_source(bundle)
```

The resolver rejects paths that escape the root. Most adapters validate companion
paths without merging their content. The XLSForm adapter is the exception: a
declared external choice CSV can become native source records and answer
categories when the workbook refers to it with `select_one_from_file` or
`select_multiple_from_file`.

## Chunk a document

```python
from survey_scribe.sources.chunking import chunk_document

chunked = chunk_document(
    document,
    max_tokens=4_000,
    overlap_tokens=200,
)

chunk_ids = tuple(chunk.id for chunk in chunked.chunks)
repeated_rows = chunked.repeated_rows
```

The default conservative estimator budgets one token per UTF-8 byte. You can
inject an object with `estimate(text: str) -> int` for model-specific estimation.

Chunking guarantees source order and a hard final `max_tokens` limit. It splits
large text deterministically and rejects a table that cannot fit without losing
cell structure. Overlap contains only complete prior text blocks and is included
in the hard final budget.

## PDF and OCR setup

Install the PDF extra:

```console
python -m pip install "survey-scribe[pdf]"
```

PDF conversion requires a configured local Docling artifact directory. When OCR
runs, the directory also needs the approved EasyOCR archives. Configure and
validate it before constructing the default registry. The PDF adapter reads
`DOCLING_ARTIFACTS_PATH`; the standalone validator also accepts
`SURVEY_SCRIBE_OCR_CACHE`:

=== "Linux and macOS"

    ```bash
    export DOCLING_ARTIFACTS_PATH="/approved/cache/easyocr"
    ```

=== "PowerShell"

    ```powershell
    $Env:DOCLING_ARTIFACTS_PATH = "C:\approved\cache\easyocr"
    ```

Validate the local cache without downloading any files:

```python
from pathlib import Path

from survey_scribe.sources.ocr import validate_ocr_cache

checks = validate_ocr_cache(Path("/approved/cache/easyocr"))
invalid = tuple(check for check in checks if check.status != "valid")
if invalid:
    raise RuntimeError("OCR cache validation failed")
```

When OCR runs, the PDF adapter validates the approved archives and the exact
extracted model files before conversion. It rejects a missing, unsafe, or
changed cache and configures EasyOCR for English-only offline use with downloads
disabled.

The PDF worker sets offline flags and blocks common Python socket calls during
conversion. This is application-level protection, not an operating-system
sandbox. Use process isolation and network policy for hostile documents.

OCR is configured for English by default. A validated cache proves artifact
identity and offline availability; it does not prove recognition quality for a
new document, language, scan condition, or layout.

### PDF conversion options

By default the adapter reads the text layer of each page and runs OCR only on a
page that needs it. It does not read a blank page. Section headings stay flat
and the adapter keeps body text only. `PdfConversionOptions` changes one choice
at a time for a caller that knows its documents. An unset option keeps the
default.

```python
from survey_scribe.sources.docling import PdfConversionOptions
from survey_scribe.sources.registry import SourceRegistry

registry = SourceRegistry.default(
    pdf_options=PdfConversionOptions(
        ocr="never",            # the text layer alone: any script verbatim, no OCR cache needed
        heading_levels=True,    # section_path carries Part I > 1. > 1.1 instead of the last heading
        include_furniture=True, # a section title printed at the top of a page is kept
    )
)
```

| option | default | meaning |
|---|---|---|
| `ocr` | `"auto"` | `"auto"` reads the text layer and runs OCR only on a page that needs it (see below); `"always"` OCRs every page that is not blank and ignores the text layer; `"never"` reads the text layer alone (born-digital PDFs in any script, no EasyOCR artifacts required) |
| `ocr_languages` | `("en",)` | OCR currently supports English only; other recognition languages need approved language-specific model artifacts and are rejected when OCR is enabled. `ocr="never"` can read a text layer in any script. |
| `heading_levels` | `False` | infer heading depth from bookmarks, numbering and font style (Docling's heading-hierarchy stage); `section_path` then lists the ancestors |
| `max_heading_level` | `6` | the deepest inferred level |
| `include_furniture` | `False` | keep page headers and footers; the layout model files a page-top section title as a page header |
| `table_mode` | `"accurate"` | TableFormer `"accurate"` or `"fast"` |

The same options are read from the environment by `SourceRegistry.default()`
when no `pdf_options` are passed: `SURVEY_SCRIBE_PDF_OCR`,
`SURVEY_SCRIBE_PDF_OCR_LANGUAGES` (comma-separated),
`SURVEY_SCRIBE_PDF_HEADING_LEVELS`, `SURVEY_SCRIBE_PDF_MAX_HEADING_LEVEL`,
`SURVEY_SCRIBE_PDF_INCLUDE_FURNITURE`, `SURVEY_SCRIBE_PDF_TABLE_MODE`.

#### The page check

The adapter checks each page before conversion, in every mode. The check gives
each page one status. The first rule that matches gives the status:

1. The page does not load: `unreadable`.
2. The page has almost no ink and fewer than 32 visible characters in its text
   layer: `blank`. The check renders the page in grayscale at 72 dpi and counts
   the pixels darker than gray level 230. A page has almost no ink when fewer
   than 0.012% of its pixels are dark. That is about 58 pixels on a letter page.
3. One image covers half of the page or more: `needs_ocr`. This finds a scanned
   page with a text stamp, such as a page number.
4. The text layer holds fewer than 32 visible characters: `needs_ocr`.
5. Any other page: `machine_readable`.

The test for blank comes first. A scan of a white sheet is one image over the
whole page, but it has no ink, so it is blank. A page with a text layer of 32
or more visible characters is never blank. Its text can be too light or
invisible for the render. The check measures an image in a form XObject at its
size on the page.

The gray level sits close to white, so most light text and most faded scans
have ink. But text at gray level 230 or lighter, such as text in the PDF gray
0.9, has no ink. A page with only such text and fewer than 32 visible
characters is blank, and its text is lost. A white scan with specks or heavy
noise, or a gray sheet near gray 236, can have ink. Such a page gets an OCR
read that finds no text. The limit for blank comes from made-up test pages,
not from real questionnaires:

- Scans of a white sheet with light noise measured 0 to 0.0014% dark pixels.
- A page with only a one-digit page number measured up to 0.0087%. Such a page
  is blank. The limit is 1.38 times this value.
- The lightest line of text measured 0.0155% (19 characters in yellow). That
  is 1.29 times the limit. A scan of one line of text at gray 225 measured
  0.0365% or more. That is 3 times the limit.
- Ink cannot tell a page number from a short word. A page with only a page
  number of two or three digits, or with only one short word, measured 0.0047%
  to 0.026%. Such a page can fall on either side of the limit. A blank page
  loses that word.

#### One read for each page

Each page gets one read, from its status and the `ocr` mode:

| status | `"auto"` | `"always"` | `"never"` |
|---|---|---|---|
| `machine_readable` | text layer | full-page OCR | text layer |
| `needs_ocr` | OCR, text layer kept | full-page OCR | text layer |
| `blank` | no read | no read | no read |
| `unreadable` | no read | no read | no read |

The adapter reads the text-layer pages in one Docling call with no OCR. It
reads each OCR page alone. In `"auto"` mode, OCR runs in the Docling default
mode. The text layer of the page stays, and OCR reads the areas that the text
layer does not cover, such as an image. On a scan with no text layer, OCR reads
each region that the layout model finds on the page. Only `"always"` runs
full-page OCR, which replaces the text layer. On scans of questionnaire pages,
full-page OCR kept fewer question numbers than the default mode. On one
scanned page with 10 question numbers, full-page OCR kept 5 and the default
mode kept 8.

A `machine_readable` page gets no OCR. Text inside an image that covers less
than half of such a page, such as a heading in a picture, is not read.

The adapter then puts the blocks in page order. The blocks of an OCR page go
before the first text-layer block of a later page. The text-layer blocks keep
the order of the Docling read. If that read puts a block after a block of a
later page, the block stays there. A section heading on an OCR page is the
section of the blocks on the later pages too. Docling can join text across a
page break. If such a block crosses a page that the text-layer read does not
keep, the adapter cuts the block at each page break. Each part goes to its own
page. The adapter drops a part on an OCR page or a blank page. Docling gives no
usable cut for a table or for a word that a hyphen splits. Such a block stays
whole at its first text-layer page.

A blank page is missing from the blocks. `SourceDocument.coverage.blank_units`
lists it. A blank page is not a failure: it has no diagnostic and no failed
block. An unreadable page is in `failed_units` and gets a
`PDF_PAGE_CONVERSION_FAILED` error. A page that Docling fails to read gets the
same error. Only that page fails, and the other pages keep their blocks. If a
Docling read fails and its errors do not name every page of the read, the
conversion stops with an error.

These warnings go in `SourceDocument.diagnostics`:

- `PDF_PAGE_OCR`: OCR read the page. The message gives the reason.
- `PDF_PAGE_TEXT_INCOMPLETE`: the page needs OCR, but the mode is `"never"`.
  The text of the page can be incomplete.

#### The OCR files

The artifacts directory always holds Docling's layout and table models
(`docling-tools models download layout tableformer -o <dir>`). The adapter
needs the approved EasyOCR archives described above only when a page gets an
OCR read. A PDF with no page for OCR needs no EasyOCR archives. If the archives
are missing and a page needs OCR, the error names the pages.

## XLSX safety

The XLSX adapter opens workbooks in read-only mode and rejects formulas, macros,
external links, malformed cell references, archive expansion violations, and
excessive worksheet dimensions. It does not calculate workbook formulas.

The XLSForm support matrix is version `1.0`. Groups become containment; repeats
remain logical templates; reference comparisons, `selected()`, and Boolean
`and`/`or`/`not` project exactly. Other functions and arithmetic remain typed
native expressions with an `opaque` canonical projection. Constraints,
calculations, and choice filters are preserved but are not treated as flow edges.

## Error handling

```python
from pathlib import Path

from survey_scribe.sources import SourceError, SourceRegistry

try:
    document = SourceRegistry.default().convert(Path("questionnaire.pdf"))
except SourceError as error:
    code = error.diagnostic.code
    safe_message = error.diagnostic.message
```

Use `SourceLimitError.limit` to identify the exceeded ceiling. Source exceptions
provide stable diagnostic codes for application-level handling.
