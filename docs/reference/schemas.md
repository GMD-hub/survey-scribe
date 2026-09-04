# JSON Schemas

These canonical files are generated from the installed Pydantic models. The docs
test suite regenerates each file in memory and fails on any byte-level drift.

- [SVIS JSON Schema](../assets/generated/svis.schema.json)
- [Questionnaire routing JSON Schema](../assets/generated/questionnaire-routing.schema.json)
- [Non-secret configuration serialization schema](../assets/generated/survey-scribe-config.schema.json)

The configuration schema uses Pydantic serialization mode. Credential fields and
the callable token provider are excluded because they cannot be persisted. Use
the [configuration guide](../guides/configuration.md) for environment-only fields
and precedence.

Regenerate or verify the files from a source checkout:

```console
uv run python scripts/generate_docs_reference.py
uv run python scripts/generate_docs_reference.py --check
```

The CLI also exports the canonical routing schema to standard output:

```console
survey-scribe schema export routing > questionnaire-routing.schema.json
```
