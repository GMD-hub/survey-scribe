# API Overview

Survey Scribe exposes a small stable top-level SVIS API and additional typed
modules for configuration, results, serialization, and local sources.

## Stable top-level imports

```python
from survey_scribe import (
    AnswerCategory,
    DataType,
    NumericRange,
    StudyType,
    SurveySVIS,
    SurveyVariable,
    UnitLevel,
    __version__,
)
```

The package freezes this exact top-level export set for `0.1.x`. Import secondary
APIs from their documented modules:

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
| [Exceptions](exceptions.md) | Package exceptions and redaction helpers |
| [Command Line](cli.md) | Bootstrap CLI behavior |

Generated signatures show parameter annotations and return annotations from the
source. The guide pages explain validation rules, defaults, side effects, and
security boundaries that are not fully expressed by signatures.

## Deprecated compatibility import

`from schemas.svis import SurveySVIS` remains available as a deprecated
compatibility path. New code must import from `survey_scribe`.

## Package boundary

No packaged function currently accepts a source file and returns extracted
`SurveySVIS` through an LLM provider. Do not infer such an API from the provider
extras or configuration types.
