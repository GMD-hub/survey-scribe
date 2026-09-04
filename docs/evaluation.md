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

## Authoritative quality command

Run the complete deterministic quality gate from a source checkout:

```console
uv run python scripts/evaluate_quality.py --manifest tests/fixtures/golden/manifest.toml --thresholds tests/fixtures/golden/quality-thresholds.toml --offline
```

The command blocks Python socket connections, validates both approved manifests,
checks exact SVIS serialization, and reuses the routing evaluator. Its JSON report
at `.cache/quality/evaluation.json` names every threshold, baseline, value,
availability state, and result. The synthetic baseline can pass exact schema and
routing mechanics only. `variable_recall`, `field_accuracy`, and
`dense_repeated_table_recall` stay explicitly unavailable until an approved real
corpus exists. An unavailable metric does not become a synthetic quality claim.

## Security boundaries

Security has two separate commands:

```console
uv run python scripts/run_security_gates.py collect --output-dir .cache/security
uv run python scripts/run_security_gates.py verify --reports .cache/security --allowlist security/allowlist.toml
```

`collect` invokes `pip-audit`, Bandit, and detect-secrets. Only the dependency
advisory lookup is network-enabled. Static and tracked-file secret scans are local.
Collection writes machine-readable scanner envelopes even when a scanner reports
findings; collection does not decide policy.

Bandit and detect-secrets are labeled `tool-offline`, not `network-blocked`.
Their selected modes have no network function, but the collection command does
not install an operating-system sandbox around scanner child processes. The
authoritative `verify` process still enforces its in-process socket boundary.

`verify` blocks Python socket connections before it reads evidence. It rejects
missing, malformed, stale, future-dated, incomplete, or wrong-boundary reports. It
also requires every allowlist entry to name its scanner, exact finding fingerprint,
owner, rationale, and future expiry. This command is the only authoritative
security policy exit. `.secrets.baseline` separately records reviewed synthetic
values and checksums with an owner, rationale, and expiry. The current dependency
allowlist has short-lived entries for `diskcache` and `transformers`, which are
transitive dependencies without a currently compatible fixed release.

Workflow policy is also local and deterministic:

```console
uv run python scripts/check_workflow_policy.py .github/workflows
```

It requires reviewed immutable action SHAs, top-level `contents: read`, no tag
trigger, and no package publication. The only deployment exception is the approved
GitHub Pages workflow in `deploy-docs.yml`, with job-scoped `pages: write` and
`id-token: write` as recorded in `docs/legal-disposition.md`.

## Package and SBOM evidence

After dependency and wheelhouse preparation, run the artifact checks offline:

```console
uv build
uv run twine check --strict dist/*.whl dist/*.tar.gz
uv run check-wheel-contents dist/*.whl
uv run python scripts/build_wheel_sbom.py --wheel dist/survey_scribe-0.1.0-py3-none-any.whl --wheelhouse .cache/wheelhouse --output dist/sbom.cdx.json
UV_OFFLINE=1 uv run pytest tests/package
```

The wheelhouse preparation step is the last package-job network boundary. SBOM
generation and package tests then run with `UV_OFFLINE=1`. The SBOM command
installs only the exact wheel and locked runtime wheels in a temporary environment.
It validates CycloneDX 1.6, root name/version, direct dependency names, and the
exact wheel SHA-256. Package tests verify the same artifact's contents and block
network during import and CLI smoke checks.

CI runs all required test categories with `pytest-socket --disable-socket
--allow-unix-socket` and the configured 95 percent coverage floor. The
Unix-socket exception is required by Python's local asyncio event loop and does
not permit TCP provider traffic.

Documentation and browser evidence use an explicit browser-install boundary:

```console
uv run playwright install chromium
UV_OFFLINE=1 uv run mkdocs build --strict --clean
UV_OFFLINE=1 uv run linkchecker --ignore-url='^https?://' site/
UV_OFFLINE=1 uv run pytest --disable-socket --allow-unix-socket tests/docs tests/browser
```

The browser tests fulfill a virtual local origin only from generated `site/`
files and reject every external route. The locally pinned
`axe-playwright-python==0.1.8` package embeds axe-core 4.12.1. Browser checks fail on
serious or critical WCAG 2 A/AA and WCAG 2.1 AA violations on every desktop and
mobile route. Deterministic checks also cover one page heading, heading order,
unique IDs, keyboard behavior, mobile overflow, and playground policy. No live
provider call is part of these commands.

## Golden extraction manifest requirements

Each fixture record must include path, kind, rights basis, restrictions,
SHA-256, expected variable count, field-judgment status, provider/model identity,
and prompt version. Approved sanitized source and output records must bind each
other by ID and digest. The output stores a recorded `actual_output`, an expected
variable-ID inventory, independent JSON-pointer field judgments, and explicit
dense-table row-variable inventories. Validation fails on a missing pair, stale
checksum, invalid judgment, unknown rights basis, or missing threshold.

Routing source manifests instead declare source-only, benchmark-ineligible
fixtures. The routing mechanics manifest declares repository-generated synthetic
artifacts, checksums, and restrictions against provider calls, quality claims,
source text, and reviewer prose.

## Reproducibility

Golden evaluation is offline by default. Provider calls are never made by pull
request tests. Any future recorded response must be synthetic or sanitized and
must omit credentials, raw headers, and restricted questionnaire text.
