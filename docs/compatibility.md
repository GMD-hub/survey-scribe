# Compatibility

Survey Scribe uses Semantic Versioning and treats public serialized SVIS behavior
as compatibility-sensitive.

## Stable legacy imports

The legacy top-level model exports remain supported:

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

Additive routed models, `QuestionnaireRouter`, and `RoutingConfig` are also
available from `survey_scribe`. The package includes tested secondary modules for
configuration, providers, results, routing, serialization, and sources. Import
lower-level names from the module shown in the [API Overview](reference/index.md).

## Serialized SVIS contract

Changes to these items can affect consumers:

- Field names, order, nesting, types, required status, and defaults.
- Enum values and JSON representation.
- Date serialization and null behavior.
- Pydantic validation behavior.
- The legacy main artifact name `<survey_id>_svis.json`.

Pin a compatible package version when another system consumes generated JSON or
JSON Schema.

## Removed source-tree schema path

The old repository-only `schemas.svis` path is not in the wheel. Import public
models from `survey_scribe`.

## Legacy repository pipeline

The repository contains `docling_pipeline.py` for migration. It is not included
in the wheel. It lazily uses the public package API and current configuration
resolution while preserving the selected legacy entry points.

For existing repository users, these entry points remain characterized through
1.x:

- `python docling_pipeline.py INPUT [--output-dir DIR]`
- `docling_pipeline.run(Path, Path) -> None`
- Main output name `<survey_id>_svis.json`
- Existing SVIS keys, nesting, JSON value types, enum values, defaults, nulls,
  and field order

The shim accepts only PDF input, writes the legacy projection without a sidecar,
overwrites an existing projection, returns `None` from `run()`, and reports one
actionable error for invalid input, configuration, conversion, or writing.

Only corrections listed in
`tests/fixtures/legacy/intentional-corrections.toml` can alter output values while
preserving this JSON contract. Other changes require an explicit compatibility
decision.

## Command-line boundary

The `survey-scribe` command supports `convert`, `batch`, `providers`,
`config check`, and `schema export routing`. See the [migration guide](migration.md)
for differences from the root shim.

## Additive routed contract

`RoutedSurveyVariable` and `RoutedSurveySVIS` extend the legacy models without
adding fields to `SurveyVariable` or `SurveySVIS`. The routed artifact has schema
version `1.0`; its legacy projection preserves keys, nesting, JSON value types,
defaults, enum values, field order, and variable order. Runtime interview
execution is not part of this contract.

## Python and Pydantic

The package supports Python 3.11 through 3.13 and Pydantic 2.11.7 or later below
major version 3. The package ships `py.typed` for static type checking.
