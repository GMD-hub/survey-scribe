---
date: 2026-09-04
title: "Azure Gateway Header Compatibility"
status: completed
completed-date: 2026-09-04
scope: "Deep"
brainstorm: ".cg-docs/brainstorms/2026-09-04-public-foundry-mai-factory-compatibility.md"
language: "Python"
estimated-effort: "medium"
deviation-policy: "ask"
artifact-schema-version: 1
phases: 3
completed-phases: [1, 2, 3]
tags: [providers, azure, foundry, gateway, security]
execution-report: ".cg-docs/work-reports/2026-09-04-azure-gateway-header-compatibility.md"
---

# Plan: Azure Gateway Header Compatibility

## Objective

Extend the existing `AzureOpenAIProvider` so applications can use direct
Microsoft Foundry endpoints and Azure-compatible institutional gateways that
require caller-defined metadata and auxiliary secret headers. Keep Survey Scribe
provider-neutral, keep all exact mAI Factory configuration outside the public
package, and make no change to questionnaire extraction semantics.

## Context

The existing Azure adapter already supports either an API key or a refreshable
Azure token callback, lazy OpenAI/Instructor imports, strict structured output,
bounded package-owned retries, and normalized provider metadata. It does not
support additional gateway headers.

The approved brainstorm selects one generic Azure adapter rather than a public
`mai_factory` provider. Exact mAI Factory endpoints, scopes, header names,
environment identifiers, private package instructions, and model aliases are
unresolved or unsuitable for the public repository. The implementation must
therefore supply mechanism, not institutional policy.

This plan deliberately does not add a Responses transport. The current
questionnaire extraction path uses Instructor over Azure Chat Completions, and
the available local evidence does not establish a valid Responses contract.

## Requirements

| ID | Requirement | Source |
| --- | --- | --- |
| R1 | Keep `StructuredProvider`, `SurveyScribe`, `SurveyScribeConfig`, TOML, CLI, and environment resolution provider-neutral and unchanged. | Brainstorm decision; `compound-gpid.md` objective |
| R2 | Preserve exactly one primary Azure credential: API key or refreshable token callback. | Existing `AzureOpenAIProvider` contract |
| R3 | Accept caller-defined, non-secret static metadata headers at direct `AzureOpenAIProvider` construction only. | Brainstorm goals |
| R4 | Accept one callback that returns a mapping of auxiliary secret headers and resolve it for every package-owned outbound attempt. | Brainstorm goals; retry behavior |
| R5 | Validate static and dynamic header names and values, required names, case-insensitive collisions, and reserved transport/authentication names before sending a request. | Security requirement |
| R6 | Never retain or expose secret callback results through serialization, representation, logs, diagnostics, exceptions, or artifacts. | Charter credential constraint; security guide |
| R7 | Preserve lazy provider SDK imports, Python 3.11-3.13 support, existing optional extras, and current runtime dependencies. | Charter and `pyproject.toml` |
| R8 | Prove direct Foundry-style and mAI-style compositions with synthetic offline contract tests; do not require a live provider call. | Brainstorm decision |
| R9 | Keep public documentation generic and use placeholder endpoints, header names, and callback values only. | Public repository documentation policy |
| R10 | Keep Responses, health checks, provider deployment, credential discovery, and non-extraction APIs out of scope. | Brainstorm non-goals |

## Design Contract

### Public Constructor Surface

Add these keyword-only arguments to `AzureOpenAIProvider.__init__`:

```python
metadata_headers: Mapping[str, str] | None = None
sensitive_headers_callback: Callable[[], Mapping[str, str]] | None = None
required_headers: Collection[str] = ()
```

The names are generic and do not encode mAI Factory policy. Do not add these
fields to `SurveyScribeConfig` or the facade provider factory. Gateway-aware
applications construct `AzureOpenAIProvider` and inject it through the existing
`StructuredProvider` argument.

### Header Rules

- Header names must be non-empty ASCII HTTP token names. Normalize names with
  `casefold()` only for comparison; preserve caller spelling when sending.
- Header values must be strings that encode as ASCII, remain non-empty after
  trimming for validation, and contain no control code point from `0x00` through
  `0x1F` or `0x7F`. This explicitly rejects tab, carriage return, line feed,
  NUL, DEL, and non-ASCII values before the HTTP stack sees them. Reject leading
  or trailing ASCII spaces because the real HTTP/1.1 transport rejects them. Do
  not trim or otherwise alter a valid caller value before sending.
- Reject duplicate names within either mapping after case-insensitive
  normalization.
- Reject collisions between metadata and sensitive mappings.
- Reject static metadata names recognized by `is_sensitive_key()`, including
  subscription-key forms. The error directs callers to
  `sensitive_headers_callback` without echoing the header name. Classification is
  best effort; callers remain responsible for putting secrets with unknown names
  in the sensitive channel.
- Reject caller control of primary authentication and HTTP framing names:
  `authorization`, `proxy-authorization`, `api-key`, `host`, `content-length`,
  `content-type`, `connection`, `keep-alive`, `proxy-authenticate`,
  `proxy-connection`, `te`, `trailer`, `transfer-encoding`, `upgrade`, and
  `expect`. Apply this reserved set to both channels and to required names,
  case-insensitively. The Azure SDK and HTTP transport own these fields.
- `required_headers` accepts a non-string `Collection[str]` only. Reject bare
  `str`, `bytes`, non-string members, invalid names, reserved names, and
  case-insensitive duplicates at construction. Copy names into an immutable
  normalized set. Check satisfaction against the merged caller headers for each
  outbound attempt because a required name can come from the dynamic channel.
  Missing required headers fail as a fresh safe, non-retryable
  `ProviderAuthenticationError` before completion is called.
- Static metadata headers are copied and validated at construction. The provider
  must not retain the caller's mutable mapping.
- The sensitive callback object may be retained, but its returned mapping and
  values must not be stored on the provider or attached to an exception.

### Callback And Retry Lifecycle

- Do not invoke either credential or sensitive-header callbacks during module
  import, provider construction, representation, schema inspection, token
  estimation, or SDK client creation.
- The sensitive callback is synchronous and must be bounded and non-blocking,
  such as a read from an environment variable or host-managed in-memory secret
  cache. Async callbacks and network-bound secret acquisition are out of scope.
- Invoke `sensitive_headers_callback` inside the existing package-owned attempt
  loop, after entering the shared limiter and immediately before calling the
  completion transport.
- Validate and merge the callback result with static metadata on every attempt.
  This refreshes expiring gateway keys and prevents reuse after a retry.
- The protected base hook returns `None`. Add the internal `extra_headers`
  completion keyword only when the Azure hook returns a non-empty merged mapping.
  Existing generic and Azure completions configured without headers therefore
  receive exactly the current keyword set, including completions with explicit
  signatures and no `**kwargs`.
- When present, the Azure SDK-backed closure forwards a detached mapping as the
  request-level `extra_headers` argument to
  `patched.chat.completions.create_with_completion()`.
- Catch ordinary `Exception` only from the sensitive callback and header
  validation. Propagate `asyncio.CancelledError`, `KeyboardInterrupt`, and
  `SystemExit` unchanged.
- Detach callback and SDK failures from secret-bearing exceptions. Classify each
  failure into safe scalar state or a fresh normalized provider error, clear the
  transient header mapping and raw exception reference, leave the originating
  `except` block, and only then raise the fresh error. The raised error must have
  `__cause__ is None`, `__context__ is None`, no raw request or secret-bearing
  attributes, and no secret string in its traceback locals. Callback and invalid
  header failures become non-retryable `ProviderAuthenticationError` instances;
  actual request failures retain current normalized retry behavior.
- The Azure token callback remains owned by `AsyncAzureOpenAI` and continues to
  refresh according to the SDK contract. Do not call it from package code.

### Secret Classification

Extend generic redaction so case and hyphen/underscore variants of
`subscription-key` and `ocp-apim-subscription-key` are recognized in mappings,
assigned text, escaped text, and URL query keys. This is generic defensive
coverage; public documentation and tests must use synthetic names and values.

## Dependency Graph

| Step | Depends on | Enables |
| --- | --- | --- |
| 1 | None | 2 |
| 2 | 1 | 3, 4, 5 |
| 3 | 2 | 5, 6 |
| 4 | 2 | 5, 6 |
| 5 | 2, 3, 4 | 6, 7 |
| 6 | 3, 4, 5 | 7 |
| 7 | 6 | Handoff |

## Phase 1: Security Primitives

### 1. Extend Generic Secret Redaction

- **Requirements**: R6, R7
- **Files**: `src/survey_scribe/errors.py`, `tests/unit/test_errors.py`
- **Details**: Add subscription-key spellings to the existing sensitive query
  set and text/mapping key patterns. Keep error messages fixed and avoid adding
  mAI-specific endpoint or credential examples. Ensure longer key names are
  matched before generic `key` forms so partial matching cannot leave a value.
- **Test Scenarios**:
  - Happy path: mapping keys and assigned strings redact synthetic subscription
    key values regardless of case or hyphen/underscore spelling.
  - Edge case: quoted, JSON-escaped, query-string, and nested exception forms
    redact the complete value.
  - Error path: nearby non-secret metadata such as `subscription-name` remains
    visible and unchanged.
- **Tests**: `UV_OFFLINE=1 uv run --no-sync pytest tests/unit/test_errors.py tests/unit/test_artifacts.py`
- **Acceptance criteria**: All new synthetic values are absent from rendered
  output, current redaction behavior remains green, and no public fixture uses a
  real credential or endpoint.

## Phase 2: Azure Adapter Integration

### 2. Add And Validate Adapter-Only Header Inputs

- **Requirements**: R1, R2, R3, R4, R5, R6
- **Files**: `src/survey_scribe/providers/azure.py`,
  `tests/contract/providers/test_provider_adapters.py`
- **Details**: Add the approved keyword-only constructor arguments and private
  helpers that implement every Header Rule. Validate and detach static metadata,
  reject sensitive static names through `is_sensitive_key()`, validate and freeze
  required names, retain only the sensitive callback, and leave the public
  facade/configuration path unchanged. Fixed validation messages identify only
  the failed rule and never echo a supplied name or value. Do not expose header
  values through a property or custom `repr`.
- **Test Scenarios**:
  - Happy path: existing API-key and token-callback construction remains valid;
    valid mixed-case static metadata is copied without mutation.
  - Edge case: mutation of the caller mapping has no effect; a valid non-string
    collection of required names is frozen; `completion`-only construction can
    exercise validation without SDK imports.
  - Error path: API key plus token callback remains invalid; bare string/bytes or
    duplicate required names fail; empty or invalid names, non-string or
    non-ASCII values, leading/trailing spaces, `0x00`-`0x1F`/`0x7F` controls,
    every reserved name, and a recognized sensitive static name fail with fixed
    safe messages.
- **Tests**: `UV_OFFLINE=1 uv run --no-sync pytest tests/contract/providers/test_provider_adapters.py tests/unit/test_config.py tests/cli/test_configuration.py`
- **Acceptance criteria**: Existing callers require no changes, direct adapter
  construction supports both header channels, every construction-time Header
  Rule is tested case-insensitively, and serialized configuration has no new
  fields.

### 3. Resolve Sensitive Headers For Each Attempt

- **Requirements**: R4, R5, R6, R8
- **Files**: `src/survey_scribe/providers/openai_compatible.py`,
  `src/survey_scribe/providers/azure.py`,
  `tests/contract/providers/test_provider_adapters.py`,
  `tests/contract/providers/test_openai_compatible.py`
- **Details**: Add a protected hook on `InstructorOpenAIProvider` that returns
  `None`. Invoke it from `generate()` inside the limiter immediately before each
  completion call. Add `extra_headers` to the completion call only for a
  non-empty mapping. Override only the hook in `AzureOpenAIProvider` to call,
  validate, merge, and check required names. Catch ordinary exceptions only;
  preserve cancellation and process-exit behavior. Classify callback/header
  failures to safe scalar state, clear secret-bearing locals and raw exception
  references, leave the originating `except` block, then raise a fresh
  non-retryable authentication error with no cause or context. This keeps retry
  ownership in one loop and avoids duplicating `generate()`.
- **Test Scenarios**:
  - Happy path: two package retries receive two independently returned sensitive
    values; static metadata appears on both.
  - Edge case: callback count remains zero through construction, representation,
    schema inspection, token estimation, and SDK creation, then increments once
    per attempt under the limiter; a generic completion with an explicit
    signature and no `**kwargs` receives the unchanged keyword set.
  - Error path: callback exceptions, invalid mappings, case-insensitive channel
    collisions, and missing dynamic requirements become safe non-retryable
    authentication errors. Assert no completion call, retry, cause, context, raw
    request/exception attribute, secret string, or secret-bearing traceback local.
    Assert `CancelledError`, `KeyboardInterrupt`, and `SystemExit` propagate.
- **Tests**: `UV_OFFLINE=1 uv run --no-sync pytest tests/contract/providers/test_provider_adapters.py tests/contract/providers/test_openai_compatible.py`
- **Acceptance criteria**: Each package-owned attempt resolves fresh sensitive
  headers exactly once, the generic provider still sends no extra headers by
  default, existing explicit completion signatures remain compatible, and
  callback failures cannot remain attached to the raised error or trigger retries.

### 4. Forward Request-Level Headers Through Instructor

- **Requirements**: R2, R3, R4, R8
- **Files**: `src/survey_scribe/providers/azure.py`,
  `tests/contract/providers/test_provider_adapters.py`,
  `tests/contract/providers/test_azure_sdk_headers.py`
- **Details**: Consume the internal `extra_headers` keyword in the Azure SDK
  completion closure and forward a detached mapping to Instructor's
  `create_with_completion()` request. Do not place sensitive headers in
  `AsyncAzureOpenAI(default_headers=...)`, because that would resolve them once
  and retain them on the long-lived client. Keep `max_retries=0` so only the
  package loop determines per-attempt refresh.
- **Test Scenarios**:
  - Happy path: a fake Azure SDK and Instructor layer receive metadata and
    sensitive headers at request level while primary auth remains in the SDK
    client arguments.
  - Edge case: an empty mapping omits `extra_headers` and does not change existing
    request shape or response normalization.
  - Error path: no secret header appears in provider properties, `repr`, raised
    error attributes, cause/context, or traceback locals after a simulated SDK
    failure.
- **Tests**: `UV_OFFLINE=1 uv run --no-sync pytest tests/contract/providers/test_provider_adapters.py`
- **Acceptance criteria**: Header values exist only in the active request call,
  direct Foundry key/token behavior is unchanged, and SDK retries remain disabled.

### 5. Verify The Installed SDK Request Path Offline

- **Requirements**: R3, R4, R7, R8
- **Files**: `tests/contract/providers/test_azure_sdk_headers.py`
- **Details**: Add one dependency-level contract test using the locked installed
  OpenAI and Instructor packages with an `httpx.MockTransport` or equivalent
  in-process transport injection. Monkeypatch only the Azure client constructor
  with a wrapper that delegates to the installed `openai.AsyncAzureOpenAI` while
  adding an `httpx.AsyncClient(transport=httpx.MockTransport(...))`; use the real
  Instructor patch and request machinery. Drive that path far enough to capture
  the final HTTP request, return a synthetic strict tool-call response, and assert
  that request-level extra headers reached the HTTP request. No DNS, socket,
  credential acquisition, or live endpoint is allowed. If the locked public SDK
  does not expose this safe transport injection point, stop under the plan
  blocked-stop rule rather than replacing this test with an untyped fake.
- **Test Scenarios**:
  - Happy path: static and fresh sensitive headers appear on the captured HTTP
    request, and the synthetic strict response validates.
  - Edge case: primary Azure auth remains SDK-owned and package retries remain
    disabled.
  - Error path: the transport asserts if any external network path is attempted.
- **Tests**: `UV_OFFLINE=1 uv run --no-sync pytest --disable-socket tests/contract/providers/test_azure_sdk_headers.py`
- **Acceptance criteria**: The locked real SDK pair accepts and forwards
  `extra_headers` to an in-process HTTP request with zero network access.

## Phase 3: Compatibility Evidence And Documentation

### 6. Complete Offline Compatibility And Boundary Tests

- **Requirements**: R1, R6, R7, R8, R10
- **Files**: `tests/contract/providers/test_provider_adapters.py`,
  `tests/contract/providers/test_import_boundaries.py`,
  `tests/architecture/test_runtime_boundaries.py`
- **Details**: Add synthetic direct-Foundry and gateway-style compositions. The
  Foundry case uses primary key or token auth with no auxiliary key. The gateway
  case uses a token callback, metadata headers, and a synthetic auxiliary-key
  callback. Extend AST import checks to reject `itsai` and `azure.identity` from
  core runtime modules. Add a `tomllib` metadata assertion that normalized names
  in `[project].dependencies` and every `[project.optional-dependencies]` group
  exclude `azure-identity`, `itsai-platform`, and other private integration
  packages. Add a source-structure assertion that no `mai_factory` provider
  module, preset, or facade provider value exists. `pyproject.toml` and `uv.lock`
  are evidence inputs, not modified files. Do not add a live test to the default
  suite.
- **Test Scenarios**:
  - Happy path: both compositions return a validated synthetic Pydantic output.
  - Edge case: close behavior and normalized usage/attempt counts remain
    unchanged.
  - Error path: missing required gateway metadata fails before completion and
    without a network attempt.
- **Tests**: `UV_OFFLINE=1 uv run --no-sync pytest tests/contract/providers tests/architecture/test_runtime_boundaries.py tests/unit/test_config.py tests/cli/test_configuration.py`
- **Acceptance criteria**: Offline tests prove both configurations through the
  same Azure adapter; there is no `mai_factory` provider, no Responses adapter,
  no credential discovery, no new dependency, and no live-call requirement.

### 7. Document Generic Gateway Composition And Run Final Gates

- **Requirements**: R7, R8, R9, R10
- **Files**: `docs/reference/providers.md`, `docs/guides/security.md`,
  `tests/docs/test_documentation.py`, `CHANGELOG.md`
- **Details**: Document direct adapter injection with a placeholder HTTPS
  endpoint, placeholder deployment/API version, token callback, static metadata,
  sensitive-header callback, and required-name set. The sensitive callback reads
  from a host-owned environment variable or secret provider; public examples do
  not hard-code even a placeholder key value. State that callbacks are bounded
  synchronous functions resolved per attempt, values are never serialized,
  applications own credential acquisition, and gateway route identity does not
  prove an exact backend. Add a focused documentation policy test that rejects
  institution-specific product/package/credential-acquisition labels and internal
  URLs in the changed public pages while permitting generic Azure/APIM protocol
  terms. Add an `[Unreleased]` changelog entry for Azure request-level gateway
  headers. Link existing configuration and security guidance. Do not publish
  exact internal endpoints, scopes, contacts, environment names, package indexes,
  or private package setup. The committed deny pattern for only these two public
  pages is case-insensitive and contains safe labels, not private values:
  `worldbank`, `worldbankgroup`, `mAI Factory`, `DesktopToken`, `itsai`,
  `artifactory`, `service-now`, `Ocp-Apim-Subscription-Key`, and an OAuth scope
  suffix `.default`. The test reports only the page and line number, not matched
  text, so an accidental value is not copied into test output.
- **Test Scenarios**:
  - Happy path: strict MkDocs build accepts the new API example and links.
  - Edge case: example imports only public Survey Scribe APIs, uses invented
    `X-Synthetic-*` metadata names, and obtains secret values at runtime.
  - Error path: the committed documentation policy test rejects internal URLs and
    private integration labels without reading or printing a private denylist.
- **Tests**:
  - `UV_OFFLINE=1 uv run --no-sync ruff check .`
  - `UV_OFFLINE=1 uv run --no-sync ruff format --check .`
  - `UV_OFFLINE=1 uv run --no-sync pyright`
  - `UV_OFFLINE=1 uv run --no-sync pytest --allow-hosts=127.0.0.1,::1 --allow-unix-socket tests --ignore=tests/browser --ignore=tests/docs --ignore=tests/package --cov=survey_scribe --cov-branch --cov-report=term-missing`
  - `UV_OFFLINE=1 uv run --no-sync python scripts/generate_docs_reference.py --check`
  - `UV_OFFLINE=1 uv run --no-sync mkdocs build --strict --clean`
  - `UV_OFFLINE=1 uv run --no-sync linkchecker --ignore-url='^https?://' site/`
  - `UV_OFFLINE=1 uv run --no-sync pytest --disable-socket tests/docs`
  - `UV_OFFLINE=1 uv build`
  - `UV_OFFLINE=1 uv run --no-sync twine check --strict dist/*.whl dist/*.tar.gz`
  - `UV_OFFLINE=1 uv run --no-sync check-wheel-contents dist/*.whl`
- **Acceptance criteria**: All required quality gates pass, coverage remains at
  or above the repository threshold, public docs contain only generic
  configuration, distributions build and pass metadata/content checks, and the
  implementation is ready for optional protected smoke testing without requiring
  it for completion. Browser checks remain a pre-merge CI gate: use current CI
  evidence, or run them locally only when Chromium is already installed. Do not
  install browser or system dependencies silently during `/cg-work`.

## Testing Strategy

- Use only synthetic endpoints, secret values, messages, and responses in
  committed tests. Generic HTTP/APIM names required to test redaction and
  reserved-name behavior are allowed. Do not use internal mAI-specific names.
  Composition examples use invented `X-Synthetic-*` metadata names.
- Keep unit tests focused on generic redaction. Keep provider contract tests
  focused on constructor compatibility, callback timing, retries, validation,
  SDK request forwarding, and normalized failures.
- Use fake SDK modules and injected completions; default tests must not contact a
  provider, acquire credentials, or import a private SDK.
- Preserve the existing CI matrix for Linux, macOS, and Windows on Python 3.11,
  3.12, and 3.13. Do not add a Python 3.12 private-package environment to public
  CI.
- Before implementation completion, run these exact isolated offline matrix
  checks. `uv --isolated` creates disposable environments outside the project and
  leaves no untracked workspace directory:
  - `UV_OFFLINE=1 uv run --isolated --offline --locked --all-extras --python 3.11 pytest --disable-socket tests/contract/providers tests/unit/test_errors.py tests/architecture/test_runtime_boundaries.py`
  - `UV_OFFLINE=1 uv run --isolated --offline --locked --all-extras --python 3.12 pytest --disable-socket tests/contract/providers tests/unit/test_errors.py tests/architecture/test_runtime_boundaries.py`
  - `UV_OFFLINE=1 uv run --isolated --offline --locked --all-extras --python 3.13 pytest --disable-socket tests/contract/providers tests/unit/test_errors.py tests/architecture/test_runtime_boundaries.py`
  If an interpreter or locked artifact is absent from the local cache, this is a
  blocked required-evidence item; do not enable network access implicitly. The
  full operating-system and browser matrix remains a required pre-merge CI gate,
  not a `/cg-work` completion gate.
- An optional protected smoke may test one direct Foundry configuration and one
  authorized mAI Factory configuration with synthetic questionnaire content. It
  must record only sanitized status, route alias, SDK version, schema digest, and
  normalized usage. It must not record headers, tokens, prompts, raw responses,
  exact private endpoints, or restricted questionnaires.

## Documentation Checklist

- [ ] `docs/reference/providers.md` shows adapter-only generic gateway setup.
- [ ] `docs/guides/security.md` explains static metadata versus secret callbacks.
- [ ] Examples use placeholders and read secrets from a host-owned runtime source.
- [ ] No exact mAI Factory endpoint, OAuth scope, contact, environment name,
      private index, package instruction, or model recommendation is published.
- [ ] Direct Foundry and gateway access are described as configurations of the
      Azure adapter, not separate Survey Scribe providers.
- [ ] Responses and health-check support are not claimed.
- [ ] Package publication remains described as subject to legal approval.
- [ ] `CHANGELOG.md` records the new public Azure constructor capability under
      `[Unreleased]`.

## Risks & Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Callback values leak through validation or SDK errors | Credential exposure | Classify outside originating exception handlers, clear transient locals, raise detached fixed errors, expand generic redaction, and inspect traceback locals in negative-leak tests |
| Sensitive header is resolved only once | Expired key on retries | Resolve inside the package-owned attempt loop and disable SDK retries |
| Secret is placed in static metadata | Long-lived credential retention | Reject names recognized by `is_sensitive_key()` and direct callers to the sensitive callback |
| Header injection permits auth or HTTP framing override | Request smuggling or credential confusion | ASCII token/value validation and a complete fixed set of auth, proxy-auth, and hop-by-hop reserved names |
| Case variants bypass collision checks | Ambiguous headers | Compare all names with `casefold()` and reject duplicates across channels |
| Shared OpenAI provider behavior regresses | Other provider failures | Protected hook returns `None`, omits the new keyword when empty, and is tested with an explicit existing completion signature |
| Synchronous secret callback blocks the event loop | Reduced concurrency | Document the callback as bounded and non-blocking; keep async or network callbacks out of scope |
| mAI policy changes | Public package churn | Keep exact institutional profiles outside the package and caller-supplied |
| Azure-compatible route lacks strict tool support | Extraction failure | Require administrator-owned capability evidence and optional protected smoke; do not infer support from endpoint reachability |
| Public package publication is mistaken for provider access | User confusion | Document that installation is public but endpoint authorization is caller-owned and separately governed |

## Out of Scope

- A public `mai_factory` provider name or environment profile.
- Exact World Bank endpoints, scopes, headers, contacts, onboarding links,
  DesktopToken environment names, or private package instructions.
- `itsai-platform`, `azure-identity`, DesktopToken, Databricks, or managed-identity
  discovery in Survey Scribe.
- Responses, Batch, embeddings, DNR, translation, text-to-speech, search, Gemini,
  Bedrock, and other non-extraction transports or APIs.
- Health checks, model deployment, Foundry infrastructure, quota, networking, or
  role assignment.
- Changes to the facade configuration, CLI, TOML, or environment-variable schema.
- PyPI publication or changes to the legal publication gate.

## Completion Contract

### Outcome

`AzureOpenAIProvider` supports safe static metadata headers and refreshable
sensitive gateway headers for direct Foundry and mAI-style Azure-compatible
gateways. Existing provider behavior, secret safety, Python 3.11-3.13
compatibility, and public/private documentation boundaries remain intact.

### Verification Surface

| ID | Phase | Evidence Required | Command/Artifact | Required |
| --- | --- | --- | --- | --- |
| V1 | 1 | Subscription-key redaction tests pass | `UV_OFFLINE=1 uv run --no-sync pytest tests/unit/test_errors.py tests/unit/test_artifacts.py` | yes |
| V2 | 2 | Header validation, auth compatibility, per-attempt refresh, exception detachment, and installed SDK forwarding pass offline | `UV_OFFLINE=1 uv run --no-sync pytest --disable-socket tests/contract/providers/test_provider_adapters.py tests/contract/providers/test_openai_compatible.py tests/contract/providers/test_azure_sdk_headers.py` | yes |
| V3 | 3 | Import, dependency, facade, and configuration boundaries pass without metadata changes | `UV_OFFLINE=1 uv run --no-sync pytest tests/contract/providers/test_import_boundaries.py tests/architecture/test_runtime_boundaries.py tests/unit/test_config.py tests/cli/test_configuration.py`; verify `git diff --exit-code -- pyproject.toml uv.lock` | yes |
| V4 | 3 | Public docs use generic placeholders and pass committed policy checks | `UV_OFFLINE=1 uv run --no-sync pytest --disable-socket tests/docs`; `UV_OFFLINE=1 uv run --no-sync python scripts/generate_docs_reference.py --check`; `UV_OFFLINE=1 uv run --no-sync mkdocs build --strict --clean`; `UV_OFFLINE=1 uv run --no-sync linkchecker --ignore-url='^https?://' site/` | yes |
| V5 | final | Source, offline test, documentation, and distribution gates pass | Exact `UV_OFFLINE=1 uv run --no-sync ...` and `UV_OFFLINE=1 uv build` commands from Step 7 | yes |
| V6 | final | Focused provider/security/architecture suite passes under Python 3.11, 3.12, and 3.13 | Exact disposable `uv run --isolated --offline --locked --all-extras --python <version>` commands in Testing Strategy | yes |
| V7 | final | Optional protected Foundry/mAI smoke records sanitized evidence | Protected smoke report outside public source artifacts | no |
| V8 | final | Full operating-system matrix, browser checks, and package artifact tests pass before merge | Existing GitHub CI and docs workflow evidence; local browser execution only when Chromium is already installed | no |

### Constraints

| ID | Phase | Constraint | Check |
| --- | --- | --- | --- |
| C1 | 1 | No secret value enters errors, logs, serialization, diagnostics, exception chains/tracebacks, or object representations | Redaction, exception-detachment, and negative-leak tests |
| C2 | 2 | No callback runs during import, construction, schema inspection, token estimation, or SDK client creation | Offline callback call-count tests |
| C3 | 2 | Primary authentication remains exactly one of API key or token callback | Existing and extended credential tests |
| C4 | 3 | No `mai_factory` provider, Responses transport, config/CLI fields, or private dependency is added | Diff, AST import checks, and config serialization tests |
| C5 | final | Python remains `>=3.11,<3.14`; no new runtime dependency is introduced | TOML dependency assertion, `git diff --exit-code -- pyproject.toml uv.lock`, and focused interpreter matrix |
| C6 | final | No live provider call is required to complete implementation | Required evidence excludes V7 and offline suite disables external sockets |

### Boundaries

- Allowed: Azure adapter and shared retry hook, generic redaction helpers,
  focused contract/security tests, and generic public provider/security docs.
- Out of scope: exact mAI configuration, private profiles, credential discovery,
  Responses, health checks, deployment infrastructure, and non-extraction APIs.

### Iteration Policy

1. Preserve the existing facade and serialized configuration.
2. Implement the smallest generic adapter hook and reuse the current retry loop.
3. Use fixed safe errors and never retain callback-returned secret values.
4. Do not infer or publish unresolved private mAI contracts.
5. If implementation requires a scope or API deviation, follow
   `deviation-policy: ask` and pause before the change.

### Blocked-Stop Conditions

- The OpenAI/Instructor request path cannot inject per-request headers without
  changing extraction semantics or enabling SDK-owned retries.
- Required tests reveal that callback or SDK failures can expose a secret value
  and the leak cannot be closed within the allowed files.
- Completion requires an internal operational value, a new dependency, a new
  provider identity, a Responses transport, or a facade/configuration change.
- A required verification cannot run through the safe runner or remains failed
  after allowed recovery attempts.
- A required deviation needs approval under `deviation-policy: ask` and approval
  is unavailable.
