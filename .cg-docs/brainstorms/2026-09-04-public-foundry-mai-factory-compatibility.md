---
date: 2026-09-04
title: "Public Foundry and mAI Factory Compatibility"
status: decided
scope: "Deep"
artifact-schema-version: 1
chosen-approach: "Generic Azure adapter with private mAI Factory configuration"
tags: [providers, azure, foundry, mai-factory, security, public-package]
---

# Public Foundry and mAI Factory Compatibility

## Context

Survey Scribe is a public, provider-neutral Python package for extracting local
survey questionnaires into SVIS. The immediate goal is to let the same package
work with direct Microsoft Foundry model access and World Bank mAI Factory model
access without adding institutional deployment or credential-discovery logic to
the package.

The project charter requires Python 3.11-3.13 compatibility, credential-safe
configuration, optional provider dependencies, and legal approval before package
publication. The existing `StructuredProvider` boundary and Azure adapter already
provide most of the required architecture.

Two local mAI Factory references were reviewed as time-sensitive evidence. They
conflict on base URLs, route paths, required headers, DesktopToken environment
names, request formats, model names, and Databricks support. Indexed intranet
documentation was unavailable. Disputed operational details therefore remain
unresolved and are not copied into this public artifact.

## Requirements

### Goals

- Make Survey Scribe publicly installable and usable by anyone with access to a
  compatible model endpoint.
- Use one provider-neutral extraction API for direct Foundry and mAI Factory.
- Reuse the existing Azure structured provider for questionnaire extraction.
- Support either an Azure API key or a refreshable token callback as primary
  authentication.
- Support validated non-secret gateway metadata headers and a separate
  refreshable sensitive-header callback for an auxiliary gateway key.
- Keep endpoint, deployment or model name, API version, credentials, and gateway
  headers caller-supplied.
- Keep credentials out of serialization, representations, logs, diagnostics,
  exceptions, artifacts, and files.
- Preserve the core Python 3.11-3.13 support window.
- Keep `itsai-platform`, Azure Identity, DesktopToken, and managed-environment
  credential discovery outside the core package.
- Use offline contract tests and optional protected live smoke tests with
  synthetic inputs.

### Access Boundaries

- **Direct Foundry:** The caller supplies an Azure API key or an Entra token
  callback. Survey Scribe does not deploy models or configure Azure resources.
- **mAI Factory Desktop:** A private integration layer wraps DesktopToken as the
  existing token-callback interface.
- **mAI Factory Application:** A private integration layer supplies the Azure
  token callback and auxiliary gateway-key callback.
- **Databricks:** The managed runtime supplies a token callback or a complete
  `StructuredProvider`. Survey Scribe does not discover workspace credentials.
- **Foundry managed identity:** The host supplies a token callback. Foundry
  infrastructure remains outside Survey Scribe.

### Non-Goals

- A publicly named `mai_factory` provider.
- Hard-coded mAI Factory endpoints, scopes, headers, environment names, contacts,
  package-index instructions, or model aliases.
- A Responses API transport in the first iteration.
- Provider deployment, onboarding, health-check orchestration, or credential
  acquisition.
- Databricks credential discovery.
- DNR, translation, text-to-speech, embeddings, search, Batch, Gemini, Bedrock,
  or other non-extraction APIs.
- Exact-backend quality claims for a dynamic gateway route.

## Evidence And Unresolved Contracts

| Topic | Evidence | Decision |
| --- | --- | --- |
| Azure-compatible model route | One local `/v2/` route worked with `gpt-4.1` | Treat as route-specific evidence, not a public default |
| Responses route | One tested route returned 404 | Do not implement now |
| Health route | Observed behavior did not match the documented success response | Do not use health as a core readiness gate |
| DesktopToken | Authentication worked locally | Keep integration private and inject a callback |
| `itsai-platform` | Local evidence indicates Python 3.12 or newer | Keep it out of core dependencies and test it separately |
| Exact endpoints and scopes | Local references conflict and authoritative indexed documentation was unavailable | Keep unresolved and private |
| Required headers | Local references disagree on names and applicability | Make core header support generic; define exact profiles privately |
| Current model aliases | Local references list conflicting generations | Require caller configuration; do not hard-code aliases |

## Approaches Considered

### Approach 1: Generic Azure Adapter With Private mAI Factory Configuration

Enhance the existing public Azure adapter with two typed header channels. Keep
all exact mAI Factory environment values and credential composition in an
approved private integration layer.

**Pros:**

- Reuses the existing provider port, Azure SDK path, strict-schema behavior,
  retry policy, lifecycle, and normalized metadata.
- Supports direct Foundry and institutional gateways without adding a new public
  provider identity.
- Adds no core dependency on private packages or Azure Identity.
- Minimizes public API and documentation maintenance.
- Keeps volatile institutional policy outside package releases.

**Cons:**

- Requires careful header validation and redaction changes.
- Requires a small private profile or application bootstrap layer.
- Does not support an unverified Responses-only route.

**Effort:** Medium.

### Approach 2: Publicly Named mAI Factory Provider

Add `mai_factory` as a public provider with environment profiles, credential
rules, required headers, and documented model routes.

**Pros:**

- Provides a recognizable provider name for Bank users.
- Could reduce setup code if all institutional contracts were stable and public.

**Cons:**

- Converts changing internal endpoints, scopes, headers, model aliases, and
  onboarding rules into a supported public API.
- Requires publication approval for internal operational details.
- Adds maintenance that does not improve questionnaire extraction.
- Risks coupling public package releases to gateway policy changes.
- Is not useful to public users who do not have mAI Factory access.

**Effort:** Large and ongoing.

### Approach 3: Private StructuredProvider Only

Leave Survey Scribe unchanged and implement a complete mAI Factory provider in a
private package or application.

**Pros:**

- No public core changes.
- Strong institutional isolation.

**Cons:**

- Duplicates security-sensitive retry, schema, parsing, metadata, and lifecycle
  behavior already implemented by Survey Scribe.
- Can drift from direct Foundry support.
- Creates more long-term maintenance than a small generic adapter extension.

**Effort:** Medium initially, with higher long-term maintenance.

### Approach 4: Azure And Responses Transports

Enhance the Azure adapter and add a separate Responses provider immediately.

**Pros:**

- Covers two possible mAI Factory route families.

**Cons:**

- The Responses route and wire contract are unresolved.
- Adds request, structured-output, response-parsing, error, and test complexity
  without evidence that extraction requires it.
- Makes uncertain platform behavior a release concern.

**Effort:** Large.

## Decision

Choose **Approach 1: Generic Azure Adapter With Private mAI Factory
Configuration**.

The public package will retain `AzureOpenAIProvider` as the provider identity.
Direct Foundry and mAI Factory are configurations of this transport, not separate
product providers. The adapter will gain only the generic capabilities needed to
compose safe gateway requests:

1. Validated non-secret metadata headers.
2. A separate sensitive-header callback evaluated for each outbound attempt.
3. Required-header validation configured by the caller.
4. Reserved-header protection for authentication and transport-owned fields.
5. Redaction coverage for auxiliary subscription keys and callback results.

The public facade, TOML schema, CLI, and environment-variable resolution will not
gain mAI-specific fields in the first iteration. Applications will construct and
inject the configured provider through the existing `StructuredProvider`
boundary.

Do not implement a Responses adapter now. Reconsider it only if the
Azure-compatible route cannot satisfy extraction and all three evidence gates
pass: authoritative documentation, sanitized offline contract fixtures, and one
approved protected live smoke for the exact route and model.

## Risks

- Gateway header callbacks can expose secrets if validation or third-party
  exceptions include raw values.
- A working route can still reject the strict Instructor tool schema for another
  model alias.
- Dynamic gateway routing can make returned backend identity differ from the
  configured route.
- Public documentation can accidentally expose internal operational details.
- Package publication remains blocked until the approval in
  `docs/legal-disposition.md` changes.

## Next Steps

1. Plan the smallest Azure adapter extension, including exact constructor types,
   header validation, reserved names, callback timing, and redaction behavior.
2. Add offline contract and security tests across Python 3.11-3.13.
3. Define a private mAI Factory profile outside the public package with exact
   environment values and credential acquisition.
4. Add optional protected smoke tests for direct Foundry and mAI Factory using
   synthetic questionnaire content and no retained credentials or raw responses.
5. Document only generic gateway configuration in the public site.
6. Track package publication approval separately from technical compatibility.
