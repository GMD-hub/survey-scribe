# Survey Scribe

<div class="hero" markdown>

**Extract questionnaire metadata with explicit provenance and bounded AI use.**

Survey Scribe converts local questionnaire instruments into typed Survey Variable
Information Schema (SVIS) artifacts. It provides native XLSForm extraction,
model-assisted document extraction, caller-defined completed-form pipelines,
source-grounded skip-pattern graphs, and versioned output.

[Extract a questionnaire](getting-started/quickstart.md){ .md-button .md-button--primary }
[Deploy in Palantir Foundry](platforms/palantir-foundry.md){ .md-button }
[Configure AI providers](guides/ai-providers.md){ .md-button }
[Browse DeepWiki](https://deepwiki.com/GMD-hub/survey-scribe){ .md-button }

</div>

## What the package provides

<div class="feature-grid" markdown>

<div class="feature-card" markdown>

### Questionnaire extraction

Extract native XLSForm instruments without a provider, or use a strict structured
provider for PDF, DOCX, CSV, HTML, Markdown, and text.

</div>

<div class="feature-card" markdown>

### Completed-form contracts

Use caller-defined Pydantic models for completed questionnaires. Answer-state,
repeat assembly, and routing validation remain application responsibilities.

</div>

<div class="feature-card" markdown>

### Skip patterns and routing

Represent activation, branches, section jumps, terminals, repeats, evidence,
candidates, and review history without pretending to execute an interview.

</div>

<div class="feature-card" markdown>

### Platform integration

Run a provider-free XLSForm transform in Palantir Foundry, use compatible
Microsoft Foundry endpoints, or configure the generic mAI Factory gateway pattern.

</div>

<div class="feature-card" markdown>

### Controlled providers

Configure OpenAI, OpenRouter, Vercel AI Gateway, Azure-compatible endpoints,
Anthropic, or an application-owned `StructuredProvider` with bounded retries.

</div>

<div class="feature-card" markdown>

### Verifiable artifacts

Write immutable generations with main output, sidecar diagnostics, manifests,
checksums, and an active pointer.

</div>

</div>

## Package scope

Survey Scribe `0.1.x` is an alpha package. No approved PyPI release is currently
available. The source package includes:

- Native instrument metadata extraction and provider-assisted extraction.
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

!!! important "Completed-questionnaire boundary"

    The standard client extracts instrument metadata, not respondent microdata.
    Custom structured pipelines can validate caller-defined answer records, but
    Survey Scribe does not classify skipped answers, execute routing conditions,
    or expand repeat instances.

## Minimal example

```python
from datetime import date

from survey_scribe.sources import SourceRegistry

conversion = SourceRegistry.default().convert_for_svis(
    "questionnaire.xlsx",
    extraction_date=date.today(),
)
if conversion.svis is None:
    raise RuntimeError("The workbook is not a supported XLSForm")

review_codes = tuple(item.code for item in conversion.document.diagnostics)
if conversion.native is not None:
    review_codes += tuple(item.code for item in conversion.native.diagnostics)
if review_codes:
    raise RuntimeError(f"Review XLSForm diagnostics before use: {review_codes}")

survey = conversion.svis
```

## Next steps

1. [Install an approved wheel or pinned source revision](getting-started/installation.md).
2. [Extract your first questionnaire](getting-started/quickstart.md).
3. [Choose the correct extraction API](guides/extraction.md).
4. [Define completed-answer output safely](guides/completed-questionnaires.md).
5. [Interpret common skip patterns](guides/skip-patterns.md).
6. [Deploy the provider-free workflow in Palantir Foundry](platforms/palantir-foundry.md).
7. [Configure mAI Factory](integrations/mai-factory.md) or another [AI provider](guides/ai-providers.md).
8. [Check all features and limitations](project/features.md).
9. [Use the typed API reference](reference/index.md).
