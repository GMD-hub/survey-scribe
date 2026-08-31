# Sources API

Source content remains untrusted data throughout normalization. The default
registry accepts local files only and uses typed exceptions for format, security,
resource, dependency, conversion, and timeout failures.

See [Local Sources](../guides/sources.md) for supported formats, default limits,
optional dependencies, and operational controls.

## Core source types

::: survey_scribe.sources.base
    options:
      members:
        - LocalSource
        - DEFAULT_SOURCE_LIMITS
        - SourceLimits
        - SourceBundle
        - ResolvedSource
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

## Registry

::: survey_scribe.sources.registry
    options:
      members:
        - SourceRegistry

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
