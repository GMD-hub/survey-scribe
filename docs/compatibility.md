# Compatibility Contract

## Legacy Entry Points

The following behavior remains supported through 1.x:

- `python docling_pipeline.py INPUT [--output-dir DIR]`
- `docling_pipeline.run(Path, Path) -> None`
- Main output name `<survey_id>_svis.json`
- Existing SVIS keys, nesting, JSON value types, enum values, defaults, nulls,
  and field order

The package command introduced in Phase 1 is a bootstrap surface only. The full
SDK and command outcome contract is implemented in later phases.

## Characterized Legacy Outcomes

| Condition | Legacy behavior |
| --- | --- |
| Missing input | Message on stdout and exit 1 |
| Non-PDF suffix | Message on stdout and exit 1 |
| Scanned input | Print skip message, write nothing, return `None` |
| No converted chunks | Print skip message, write nothing, return `None` |
| Metadata `InstructorError` | Write output with placeholder metadata |
| One failed variable chunk | Omit that chunk and append extraction notes |
| All variable chunks fail | Write an empty variable list |
| Existing output | Unlink then replace it |
| Successful `run()` | Return `None` |

Uncaught import, authentication, provider, and write exceptions remain part of
the frozen characterization, not desired future behavior.

## Intentional Corrections

Only corrections listed in
`tests/fixtures/legacy/intentional-corrections.toml` may alter output values
while preserving the JSON contract. All other differences require an approved
compatibility decision.

## Configuration Migration

The final legacy shim will discover only `./survey-scribe.toml`, followed by
environment configuration. It will not search parent or home directories and
will not restore import-time World Bank credentials. Missing configuration will
produce one actionable migration error.
