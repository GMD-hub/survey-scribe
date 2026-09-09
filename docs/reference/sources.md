# Sources API

Source content remains untrusted data throughout normalization. The default
registry accepts local files only and uses typed exceptions for format, security,
resource, dependency, conversion, and timeout failures.

See [Local Sources](../guides/sources.md) for supported formats, default limits,
optional dependencies, and operational controls.

## Registry methods

| Method | Return | Behavior |
| --- | --- | --- |
| `convert(source, limits=...)` | `SourceDocument` | Validate, snapshot, hash, and normalize one local source |
| `convert_for_svis(source, extraction_date=..., limits=...)` | `SourceSvisConversionResult` | Add native XLSForm SVIS and routing semantics when available |
| `convert_with_native(source, svis, limits=...)` | `SourceConversionResult` | Add an exact routing binding and optional native semantics |

All methods accept a local path or confined `SourceBundle`. They raise typed
`SourceError` subclasses for input, format, security, dependency, conversion,
timeout, and resource-limit failures. They do not accept bytes, streams, URLs, or
network paths.

## Core source types

::: survey_scribe.sources.base
    options:
      members:
        - LocalSource
        - DEFAULT_SOURCE_LIMITS
        - SourceLimits
        - SourceBundle
        - ResolvedSource
        - SourceCoverage
        - SourceProvenance
        - SourceTable
        - SourceBlock
        - SourceDocument
        - SourceDiagnostic
        - SourceError
        - SourceInputError
        - SourceFormatError
        - SourceSecurityError
        - SourceDependencyError
        - SourceConversionError
        - SourceTimeoutError
        - SourceLimitError
        - SourceAdapter
        - resolve_local_source
        - snapshot_resolved_source
        - validate_source_argument

## Registry

::: survey_scribe.sources.registry
    options:
      members:
        - SourceRegistry
        - SourceConversionResult
        - SourceSvisConversionResult

## Document adapters

::: survey_scribe.sources.docling
    options:
      members:
        - DoclingPdfAdapter
        - DocxAdapter
        - HtmlAdapter
        - MarkdownAdapter
        - TextAdapter

## Tabular adapters

::: survey_scribe.sources.tabular
    options:
      members:
        - CsvAdapter
        - XlsxAdapter

## XLSForm adapter

The default registry uses `XlsFormAdapter` for `.xlsx`. It keeps ordinary XLSX
normalization and adds native SVIS, choices, relevance, group, repeat, and source
binding data when the workbook has an XLSForm `survey` sheet.

::: survey_scribe.sources.xlsform
    options:
      members:
        - XLSFORM_SUPPORT_MATRIX
        - XLSFORM_SUPPORT_MATRIX_VERSION
        - XlsFormAdapter

## Chunking

::: survey_scribe.sources.chunking
    options:
      members:
        - TokenEstimator
        - ConservativeTokenEstimator
        - RepeatedRowOrigin
        - RepeatedRow
        - SourceChunk
        - ChunkedDocument
        - chunk_document

## OCR cache validation

::: survey_scribe.sources.ocr
    options:
      members:
        - OcrArtifact
        - OcrArtifactValidation
        - validate_ocr_cache
        - main
