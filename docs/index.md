# Survey Scribe

Survey Scribe defines the Survey Variable Information Schema (SVIS) as a typed
Python API. SVIS captures survey-level metadata and the variable-level details
needed for questionnaire review and downstream harmonization.

## Package Scope

Version `0.1.0` provides:

- Pydantic models for complete survey and variable records.
- Stable JSON serialization and validation behavior.
- Top-level typed imports and a PEP 561 marker.
- A lightweight command for package help and version inspection.

The repository's legacy PDF-to-SVIS extraction pipeline is characterized for
compatibility but is not part of the built wheel. It requires internal World
Bank authentication that cannot be installed from public PyPI.

## Start Here

1. Follow the [installation guide](installation.md).
2. Learn the [core schema workflow](usage.md).
3. Adapt the [practical examples](examples.md).
4. Consult the generated [API reference](api.md) and
   [SVIS field guide](svis_field_guide.md).

!!! note "Publication gate"

    CI builds and validates the documentation, but deployment to GitHub Pages
    remains disabled pending formal release approval. See
    [Release Readiness](release-readiness.md).
