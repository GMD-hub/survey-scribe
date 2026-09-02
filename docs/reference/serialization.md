# Serialization API

The public serialization helpers preserve the legacy model field order and
produce JSON-compatible values. Use `ExtractionResult.write()` for versioned
artifact publication with atomic per-file replacement.

::: survey_scribe.serialization.legacy
    options:
      members:
        - legacy_payload
        - legacy_json_bytes

Routed publication uses `RoutedSurveySVISArtifactSerializer`, writes a routed
main plus exact legacy projection, and records manifest version 2.

::: survey_scribe.serialization.routing
    options:
      members:
        - RoutedSurveySVISArtifactSerializer
        - parse_artifact_manifest
