# Results API

Result models are frozen and reject unknown fields. `ExtractionResult[T]` can
contain mutable caller-owned output even though the envelope is frozen.

See [Results and Artifacts](../guides/results.md) for status rules, filesystem
layout, collision behavior, and sensitive-data handling.

Typed artifact-plan and serializer ports are exported from
`survey_scribe.serialization`.

::: survey_scribe.results
    options:
      members:
        - ResultStatus
        - DiagnosticSeverity
        - DiagnosticCode
        - Diagnostic
        - FailedBlock
        - ArtifactKind
        - ArtifactReference
        - ExtractionResult
