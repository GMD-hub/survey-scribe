# API Overview

Survey Scribe preserves its stable legacy SVIS API and adds routed models,
`QuestionnaireRouter`, and typed modules for providers, configuration, results,
serialization, and local sources.

## Stable top-level imports

```python
from survey_scribe import (
    AnswerCategory,
    DataType,
    NumericRange,
    QuestionnaireRouter,
    QuestionnaireRoutingGraph,
    RoutedSurveySVIS,
    RoutingConfig,
    StudyType,
    SurveySVIS,
    SurveyVariable,
    UnitLevel,
    __version__,
)
```

The seven legacy SVIS model exports and their serialized behavior remain exact
through 1.x. Routed exports are additive. Import lower-level contracts from their
documented modules:

```python
from survey_scribe.config import SurveyScribeConfig
from survey_scribe.errors import ConfigurationError
from survey_scribe.results import ExtractionResult
from survey_scribe.serialization import legacy_json_bytes, legacy_payload
from survey_scribe.sources import SourceLimits, SourceRegistry
from survey_scribe.sources.chunking import chunk_document
```

## Reference sections

| Section | Content |
| --- | --- |
| [SVIS Models](models.md) | Survey, variable, category, range, and enum models |
| [Configuration](configuration.md) | Validated settings and resolution methods |
| [Results](results.md) | Result status, diagnostics, and artifact references |
| [Sources](sources.md) | Local source models, adapters, chunking, and OCR checks |
| [Serialization](serialization.md) | Legacy-compatible JSON conversion |
| [Routing](routing.md) | Routed models, graph contracts, and router API |
| [Providers](providers.md) | `StructuredProvider` and capability contracts |
| [Exceptions](exceptions.md) | Package exceptions and redaction helpers |
| [Command Line](cli.md) | Help, version, and routing-schema export |

Generated signatures show parameter annotations and return annotations from the
source. The guide pages explain validation rules, defaults, side effects, and
security boundaries that are not fully expressed by signatures.

## Deprecated compatibility import

`from schemas.svis import SurveySVIS` remains available as a deprecated
compatibility path. New code must import from `survey_scribe`.

## Package boundary

No packaged function currently extracts a new `SurveySVIS` from a source file.
`QuestionnaireRouter` adds routing to an existing `SurveySVIS` and requires the
exact validated source binding. This distinction preserves the legacy contract.
