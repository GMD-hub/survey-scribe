# Local Sources

The source API converts untrusted local files into deterministic
`SourceDocument` records. It preserves block order, complete tables, and physical
provenance without calling a model provider.

## Supported formats

| Suffix | Adapter | Extra |
| --- | --- | --- |
| `.pdf` | Docling PDF conversion with local OCR artifacts | `pdf` |
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

The resolver rejects paths that escape the root. Current adapters validate the
companion paths but do not merge companion content into the normalized document.

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

PDF conversion requires a configured local Docling/EasyOCR artifact directory.
Configure and validate it before constructing the default registry. The PDF
adapter reads `DOCLING_ARTIFACTS_PATH`; the standalone validator also accepts
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

The PDF adapter validates the approved archives and the exact extracted model
files before conversion. It rejects a missing, unsafe, or changed cache and
configures EasyOCR for English-only offline use with downloads disabled.

The PDF worker sets offline flags and blocks common Python socket calls during
conversion. This is application-level protection, not an operating-system
sandbox. Use process isolation and network policy for hostile documents.

OCR is currently configured for English. A validated cache proves artifact
identity and offline availability; it does not prove recognition quality for a
new document, language, scan condition, or layout.

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
