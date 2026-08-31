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
    `-- <survey_id>/
        |-- active.json
        `-- generations/
            `-- <generation_id>/
                |-- <survey_id>_svis.json
                |-- <survey_id>_sidecar.json
                `-- manifest.json
```

The main path is a legacy-compatible projection. Generation directories preserve
immutable historical output, and `active.json` identifies the current generation.

## Collision and overwrite behavior

A second write for the same survey raises `ArtifactCollisionError` by default.
To publish a new generation while preserving the old one:

```python
updated = result.write(Path("output"), overwrite=True)
```

The writer restricts `survey_id` to letters, numbers, dots, underscores, and
hyphens, and uses a lock to reject concurrent writers for the same survey.

The output directory and its existing `.survey-scribe` tree must be trusted and
free of symlinks. The writer resolves the output root but follows pre-existing
internal path components.

Each file replacement is atomic. Publication is not one crash-atomic operation
across the legacy projection and `active.json`. An interrupted process can leave
those paths on different generations. Readers that need generation consistency
must resolve `active.json` and verify its manifest. After an unclean shutdown,
compare the projection with the active generation and republish if required.

## Sensitive content

Sidecar diagnostics pass through package redaction. The main SVIS output is the
intended data product and can contain full `question_text`, labels, filenames,
and notes. Write artifacts only to an approved, access-controlled location.

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
