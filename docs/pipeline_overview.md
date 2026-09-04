# Pipeline Overview

Survey Scribe converts a supported local questionnaire to `SurveySVIS` through
the public `survey_scribe.SurveyScribe` facade.

## Processing Stages

1. `survey_scribe.sources.SourceRegistry` validates a local path, applies format
   and resource controls, snapshots the input, and selects its source adapter.
2. A native adapter can return authoritative SVIS directly. XLSForm uses this
   path while preserving names, choices, groups, repeats, and expressions.
3. Other sources become ordered `SourceDocument` blocks with page, sheet, or row
   provenance.
4. `survey_scribe.pipeline.ExtractionPipeline` sends bounded structured requests
   through the configured `StructuredProvider` and shared concurrency limiter.
5. Deterministic reconciliation applies quality diagnostics and preserves failed
   blocks without fabricating source content.
6. `ExtractionResult` derives `success`, `partial`, or `failed` and keeps
   diagnostics, failed blocks, and artifact references immutable.
7. `ExtractionResult.write()` publishes a validated immutable generation,
   sidecar, manifest, active pointer, and legacy SVIS projection.

## Entry Points

Use the installed command for local conversion:

```console
survey-scribe convert questionnaire.pdf --output-dir output
survey-scribe batch questionnaire-a.pdf questionnaire-b.xlsx --output-dir output
```

Use `SurveyScribe.convert()` / `aconvert()` for one source and
`convert_many()` / `aconvert_many()` for ordered batches. See the
[CLI guide](cli.md), [API overview](reference/index.md), and
[results guide](guides/results.md).

The deprecated `docling_pipeline.py` root shim remains only for 1.x migration.
New code must not import removed `agents/`, `extractors/`, or `schemas/` modules.
