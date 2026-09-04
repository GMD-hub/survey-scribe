# Survey Scribe

<div class="hero" markdown>

**Typed questionnaire metadata with explicit provenance.**

Survey Scribe provides the Survey Variable Information Schema (SVIS), safe local
document normalization, deterministic chunking, secure configuration resolution,
versioned artifact output, and source-grounded questionnaire routing for
household-survey workflows.

[Install Survey Scribe](getting-started/installation.md){ .md-button .md-button--primary }
[Open the quickstart](getting-started/quickstart.md){ .md-button }
[Explore synthetic results](playground.md){ .md-button }

</div>

## What the package provides

<div class="feature-grid" markdown>

<div class="feature-card" markdown>

### Typed SVIS records

Build and validate survey, variable, category, range, confidence, and review
metadata with Pydantic 2.

</div>

<div class="feature-card" markdown>

### Local source normalization

Convert local PDF, DOCX, XLSX, CSV, HTML, Markdown, and text files into one
ordered, provenance-aware document model.

</div>

<div class="feature-card" markdown>

### Controlled configuration

Resolve non-secret TOML settings and opt-in environment credentials with clear,
deterministic precedence.

</div>

<div class="feature-card" markdown>

### Questionnaire routing

Represent accepted flow as a directed multigraph with separate source evidence,
disputed candidates, activation conditions, repeat templates, and review history.

</div>

<div class="feature-card" markdown>

### Verifiable artifacts

Write immutable generations with main output, sidecar diagnostics, manifests,
checksums, and an active pointer.

</div>

</div>

## Package scope

Survey Scribe `0.1.x` is an alpha package. It includes:

- Stable legacy SVIS imports plus additive routed models and `QuestionnaireRouter`.
- Typed configuration, result, source, routing, provider-contract, chunking, and serialization modules.
- A PEP 561 `py.typed` marker for editors and type checkers.
- A `survey-scribe` command for conversion, batch runs, provider/configuration
  inspection, and routing-schema export.

!!! important "Local-first boundary"

    The installed package converts local files only. It does not accept remote
    URLs, store managed credentials, or expose a hosted inference service.
    Native XLSForm conversion can require zero provider calls. Other extraction
    sends normalized source content only to the provider endpoint that the user
    explicitly configures. The package contains no telemetry client.

## Minimal example

```python
from datetime import date

from survey_scribe import DataType, SurveySVIS, SurveyVariable

survey = SurveySVIS(
    survey_id="TST_2024_SYNTH",
    country_code="TST",
    year=2024,
    survey_name="Synthetic Household Survey",
    variables=[
        SurveyVariable(
            raw_name="q_age",
            label="Age in completed years",
            data_type=DataType.numeric,
            extraction_confidence=0.98,
        )
    ],
    source_file="questionnaire.pdf",
    source_format="pdf",
    extraction_date=date.today(),
)

payload = survey.model_dump_json(indent=2)
restored = SurveySVIS.model_validate_json(payload)
assert restored == survey
```

## Next steps

1. [Install the package and optional source dependencies](getting-started/installation.md).
2. [Build and validate your first SVIS record](getting-started/quickstart.md).
3. [Configure API keys without persisting them](guides/security.md).
4. [Normalize local source documents](guides/sources.md).
5. [Use the complete typed API reference](reference/index.md).
6. [Interpret and validate routed output](routing.md).
7. [Inspect precomputed result states without uploading data](playground.md).
