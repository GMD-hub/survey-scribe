# Questionnaire Extraction

Survey Scribe converts a local questionnaire instrument into typed survey
metadata. The standard output is `SurveySVIS`. It describes questions,
variables, answer options, ranges, modules, raw skip text, and extraction
metadata.

!!! important "Instrument metadata, not response microdata"

    `SurveyScribe` does not extract respondent rows or observed answer values.
    Use a [caller-defined structured pipeline](completed-questionnaires.md) when
    you must extract answer records from filled questionnaire files.

## Choose an extraction path

| Input and goal | API | Provider call |
| --- | --- | --- |
| XLSForm instrument to `SurveySVIS` | `SourceRegistry.convert_for_svis()` | No |
| PDF, DOCX, CSV, HTML, Markdown, or text instrument to `SurveySVIS` | `SurveyScribe.convert()` | Yes |
| One source in async code | `SurveyScribe.aconvert()` | Depends on source |
| Ordered batch | `convert_many()` or `aconvert_many()` | Depends on each source |
| Source blocks only | `SourceRegistry.convert()` | No |
| Caller-defined completed-answer record | `StructuredPipeline` | Yes |
| Long caller-defined output | `ChunkedStructuredPipeline` | Yes |

An ordinary `.xlsx` file without an XLSForm `survey` sheet follows the
provider-backed document path. It does not get native questionnaire semantics.

## Provider-free XLSForm quick start

Install the `tabular` extra, then parse the instrument directly:

```python
from datetime import date
from pathlib import Path

from survey_scribe import ExtractionResult
from survey_scribe.results import ArtifactProvenance
from survey_scribe.sources import SourceRegistry

source = Path("questionnaire.xlsx")
conversion = SourceRegistry.default().convert_for_svis(
    source,
    extraction_date=date.today(),
)

if conversion.svis is None:
    raise RuntimeError("The workbook is not a supported XLSForm")

review_codes = tuple(item.code for item in conversion.document.diagnostics)
if conversion.native is not None:
    review_codes += tuple(item.code for item in conversion.native.diagnostics)
if review_codes:
    raise RuntimeError(f"Review XLSForm diagnostics before publication: {review_codes}")
if conversion.document.snapshot_sha256 is None:
    raise RuntimeError("The source snapshot has no digest")

survey = conversion.svis
result = ExtractionResult(
    output=survey,
    artifact_provenance=ArtifactProvenance(
        source_sha256=(conversion.document.snapshot_sha256,),
        model_response_sha256=(),
        prompt_versions=(),
    ),
)
written = result.write(Path("output"))

assert survey.source_format == "xlsform"
assert written.output is not None
```

The SVIS preserves XLSForm names, choices, module labels, raw relevance, and
retained constraint, calculation, choice-filter, and repeat-count notes. Full
group, repeat, expression, and routing structure remains in `conversion.native`.
The stable SVIS artifact does not contain that full native structure. Survey
Scribe executes none of the expressions.

Use `SourceBundle` when an XLSForm uses an external choice CSV:

```python
from survey_scribe.sources import SourceBundle

bundle = SourceBundle(
    root=Path("survey-files"),
    primary=Path("questionnaire.xlsx"),
    companions=(Path("places.csv"),),
)
conversion = SourceRegistry.default().convert_for_svis(
    bundle,
    extraction_date=date.today(),
)
```

The workbook must refer to the companion with `select_one_from_file` or
`select_multiple_from_file`. Survey Scribe confines companion paths to the
bundle root.

## Provider-backed conversion

Use the facade for sources that need model-assisted structured extraction:

The PDF example needs both the selected provider extra and the `pdf` extra, plus
a validated local OCR artifact directory. Use DOCX or text to test provider
configuration without OCR.

```python
from pathlib import Path

from survey_scribe import ResultStatus, SurveyScribe

with SurveyScribe.from_config(resolve_environment=True) as client:
    result = client.convert(Path("questionnaire.pdf"))

if result.status is ResultStatus.failed:
    codes = tuple(item.code for item in result.diagnostics)
    raise RuntimeError(f"Extraction failed with codes: {codes}")
if result.status is ResultStatus.partial:
    codes = tuple(item.code for item in result.diagnostics)
    raise RuntimeError(f"Send partial extraction to review: {codes}")

assert result.output is not None
written = result.write(Path("output"))
```

`from_config()` checks only `./survey-scribe.toml` unless you supply a path.
SDK environment access is disabled unless `resolve_environment=True`.

The facade must still have a configured or injected provider when the source is
an XLSForm. Native XLSForm can make zero outbound calls, but provider-free
construction of `SurveyScribe()` is not supported. Use
`SourceRegistry.convert_for_svis()` for a fully provider-free path.

## Async and batch use

Use async methods inside an event loop:

```python
from survey_scribe import ExtractionResult, SurveySVIS, SurveyScribe


async def convert_batch() -> list[ExtractionResult[SurveySVIS]]:
    sources = (
        "questionnaire-a.pdf",
        "questionnaire-b.docx",
        "questionnaire-c.xlsx",
    )
    async with SurveyScribe.from_config(resolve_environment=True) as client:
        return await client.aconvert_many(sources)
```

Batch results remain in input order. One concurrency limiter covers source
conversion and all provider attempts for the batch. Separate concurrent calls
to `aconvert()` have separate limiters.

Do not call `convert()` or `convert_many()` from a running event loop. The
synchronous facade rejects that use instead of starting a nested loop.

## Public extraction API

| Method | Input | Output | Main behavior |
| --- | --- | --- | --- |
| `SurveyScribe.convert(source)` | Local path or `SourceBundle` | `ExtractionResult[SurveySVIS]` | Synchronous single-source conversion |
| `SurveyScribe.aconvert(source)` | Local path or `SourceBundle` | `ExtractionResult[SurveySVIS]` | Async single-source conversion |
| `SurveyScribe.convert_many(sources)` | Iterable of local sources | `list[ExtractionResult[SurveySVIS]]` | Ordered concurrent batch |
| `SurveyScribe.aconvert_many(sources)` | Iterable of local sources | `list[ExtractionResult[SurveySVIS]]` | Ordered async batch |
| `SourceRegistry.convert(source)` | Local path or `SourceBundle` | `SourceDocument` | Normalization only |
| `SourceRegistry.convert_for_svis(source, extraction_date=...)` | Local path or bundle | `SourceSvisConversionResult` | Native XLSForm SVIS when available |
| `SourceRegistry.convert_with_native(source, svis)` | Matching source and SVIS | `SourceConversionResult` | Normalization plus exact routing binding |
| `ExtractionResult.write(output_dir, ...)` | Usable result | New `ExtractionResult` | Versioned files, manifest, sidecar, and active pointer |

See [Extraction Client and Pipelines](../reference/client.md),
[Sources API](../reference/sources.md), and
[Results API](../reference/results.md) for generated signatures.

## Processing stages

The standard extraction path has seven stages:

1. Validate and snapshot the local source.
2. Use authoritative native XLSForm output when it is available.
3. Normalize other sources into ordered blocks with physical provenance.
4. Send bounded structured requests through `StructuredProvider`.
5. Reconcile chunk output without fabricating missing source content.
6. Derive `success`, `partial`, or `failed` from operational evidence.
7. Publish a validated generation, sidecar, manifest, active pointer, and stable SVIS projection.

Metadata and variable extraction use separate request phases. A document can
therefore use about two provider calls per chunk, plus bounded retries.

## Result handling

| Status | Meaning | Required action |
| --- | --- | --- |
| `success` | Usable output and no operational failure | Apply your quality and review policy |
| `partial` | Usable output with failed blocks or operational error evidence | Inspect diagnostics and failed blocks before publication |
| `failed` | No usable output | Do not call `write()` |

A low-confidence warning alone remains `success`. Confidence is a review signal,
not an operational failure.

`SurveyScribe` returns safe result envelopes for expected source and provider
failures. Programmer input errors, use-after-close, and sync calls in an event
loop raise typed exceptions before conversion.

## Provenance and privacy

`SourceDocument` keeps block-level page, sheet, section, and row provenance.
Plain `SurveySVIS` keeps source file, source format, and an optional source page,
but it does not contain artifact digests or retain each provider source-block
citation. Digests are stored in `ExtractionResult.artifact_provenance`, artifact
references, and manifests according to the selected extraction path.

Routed output has stronger evidence records and can contain exact bounded source
quotes. Treat the primary SVIS and routed SVIS as sensitive data products. The
package sidecars and manifests use fixed safe records and digests and do not
persist raw provider responses.

## Source limits and failures

Default limits include 250 MiB per source, 2,000 PDF pages, 2,000,000 worksheet
cells, and a 30-minute conversion deadline. Set smaller limits for shared or
interactive runtimes. See [Questionnaire Sources](sources.md) for all limits,
archive controls, OCR requirements, and format-specific checks.

Survey Scribe accepts local paths only. It rejects URLs, file objects, bytes,
network paths, missing files, and bundle paths that escape their root.

## Next steps

1. Use [Completed Questionnaires](completed-questionnaires.md) for caller-defined answer records.
2. Use [Skip Patterns](skip-patterns.md) to interpret activation and routing output.
3. Use [AI Providers](ai-providers.md) to choose and configure an adapter.
4. Use [Results and Artifacts](results.md) to publish or recover output.
