# Evaluation Policy

## Evidence Classes

- Synthetic fixtures verify deterministic schema, parsing, status, and artifact
  mechanics.
- Sanitized real fixtures may verify extraction quality only when their rights,
  restrictions, checksums, expected inventory, and field judgments are recorded.
- Historical narrative results are context only and cannot pass a threshold.

Deterministic routing mechanics and live provider quality are different evidence
classes. A passing mechanics run does not establish mAI Factory, gateway-route,
or exact-model quality.

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

## Routing mechanics

This is a repository-maintainer command. It requires a source checkout and is not
part of the installed package CLI or SDK. Run it without provider credentials:

```console
uv run python scripts/evaluate_routing.py --manifest tests/fixtures/routing/manifest.toml
```

The evaluator compares expected, first-pass, and post-review snapshots. It uses
multiset edge scoring so parallel directed edges remain distinct. It reports:

- node and accepted-edge precision and recall;
- target accuracy, where a missing or unresolved expected route is a miss;
- normalized condition-AST exact match with `raw_text` excluded from identity;
- terminal and loop classification exact match;
- unresolved-route and invented accepted source-ID counts; and
- first-pass to post-review deltas.

The report contains metrics and SHA-256 digests, not questionnaire text,
reviewer prose, or unresolved raw references. Zero denominators are reported as
unavailable, not as perfect scores. A separate 1,000-node/3,000-edge run records
hardware, duration, and peak traced memory without a cross-platform time limit.

## Optional model-quality capture

G6 is an optional protected test action. It is `not_run` unless a human approves
one sanitized dry-run summary for an authorized source, gateway route, credential
environment-variable name, request and token ceilings, temporary-output policy,
and stop conditions. No provider call occurs as part of the deterministic package
gates.

A dynamic institutional route can support only a gateway-route claim. An exact
backend quality claim requires a pinned backend. Returned provider and model
metadata can describe one observed dynamic response, but it does not pin the
route. A missing or failed capture limits quality claims but does not weaken or
block deterministic mechanics evidence.

## Golden extraction manifest requirements

Each fixture record must include path, kind, rights basis, restrictions,
SHA-256, expected variable count, field-judgment status, provider/model identity,
and prompt version. Validation fails on a missing file, checksum drift, unknown
rights basis, or a missing required threshold.

Routing source manifests instead declare source-only, benchmark-ineligible
fixtures. The routing mechanics manifest declares repository-generated synthetic
artifacts, checksums, and restrictions against provider calls, quality claims,
source text, and reviewer prose.

## Reproducibility

Golden evaluation is offline by default. Provider calls are never made by pull
request tests. Any future recorded response must be synthetic or sanitized and
must omit credentials, raw headers, and restricted questionnaire text.
