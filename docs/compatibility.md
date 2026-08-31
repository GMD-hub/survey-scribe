# Compatibility

Survey Scribe uses Semantic Versioning and treats public serialized SVIS behavior
as compatibility-sensitive.

## Stable `0.1.x` imports

The supported top-level exports are:

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

The package also includes tested secondary modules for configuration, results,
serialization, and sources. Import those names from the module shown in the
[API Overview](reference/index.md).

## Serialized SVIS contract

Changes to these items can affect consumers:

- Field names, order, nesting, types, required status, and defaults.
- Enum values and JSON representation.
- Date serialization and null behavior.
- Pydantic validation behavior.
- The legacy main artifact name `<survey_id>_svis.json`.

Pin a compatible package version when another system consumes generated JSON or
JSON Schema.

## Deprecated schema path

The wheel retains this compatibility import:

```python
from schemas.svis import SurveySVIS
```

New code must use `from survey_scribe import SurveySVIS`. The `schemas` path can
be removed in a future major release after a documented deprecation period.

## Legacy repository pipeline

The repository contains `docling_pipeline.py` for characterization and migration.
It is not included in the wheel, is not exposed by the installed command, and
depends on internal provider authentication. Its behavior is a repository
compatibility contract, not the installed SDK contract.

For existing repository users, these entry points remain characterized through
1.x:

- `python docling_pipeline.py INPUT [--output-dir DIR]`
- `docling_pipeline.run(Path, Path) -> None`
- Main output name `<survey_id>_svis.json`
- Existing SVIS keys, nesting, JSON value types, enum values, defaults, nulls,
  and field order

### Characterized outcomes

| Condition | Repository-only legacy behavior |
| --- | --- |
| Missing input | Message on stdout and exit 1 |
| Non-PDF suffix | Message on stdout and exit 1 |
| Scanned input | Print skip message, write nothing, return `None` |
| No converted chunks | Print skip message, write nothing, return `None` |
| Metadata `InstructorError` | Write output with placeholder metadata |
| One failed variable chunk | Omit that chunk and append extraction notes |
| All variable chunks fail | Write an empty variable list |
| Existing output | Unlink it and then replace it |
| Successful `run()` | Return `None` |

Uncaught import, authentication, provider, and write exceptions are
characterized behavior, not recommended application behavior.

Only corrections listed in
`tests/fixtures/legacy/intentional-corrections.toml` can alter output values while
preserving this JSON contract. Other changes require an explicit compatibility
decision.

## Command-line boundary

The `survey-scribe` command supports `--help` and `--version`. An extraction
command is not part of `0.1.x`.

## Python and Pydantic

The package supports Python 3.11 through 3.13 and Pydantic 2.11.7 or later below
major version 3. The package ships `py.typed` for static type checking.
