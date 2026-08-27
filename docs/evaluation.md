# Evaluation Policy

## Evidence Classes

- Synthetic fixtures verify deterministic schema, parsing, status, and artifact
  mechanics.
- Sanitized real fixtures may verify extraction quality only when their rights,
  restrictions, checksums, expected inventory, and field judgments are recorded.
- Historical narrative results are context only and cannot pass a threshold.

## Required Metrics

The canonical thresholds are in
`tests/fixtures/golden/quality-thresholds.toml`.

| Metric | Meaning |
| --- | --- |
| `exact_schema_compatibility` | Exact legacy keys, nesting, types, defaults, nulls, enums, and ordering |
| `variable_recall` | Expected questionnaire variables recovered |
| `field_accuracy` | Approved field judgments matched |
| `dense_repeated_table_recall` | Expected rows recovered from repeated dense tables |

Synthetic fixtures can satisfy exact schema compatibility but cannot establish
real-document recall or field accuracy. Those metrics remain unavailable until
an approved corpus exists.

## Manifest Requirements

Each fixture record must include path, kind, rights basis, restrictions,
SHA-256, expected variable count, field-judgment status, provider/model identity,
and prompt version. Validation fails on a missing file, checksum drift, unknown
rights basis, or a missing required threshold.

## Reproducibility

Golden evaluation is offline by default. Provider calls are never made by pull
request tests. Any future recorded response must be synthetic or sanitized and
must omit credentials, raw headers, and restricted questionnaire text.
