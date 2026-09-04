# Privacy and Local-First Boundaries

Survey Scribe is local-first, not offline-only. It accepts local paths, validates
and normalizes files on the local machine, and has no package telemetry client.
The package does not send analytics, usage events, or document samples to the
Survey Scribe maintainers.

## When data leaves the machine

Native XLSForm conversion and local source normalization do not need a model
provider. Provider-backed extraction sends normalized questionnaire content to
the endpoint that the user configures. The package cannot control that
provider's logging, retention, region, training, or abuse-monitoring policy.
Review the provider contract and institutional data policy before conversion.

No remote source URL is accepted. Provider calls occur only after explicit
provider construction or CLI configuration. PDF OCR uses validated local model
artifacts and disables model downloads; use an operating-system network policy
when an enforceable offline boundary is required.

## Data retained locally

Survey Scribe does not add a questionnaire-content cache. The main output is the
intended data product and can contain question text, labels, filenames, and source
references. Sidecars contain redacted diagnostics. Manifests contain metadata and
digests. Store all generated artifacts in an approved location and apply your own
retention and access policy.

Credentials are excluded from configuration serialization and must not be stored
in TOML. The package does not write provider keys or bearer tokens to artifacts.
It also does not use browser cookies, browser storage, or a service worker in the
static sample explorer.

## Documentation site

The documentation site has no configured analytics and uses no external web
fonts. Its [sample explorer](../playground.md) contains precomputed synthetic JSON
and local JavaScript only. It cannot upload a file, accept questionnaire text or
credentials, call a backend, or run inference.

## Evidence limits

Passing deterministic tests establishes schema, parser, status, security-policy,
and artifact mechanics. It does not establish accuracy on real questionnaires or
quality for a live provider/model pair. Real-document recall and field accuracy
remain unavailable until an approved, rights-cleared corpus is evaluated. See the
[evaluation policy](../evaluation.md).
