# Results and Artifacts

`ExtractionResult[T]` is a frozen envelope for usable output, diagnostics,
failed source blocks, status, and local artifact references. The generic output
type can be `SurveySVIS` or another application model.

## Create a result

```python
from survey_scribe.results import (
    Diagnostic,
    DiagnosticCode,
    DiagnosticSeverity,
    ExtractionResult,
    FailedBlock,
)

result = ExtractionResult(
    output=survey,
    diagnostics=(
        Diagnostic(
            code=DiagnosticCode.quality_low_confidence,
            message="One variable needs human review.",
            severity=DiagnosticSeverity.warning,
            details={"raw_name": "q_age"},
        ),
    ),
    failed_blocks=(
        FailedBlock(
            block_id="block-000042",
            message="The answer table was incomplete.",
            source_order=41,
        ),
    ),
)
```

When `survey_id` is omitted and `output.survey_id` is a string, the envelope
copies it automatically.

## Result fields

| Field | Type | Default |
| --- | --- | --- |
| `output` | `T \| None` | Required |
| `survey_id` | `str \| None` | `None` |
| `run_id` | `str` | Random UUID4 hexadecimal value |
| `diagnostics` | `tuple[Diagnostic, ...]` | `()` |
| `failed_blocks` | `tuple[FailedBlock, ...]` | `()` |
| `artifacts` | `tuple[ArtifactReference, ...]` | `()` |
| `status` | `ResultStatus` | Computed |

The envelope is frozen. Caller-owned output can remain mutable.

## Status rules

| Status | Condition |
| --- | --- |
| `failed` | `output is None` |
| `partial` | A failed block, error diagnostic, or operational failure code exists |
| `success` | Usable output exists without an operational failure |

A low-confidence quality warning alone remains `success`. It reports a review
condition, not a failed extraction operation.

## Detached snapshots

```python
snapshot = result.serialization_snapshot()
```

The method returns a deep-copied, JSON-compatible `dict[str, Any]`. Later changes
to mutable caller-owned output do not change the returned snapshot.

## Write artifacts

```python
from pathlib import Path

written = result.write(
    Path("output"),
    sidecar=True,
    overwrite=False,
)
```

`write()` returns a new `ExtractionResult[T]` with `ArtifactReference` values.
Each reference contains its role, path, generation ID, and SHA-256 digest.

The output layout is:

```text
output/
|-- <survey_id>_svis.json
`-- .survey-scribe/
    |-- aliases/
    `-- surveys/
        `-- <exact_identity_key>/
            |-- active.json
            `-- generations/
                `-- <generation_id>/
                    |-- <survey_id>_svis.json
                    |-- <survey_id>_sidecar.json
                    `-- manifest.json
```

An exact `SurveySVIS` uses the legacy-compatible `_svis.json` projection. Other
output types use `_result.json` by default. Supply a typed serializer to select a
different safe filename and artifact plan:

```python
from survey_scribe.serialization import JsonArtifactSerializer

serializer = JsonArtifactSerializer(MyResult, filename_suffix="_analysis.json")
written = result.write(Path("output"), serializer=serializer)
```

Generation directories preserve immutable historical output, and `active.json`
identifies the current generation.

### Routed output

An exact `RoutedSurveySVIS` uses manifest version 2 and publishes both the routed
main and the ordered legacy projection:

```text
output/
|-- <survey_id>_svis.json
`-- .survey-scribe/surveys/<exact_identity_key>/generations/<generation_id>/
    |-- <survey_id>_routed_svis.json
    |-- <survey_id>_svis.json
    |-- <survey_id>_sidecar.json
    `-- manifest.json
```

The routed main contains `routing_schema_version`, `routing_graph`, and the
append-only audit. The stable `<survey_id>_svis.json` file is reconstructed as an
exact v1 `SurveySVIS`; routed-only fields are not added to the legacy model.
Manifest v2 records the equal routed and graph schema versions, both output
digests, prompt versions, and source/model response digests without raw prompt or
response bodies.

The exact audit path is `routing_graph.routing_audit`. Routing-specific status
uses the standard result envelope:

| Routing outcome | Result status |
| --- | --- |
| Usable graph with unresolved review warnings | `success` |
| Usable graph with an unlinked variable or failed source region | `partial` |
| No usable graph after source, provider, or invariant failure | `failed` |

## Collision and overwrite behavior

A second write for the same survey raises `ArtifactCollisionError` by default.
To publish a new generation while preserving the old one:

```python
updated = result.write(Path("output"), overwrite=True)
```

The writer restricts `survey_id` to portable, non-reserved filename characters.
It rejects case and trailing-dot aliases. A process-owned OS lock covers both
recovery and publication and is released by the operating system after a crash.

Internal symlinks and Windows reparse points are rejected. Generation files are
written and flushed in a staging directory before one durable rename. A typed
journal makes the new generation authoritative before stable projection writes.
After an unclean shutdown, the next writer repairs the projection and pointer
idempotently while it holds the same process lock. Required file and directory
flush errors abort publication instead of being ignored.

## Sensitive content

Sidecar diagnostics pass through package redaction. The main SVIS or routed SVIS
artifact is the intended data product and can contain questionnaire content,
filenames, notes, and bounded source citations. Logs, diagnostics, sidecars,
manifests, evaluator reports, and persistent caches must not contain source or
model prose. Write artifacts only to an approved, access-controlled location.

## Legacy serialization

Use `legacy_payload()` for JSON-compatible Python values or
`legacy_json_bytes()` for stable UTF-8 bytes:

```python
from survey_scribe.serialization import legacy_json_bytes, legacy_payload

values = legacy_payload(survey)
payload = legacy_json_bytes(survey)
```

The byte serializer preserves model field order, uses two-space indentation, and
rejects non-finite JSON numbers.
