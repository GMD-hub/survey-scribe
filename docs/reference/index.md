# API Overview

Survey Scribe preserves its stable legacy SVIS API and adds routed models,
`SurveyScribe`, custom structured pipelines, `QuestionnaireRouter`, and typed
modules for providers, configuration, results, serialization, and local sources.

Use [Questionnaire Extraction](../guides/extraction.md) for a method-by-method
workflow and [Completed Questionnaires](../guides/completed-questionnaires.md)
for caller-defined answer records.

## Top-level public imports

The following groups cover every name in `survey_scribe.__all__`.

### Extraction, results, and SVIS

```python
from survey_scribe import (
    AnswerCategory,
    ChunkedStructuredPipeline,
    DataType,
    Diagnostic,
    DiagnosticCode,
    ExtractionResult,
    FailedBlock,
    LocalSource,
    NumericRange,
    ResultStatus,
    SourceBundle,
    StructuredPipeline,
    StudyType,
    SurveySVIS,
    SurveyScribe,
    SurveyScribeConfig,
    SurveyVariable,
    UnitLevel,
)
```

### Routing models and facade

```python
from survey_scribe import (
    CandidateEdge,
    CandidateStatus,
    Containment,
    DiagnosticSeverity,
    DiscrepancyKind,
    EdgeKind,
    EvidenceRecord,
    InventoryItem,
    LoopDefinition,
    LoopKind,
    QuestionnaireRouter,
    QuestionnaireRoutingGraph,
    RepeatKind,
    RepeatSpec,
    ReplacementEdge,
    ReviewAction,
    ReviewDecision,
    RoutedAnswerCategory,
    RoutedNumericRange,
    RoutedSurveySVIS,
    RoutedSurveyVariable,
    RoutingAudit,
    RoutingConfig,
    RoutingDiagnostic,
    RoutingDiscrepancy,
    RoutingEdge,
    RoutingNode,
    RoutingSourceBinding,
    TerminalKind,
    canonical_routing_schema_json,
)
```

The top-level `DiagnosticSeverity` is the routing enum. Import operational result
severity as `survey_scribe.results.DiagnosticSeverity`.

### Errors

```python
from survey_scribe import (
    AmbiguousCredentialError,
    ArtifactCollisionError,
    ArtifactWriteError,
    ClientClosedError,
    ConfigurationError,
    ConversionFailedError,
    ProgrammerInputError,
    RunningEventLoopError,
    SourceConversionError,
    SourceDependencyError,
    SourceError,
    SourceFormatError,
    SourceInputError,
    SourceLimitError,
    SourceSecurityError,
    SourceTimeoutError,
    SurveyScribeError,
)
```

### Version

```python
from survey_scribe import (
    __version__,
)
```

The seven legacy SVIS model exports and their serialized behavior remain exact
through 1.x. Runtime, result, source, error, and routed model names are also
available at the top level. Import lower-level contracts from their documented
modules when a name is not re-exported:

```python
from survey_scribe.providers import ModelCapabilities, StructuredProvider
from survey_scribe.results import DiagnosticSeverity as ResultDiagnosticSeverity
from survey_scribe.serialization import legacy_json_bytes, legacy_payload
from survey_scribe.sources import SourceLimits, SourceRegistry
from survey_scribe.sources.chunking import chunk_document
```

## Reference sections

| Section | Content |
| --- | --- |
| [Client and Pipelines](client.md) | `SurveyScribe` and custom structured extraction |
| [SVIS Models](models.md) | Survey, variable, category, range, and enum models |
| [Configuration](configuration.md) | Validated settings and resolution methods |
| [Results](results.md) | Result status, diagnostics, and artifact references |
| [Sources](sources.md) | Local source models, adapters, chunking, and OCR checks |
| [Serialization](serialization.md) | Legacy-compatible JSON conversion |
| [Routing](routing.md) | Routed models, graph contracts, and router API |
| [Providers](providers.md) | `StructuredProvider` and capability contracts |
| [Exceptions](exceptions.md) | Package exceptions and redaction helpers |
| [Command Line](cli.md) | Conversion, configuration, providers, and schema export |
| [JSON Schemas](schemas.md) | Generated SVIS, routing, and non-secret configuration schemas |

Generated signatures show parameter annotations and return annotations from the
source. The guide pages explain validation rules, defaults, side effects, and
security boundaries that are not fully expressed by signatures.

## Removed source-tree import

The old repository-only `schemas.svis` module is not part of the package. Import
all public models from `survey_scribe`.

## Package boundary

`SurveyScribe` converts supported local sources to `SurveySVIS`. Native XLSForm
conversion can complete without a provider. Other formats use the configured
`StructuredProvider`. `QuestionnaireRouter` is a separate additive operation that
adds source-grounded routing to an existing `SurveySVIS`.
