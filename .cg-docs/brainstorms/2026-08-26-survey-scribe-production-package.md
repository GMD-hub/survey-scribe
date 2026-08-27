---
date: 2026-08-26
title: "Survey Scribe Production Package Architecture"
status: decided
scope: "Deep"
artifact-schema-version: 1
chosen-approach: "Ports-and-adapters modular package"
tags: [python, packaging, architecture, llm, docling, svis, providers, open-source]
---
<!-- Valid status values: decided, in-progress, abandoned -->

# Survey Scribe Production Package Architecture

## Context

The repository is a functional proof-of-concept that converts household survey questionnaire PDFs into Survey Variable Information Schema (SVIS) JSON. Its reusable strengths are the Pydantic schema, prompts, Docling conversion, and deterministic metadata corrections. Its current runtime is not suitable for broad distribution:

- `docling_pipeline.py` is a script rather than an installable package API.
- `agents/svis_agent.py` constructs a synchronous World Bank Azure client at import time.
- Provider endpoint, model, authentication, retry, and token settings are hardcoded.
- The internal `itsai` dependency is not available from public PyPI.
- The pipeline supports PDF only and deliberately skips image-only scans.
- Configuration is spread across module constants.
- Tests cover schema construction but not the pipeline, providers, sources, CLI, or packaging.
- Documentation contains stale references to removed files and earlier provider designs.

The desired product is a local-first, bring-your-own-key Python package. It should transform supported questionnaire formats into the bundled SVIS schema by default while allowing advanced users to supply a custom Pydantic response model.

No `compound-gpid.md` charter or `compound-gpid.local.md` configuration existed during the brainstorm, so charter alignment and project-specific Compound GPID settings could not be verified.

## Requirements

### Product Purpose

- Keep questionnaire-to-SVIS conversion as the opinionated primary use case.
- Make the package usable by external Python developers and analysts without World Bank-only dependencies.
- Provide a simple Python SDK and a thin CLI over the same application service.
- Keep the common path limited to a questionnaire, model, API key, and optional OpenAI-compatible base URL.
- Support custom Pydantic output models through an advanced API without weakening the SVIS-first product identity.
- Keep execution local and BYOK; do not make a hosted service part of the package requirement.

### Public API

- Provide a top-level `SurveyScribe` facade.
- Expose synchronous `convert()` and asynchronous `aconvert()` methods.
- Expose sync and async batch conversion with bounded concurrency.
- Return a typed `ExtractionResult[T]` rather than writing as an unavoidable side effect.
- Represent outcomes as `success`, `partial`, or `failed`.
- Preserve the current root CLI shape and `run(Path, Path) -> None` through deprecated compatibility shims during the 1.x line.
- Do not preserve every current internal import path under `agents`, `extractors`, and `schemas`.

### Provider Flexibility

- Make an OpenAI-compatible endpoint the primary provider route.
- Support OpenAI, OpenRouter, Vercel AI Gateway/endpoints, and custom compatible gateways through one adapter.
- Add native Azure OpenAI/Foundry and Anthropic adapters where endpoint, authentication, or structured-output behavior differs.
- Support API keys and injected token providers.
- Resolve credentials from explicit values first and provider-standard environment variables second.
- Never persist secrets in TOML, logs, diagnostics, or run artifacts.
- Keep Instructor behind provider adapters to preserve structured Pydantic validation and retry behavior without exposing Instructor types publicly.
- Remove import-time credential acquisition and network/client construction.

### Input Formats

Use an explicit support-tier contract instead of promising literal compatibility with every possible file format.

| Tier | Formats | Support expectation |
| --- | --- | --- |
| Tier 1 | Digital/scanned PDF, DOCX, XLSX, CSV, HTML, Markdown, plain text | Documented, fixture-backed, CI-tested |
| Tier 2 | XLSForm workbooks and Survey Solutions exports | Format-specific adapters with documented limitations |
| Extension | Other formats | Public source adapter protocol; no built-in guarantee |

- Use Docling OCR for scanned PDFs and expose page-level quality warnings.
- Use deterministic parsers for structured survey formats so native names, choices, sections, and skip logic are not flattened into lossy text.
- Preserve page, sheet, row, heading, table, and block provenance where available.
- Use token-aware, table-aware chunking and completeness checks for dense repeated questionnaire rows.

### Schema and Validation

- Keep the current SVIS field structure as the default main JSON output for downstream compatibility.
- Store provider, model, prompt version, diagnostics, failed blocks, metrics, and run provenance in a separate sidecar or opt-in rich envelope.
- Keep structural Pydantic validation separate from deterministic quality rules.
- Set `needs_review=True` deterministically below the configured confidence threshold or when quality rules identify review conditions.
- Add survey-wide reconciliation for duplicate names, repeated questions, chunk overlap, and module provenance.
- Accept a caller-supplied Pydantic `BaseModel` through `StructuredPipeline[T]`.
- Give custom schemas framework-level transport, chunking, retry, provenance, and validation guarantees, but not automatic SVIS quality guarantees.

### Configuration

- Make typed Python configuration the canonical programmatic interface.
- Support one optional `survey-scribe.toml` format.
- Use CLI flags, environment variables, TOML, and package defaults in documented precedence order.
- Configure model, endpoint, temperature where supported, timeouts, retries, concurrency, chunk limits, review threshold, validation policy, and artifact persistence.
- Reject explicitly unsupported model settings instead of silently ignoring them.
- Support CPython 3.11, 3.12, and 3.13.

### Failure Behavior

- Return `success` when all required stages and source blocks complete.
- Return `partial` when usable data exists but blocks, pages, or required metadata remain incomplete.
- Return `failed` when no usable validated output exists or configuration/authentication/source normalization cannot start.
- Keep low-confidence review flags distinct from partial execution status.
- Make the default CLI exit code `0` for success and partial results, and nonzero for failed results.
- Add strict mode so partial results exit nonzero and do not write the main partial SVIS JSON.
- Write status and diagnostics to the sidecar so automation can detect partial extraction even when the default exit code is `0`.

### Packaging, Documentation, and Website

- Use a `src/` package layout, `pyproject.toml`, Hatchling, `uv`, type hints, and `py.typed`.
- Keep PDF plus OpenAI-compatible conversion available in the default installation.
- Put native Anthropic and Azure identity dependencies behind optional extras.
- Add Ruff, Pyright, pytest/pytest-asyncio, package build checks, and cross-platform CI.
- Publish MkDocs Material documentation with mkdocstrings and generated schema/config references.
- Document every supported provider, source format, status, migration path, privacy rule, and known model-quality tradeoff.
- Provide a static, curated-sample playground that makes no live model calls and accepts no uploads or API keys.

### Licensing

The intended license is the same bespoke World Bank Master Community License Agreement used by Survey Solutions. GitHub classifies that license as `Other`/`NOASSERTION`, and it includes terms that differ from standard OSI licenses. World Bank legal approval is a blocking release requirement before copying the license, accepting contributions, or describing the project as open source.

## Approaches Considered

### Approach 1: Ports-and-Adapters Modular Package

Create one installable `survey-scribe` distribution with explicit provider and source protocols, a stable intermediate questionnaire representation, a typed result model, optional provider extras, and future entry-point plugin compatibility.

**Pros**

- Keeps installation and documentation coherent for first-time users.
- Isolates Docling, provider SDKs, Instructor, credentials, and persistence behind testable boundaries.
- Supports fake providers and synthetic source fixtures in offline CI.
- Preserves a simple facade while allowing advanced extensions.
- Allows provider/source packages to split later if real dependency or maintenance needs emerge.

**Cons**

- The main repository owns the built-in provider and source adapter compatibility matrix.
- Requires careful capability and error normalization across provider SDKs.

**Recommendation:** Yes. This balances usability, extensibility, and production testability.

### Approach 2: Plugin Microkernel from the First Release

Publish a minimal core and release each provider and source adapter as a separate distribution discovered through Python entry points.

**Pros**

- Independent dependency and release cycles.
- Third parties can own adapters without changing core.

**Cons**

- Creates a package-version compatibility matrix before an ecosystem exists.
- Makes installation, support, security review, and documentation harder.
- Increases the chance that new users cannot identify the correct plugin set.

**Recommendation:** No for v1. Preserve plugin-compatible protocols but defer package splitting.

### Approach 3: Third-Party Multiprovider Router as the Core

Delegate provider normalization to a unified routing library and focus Survey Scribe on source conversion and SVIS logic.

**Pros**

- Faster initial provider breadth.
- Less provider-specific code in this repository.

**Cons**

- Authentication, structured output, errors, model settings, and gateway behavior still differ.
- Introduces a critical external abstraction and migration risk.
- Makes the World Bank token-provider and custom endpoint paths harder to control.

**Recommendation:** No. A router may be added later as one provider adapter, not the architectural center.

## Devil's Advocate

### Problem Validation

The technical packaging problem is real: the hardcoded gateway, internal dependency, import-time client, missing package metadata, and narrow test surface prevent public reuse. External demand for every source format and a product website has not yet been demonstrated, so format and website investments should be validated against representative adopters and a non-restricted golden corpus.

### Simplicity Check

Five provider brands do not require five unrelated public APIs. OpenAI, OpenRouter, Vercel Gateway, and custom compatible endpoints should use one adapter. Native adapters should exist only when protocol, authentication, or structured-output differences require them.

### Effort-Value Check

Format breadth and the playground must not delay a trustworthy package core. The implementation should establish packaging, compatibility fixtures, result/config contracts, the PDF/text path, and provider contract tests before filling the complete Tier 1/Tier 2 matrix.

### Charter Alignment

Alignment could not be verified because no `compound-gpid.md` project charter existed. The license choice also requires legal review before public release claims.

## Decision

Adopt the **ports-and-adapters modular package**.

The canonical product is `SurveyScribe`, an SVIS-first facade over a provider-independent application pipeline. The application consumes a normalized `QuestionnaireDocument`, calls a `StructuredProvider`, applies deterministic reconciliation and quality policy, and returns `ExtractionResult[SurveySVIS]`. An advanced `StructuredPipeline[T]` supports trusted caller-supplied Pydantic models.

The implementation will remain one distribution for v1, use an OpenAI-compatible provider as the simplest BYOK route, and add native Azure/Anthropic adapters as optional integrations. The default JSON remains legacy-compatible, while operational metadata is written separately. Source formats are governed by explicit support tiers, and scanned PDFs are processed with Docling OCR plus diagnostics.

This decision prioritizes adoption: simple defaults, no hosted credential custody, no import-time authentication, no required internal packages, and no plugin-package maze. It retains extensibility through protocols rather than exposing provider SDK details in the public API.

## Next Steps

The implementation-ready roadmap is captured in:

`.kilo/plans/1787694223076-survey-scribe-package-blueprint.md`

The ordered handoff is:

1. Obtain legal approval and freeze compatibility/quality fixtures.
2. Create the installable `src/survey_scribe` package and build/test configuration.
3. Add typed configuration, results, diagnostics, errors, and atomic artifacts.
4. Move Docling and structured input handling behind source adapters.
5. Move Instructor/provider SDK behavior behind provider adapters.
6. Rebuild orchestration around an async core with a sync facade.
7. Add the SVIS-first facade and custom Pydantic pipeline.
8. Complete Tier 2 structured survey adapters.
9. Add the CLI and legacy `docling_pipeline.py` shim.
10. Build cross-platform contract, golden-quality, packaging, and release CI.
11. Publish MkDocs documentation and the sample-only playground.
12. Stage preview, prerelease, and stable releases behind legal, security, compatibility, and quality gates.

The first implementation work should characterize current behavior rather than immediately move all files. This protects the downstream SVIS contract and ensures refactoring defects can be distinguished from intentional quality corrections.
