---
date: 2026-08-31
title: "Implement the Questionnaire Routing Graph"
status: completed
completed-date: 2026-09-02
scope: "Deep"
brainstorm: "../brainstorms/2026-08-31-questionnaire-routing-graph.md"
language: "Python"
estimated-effort: "large"
deviation-policy: "ask"
artifact-schema-version: 1
execution-report: "../work-reports/2026-08-31-questionnaire-routing-graph.md"
phases: 5
completed-phases: [1, 2, 3, 4, 5]
tags: [python, pydantic, llm, questionnaire, routing, graph, instructor, svis]
---

# Plan: Implement the Questionnaire Routing Graph

## Objective

Add a production-quality questionnaire routing capability that lets LLM agents
understand and validate the complete flow of a household or labor force survey.
The package will produce one versioned `RoutedSurveySVIS` artifact with
source-grounded routing evidence, a canonical directed multigraph, derived
forward and backward adjacency, activation conditions, terminal states, repeat
templates, cycles, stable diagnostics, and an auditable discrepancy review path.

Preserve the existing `SurveyVariable`, `SurveySVIS`, and legacy JSON contract
through 1.x: exact keys, nesting, JSON value types, defaults, enum values, field
order, and variable order. Whitespace is not contractual. Runtime interview
execution is not part of this plan.

## Context

The current public model stores only `skip_condition_raw`. It cannot resolve a
target, represent a default edge, distinguish routing from applicability, show
multiple incoming paths, or validate the survey as a graph. The approved
brainstorm selected an evidence-first hierarchical graph and adaptive independent
incoming-path verification.

The repository already has:

- Pydantic v2 public models in `src/survey_scribe/models/svis.py`.
- Exact field-order and fixed-clock JSON characterization tests.
- Frozen typed results, stable diagnostics, recursive redaction, normalized
  source blocks, provenance, chunking, and artifact foundations. The current
  branch includes the production-review remediation and cross-platform CI fixes
  that were pending in the original plan baseline.
- Optional locked OpenAI, Instructor, Tenacity, and tiktoken dependencies.
- An active production-package plan that keeps SVIS JSON exact through 1.x,
  separates provider SDKs from core code, and requires native XLSForm logic to
  remain deterministic.

The production-package plan creates an important compatibility constraint. This
plan must not add fields to the existing `SurveyVariable` or `SurveySVIS`
classes. It will instead add an opt-in additive extension:

- `RoutedSurveyVariable(SurveyVariable)` adds nullable `routing_node_id` so an
  unmatched legacy variable remains present and review-visible.
- `RoutedSurveySVIS(SurveySVIS)` uses routed variables and adds
  `routing_schema_version` plus `routing_graph`.
- A deterministic projection converts the routed model back to a semantically
  exact, ordered
  `SurveySVIS` for the legacy `<survey_id>_svis.json` artifact.
- Existing calls that produce `SurveySVIS` keep their current output and write
  behavior.

The routing core will use the production plan's `StructuredProvider.generate()`
port and normalized `ProviderResponse[T]`. Instructor remains internal to the
provider package. This plan must not create a routing-specific provider protocol,
retry envelope, client, credential path, or Instructor adapter.

### Cross-Plan Scope Approval

The user selected independent routing evidence plus discrepancy review during
the linked brainstorm and approved this plan's completion contract on
2026-08-31. This approval narrows one boundary in the active production plan:
`RoutingDiscrepancyReviewer` is permitted only for bounded, source-cited routing
discrepancies. It is not a general independent review/autofix agent, cannot use
tools, cannot silently mutate evidence, and cannot autonomously repair other
SVIS fields. This plan supersedes the production plan's review-agent exclusion
only for that named routing component.

The user's instruction to address all plan-review findings and make this plan
ready for `/cg-work` also approves bounded ownership of G3's provider slice and
G4's core XLSForm slice when they are not already implemented. G3 is limited to
the reusable `StructuredProvider` port, normalized response/capability contracts,
and the Instructor-backed OpenAI-compatible adapter required by routing. G4 is
limited to the reusable core XLSForm parsing, security, relevance, group, and
repeat semantics required by native routing. Their executed evidence can be
reused by the production-package plan, but this routing run cannot mark that
plan's full Step 5 or Step 8 complete or claim support for unimplemented
providers/XLSForm features.

Prior knowledge applied:

- Treat the brainstorm's evidence, canonical graph, and diagnostics as separate
  layers. Source: `../brainstorms/2026-08-31-questionnaire-routing-graph.md`.
- Preserve exact legacy SVIS structure and provider/source boundaries. Source:
  `2026-08-28-survey-scribe-production-package-refined.md`.
- Redact credentials and questionnaire content at every log, diagnostic,
  validation-error, cache, and sidecar boundary. Source:
  `../solutions/bugs/2026-08-28-close-credential-redaction-boundaries.md`.
- Test editable checkout, wheel, and sdist as different filesystems. Source:
  `../solutions/build-errors/2026-08-26-bound-python-package-artifacts-and-evidence.md`.

No `compound-gpid.md` or `compound-gpid.local.md` exists, so project-charter
alignment and local review settings could not be verified.

## Requirements

| ID | Requirement | Source |
|----|-------------|--------|
| R1 | Produce one versioned, LLM-readable routed SVIS artifact with survey metadata, routed variables, and a top-level directed multigraph | Brainstorm decision |
| R2 | Preserve existing `SurveyVariable`, `SurveySVIS`, public imports, keys, nesting, JSON value types, defaults, enum values, field order, and variable order through 1.x; whitespace is not contractual | Active production plan and characterization tests |
| R3 | Prefer printed item IDs and generate deterministic source-version-scoped fallback IDs without using `raw_name` as a graph key | Brainstorm identity decision |
| R4 | Represent entry, question, section, repeat-group, and terminal nodes plus parallel conditional edges | Brainstorm schema requirements |
| R5 | Represent complex conditions with a bounded typed AST, verbatim raw text, strict scalar types, and an explicit `opaque` operator | Brainstorm condition decision |
| R6 | Keep transitions separate from item or section activation conditions | Brainstorm terminology decision |
| R7 | Preserve forward, independent incoming, activation, native-parser, discrepancy, and reviewer evidence with verified source spans, confidence, and an append-only audit trail | Evidence-first decision |
| R8 | Support conditional, default, unconditional, sequential, terminal, multiple-incoming, cross-section, and unresolved routing | User request and brainstorm |
| R9 | Preserve source-supported cycles, classify repeat and correction loops, and flag inferred unsupported cycles | Brainstorm cycle policy |
| R10 | Represent household-member, consumption-item, visit, plot, and enterprise repetition as logical templates; handle at least 1,000 logical nodes without recursion failure | Household/labor survey scope |
| R11 | Provide versioned production prompts for forward, incoming/activation, and discrepancy-review tasks that treat source text as untrusted data | User request and source-security contract |
| R12 | Keep Pydantic and routing core framework-neutral; consume the production `StructuredProvider` port, with Instructor remaining internal to provider adapters | Integration decision and active production plan |
| R13 | Let native digital questionnaire adapters supply typed routing without flattening it to text or making LLM calls | Brainstorm and production XLSForm contract |
| R14 | Reconcile evidence deterministically, keep accepted edges separate from disputed candidates, derive node adjacency only from accepted edges, and emit stable graph diagnostics | Validation-first purpose and plan review QRG-PLN-005 |
| R15 | Require every reviewer correction to cite supplied evidence; never silently repair or invent disputed routing | User review objective |
| R16 | Keep all source-derived and model-generated questionnaire prose out of logs, diagnostics, sidecars, and persistent caches while allowing cited source text in the local primary routed artifact | Existing privacy/redaction boundary |
| R17 | Require deterministic mechanics evaluation on approved synthetic fixtures; treat a protected real-provider capture as optional model-quality evidence and report first-pass and post-review quality separately | Brainstorm evaluation strategy and 2026-09-01 G6 decision |
| R18 | Keep runtime interview execution, JSON Logic guarantees, runtime loop unrolling, graphical editing, and all-vendor parser delivery out of scope | Approved boundary |
| R19 | Retain Python 3.11-3.13, Ruff, Pyright, pytest, Hatchling, uv, PEP 561, and exact-artifact package testing without adding a graph runtime dependency | Existing package baseline |
| R20 | Keep G6 as a lightweight, protected, manual authorization only for an optional live test capture; absence or deferral of G6 must not block deterministic evidence, package completion, or merge readiness | 2026-09-01 user decision |
| R21 | In final production, replace per-run interactive G6 approval with administrator-owned provider, quota, secret, data-handling, and gateway policy; keep credentials outside serialized configuration and artifacts | 2026-09-01 production/testing distinction |
| R22 | Support institutional OpenAI-compatible gateways such as World Bank mAI Factory by recording the configured gateway route plus returned provider/model metadata; require a pinned backend only for exact-backend quality claims | 2026-09-01 gateway decision |

## Prerequisite Gates

Routing work depends on production foundations identified by the 2026-08-28 full
review. The current branch includes their approved remediation. Step 1 evidence
remains the authority for those gates; static inspection or a plan-status claim
alone is not sufficient.

| Gate | Required closure before | Required production findings/evidence |
|---|---|---|
| G1 Source completeness and limits | Inventory construction and every model call | Close P0.7 partial source coverage, P0.8 hard token budgeting, P0.9 lossless table representation, P0.11 complete multi-page provenance, and P1.8 source replacement race; execute source contract/integration evidence |
| G2 Artifact safety and serializer boundary | Routed artifact implementation | Close P0.3 crash consistency, P0.4 symlink/reparse escape, P0.5 lock ownership/crash recovery, P0.6 survey identity aliasing, and P1.10 generic-result serializer coupling; execute hard-process-exit, recovery, no-follow, lock, identity, and serializer-port tests |
| G3 Provider contract | Phase 3 structured extraction | Step 8 owns the required production-provider slice when it is not already complete: `StructuredProvider.generate()`, `ProviderResponse[T]`, `ModelCapabilities`, truncation, retry counts, cancellation, redaction, and provider contract tests |
| G4 Native core adapter | Final native-routing evidence V9 | Step 9 owns the required production XLSForm slice when it is not already complete: one real core adapter with relevance/repeat semantics and a versioned support matrix; a synthetic adapter alone cannot close V9 |
| G5 Coverage | Final V12 | Close production review P1.13 and pass the configured 95% branch-coverage command without lowering the threshold |
| G6 Protected test-capture authorization | Optional Phase 5 live model-quality capture only | Before any protected test call, record a human source-safety attestation, gateway route/model alias, credential environment-variable name only, request/token ceilings, temporary-output policy, and stop conditions; technical endpoint/header/SDK details are discovered by the capture preflight and secrets are never recorded |

This plan owns G1-G5 as completion gates and G6 as an action gate. If another
approved work run already satisfies a gate, this plan records the executed evidence in its own work report instead of
reimplementing it. Otherwise Step 1 implements G1/G2/G5, Step 8 implements G3,
Step 9 implements G4, and Step 11 requests G6 approval only before an optional
paid/protected capture. A deferred G6 records `not_run` model-quality evidence;
it does not block deterministic evaluation, V12, or plan completion. Historical
reviews and another plan's work report remain unchanged.

## Normative Design Contracts

These decisions are implementation authority. A change requires approval under
`deviation-policy: ask`.

### Compatibility and Artifact Contract

- Do not change `SurveyVariable.model_fields` or `SurveySVIS.model_fields`.
- Add routed subclasses in a separate module. Their inherited fields keep the
  existing meanings and JSON types.
- `RoutedSurveyVariable.routing_node_id` is a nullable canonical node ID. Many
  routed variables can link to one question node; each variable index links to
  at most one node. An unmatched variable remains in source order with
  `routing_node_id=null`, `UNLINKED_VARIABLE`, and partial status.
- `RoutedSurveySVIS.routing_schema_version` and
  `QuestionnaireRoutingGraph.schema_version` are both `Literal["1.0"]`; model
  validation requires equality. `routing_graph` and `routing_audit` are required.
- A routed artifact uses a distinct main filename such as
  `<survey_id>_routed_svis.json` inside the immutable generation.
- The stable legacy `<survey_id>_svis.json` path contains only the semantically
  exact, ordered v1
  `SurveySVIS` projection. Existing v1 writes continue to make the generation
  main and legacy projection byte-identical.
- Projection removes routed-only fields by typed reconstruction, not by an
  unvalidated dictionary deletion pipeline.
- Legacy manifests remain version 1. Routed generations use manifest version 2
  with a typed parser and migration/compatibility tests. The routed manifest
  records both equal routing schema versions, main and projection hashes,
  prompt versions, and source/model response digests. It does not contain source
  text or model responses.
- Revalidate a detached routed snapshot immediately before artifact generation.
  Publication cannot start until G2 passes. Do not persist raw prompt or response
  bodies by default.

### Identity and Inventory Contract

- Build a complete logical item inventory before final routing reconciliation.
- Keep source item ID, preserved raw reference, canonical node ID, section path,
  source order, source blocks, logical kind, repeat-group membership, and linked
  SVIS variable index as separate fields.
- Exact printed IDs are scoped by section when the source permits duplicate IDs.
- Alias resolution is deterministic and bounded to forms such as `Q12`, `12`,
  and `Question 12` within a known namespace.
- Fallback IDs hash survey ID, normalized section path, logical ordinal, and a
  normalized source-text digest. They are stable only for one source version.
- Fuzzy semantic matches can create reviewer candidates but never accepted
  targets.
- Ignore LLM-generated final IDs. Python assigns canonical node, evidence, edge,
  loop, and diagnostic IDs.
- Inventory hierarchy uses `parent_node_id` plus derived `child_node_ids`.
  Question, section, and repeat-group containment is separate from flow edges.
  The hierarchy is acyclic, each non-root node has at most one parent, each
  section/repeat group identifies one entry child, and a flow edge that targets a
  section reaches that section node before its explicit entry edge.

### Condition Contract

- Define two condition types. `ExtractedRoutingCondition` uses an
  `ItemReference` that can preserve a printed or unresolved identifier.
  `CanonicalRoutingCondition` uses only a resolved `question_node_id`.
  Reconciliation transforms extracted references into canonical references; an
  unresolved or ambiguous controlling question leaves the candidate out of the
  accepted graph.
- Supported canonical operators are `always`, `equals`, `not_equals`, `in_set`,
  `not_in_set`, `greater_than`, `greater_than_or_equal`, `less_than`,
  `less_than_or_equal`, `between`, `answered`, `not_answered`, `selected`,
  `not_selected`, `all`, `any`, `not`, and `opaque`.
- Use strict string, integer, finite float, and Boolean scalar values. Do not
  coerce `true` to `1` or numeric strings to numbers.
- Scalar, set, range, question-only, and boolean operators validate their exact
  required/null field shapes.
- `all` and `any` require at least two children; `not` requires one.
- Maximum accepted AST depth is 6 and maximum nodes per condition is 100.
- Every condition preserves `raw_text`. `opaque` requires non-empty raw text and
  cannot be used as executable proof of branch coverage.
- A default edge has no condition and is evaluated only if no conditional edge
  applies. Each source node has at most one default edge.
- Edge priority is set only when source order explicitly defines ordered routing.
- Native evidence can also carry `NativeExpression(language, version,
  exact_expression, parsed_references, canonical_projection)`. Unsupported
  native functions or arithmetic keep this typed payload and use an `opaque`
  canonical projection without any LLM reconstruction. A versioned XLSForm
  support matrix defines which relevance/repeat operators project exactly;
  constraints, calculations, and choice filters are preserved but are not
  automatically treated as flow edges.

### Evidence and Reconciliation Contract

- Extraction responses use a discriminated `evidence_type` field so transition
  and activation records cannot validate as the wrong union member.
- Every source span names a normalized block, includes physical provenance, and
  includes a bounded source quote. Python verifies the normalized quote against
  the named block before evidence can support an accepted edge.
- Pass A examines all logical items and extracts outgoing routing.
- Pass B receives no Pass A output. It runs only for branch targets,
  cross-section paths, unresolved or ambiguous targets, opaque conditions,
  cycles, low-confidence evidence, and unusual in/out degree.
- Incoming evidence is still expressed in actual flow direction:
  predecessor -> target.
- Exact compatible forward/incoming/native evidence is merged by normalized
  source, target, kind, and condition identity while preserving all evidence
  IDs.
- Explicit printed routing outranks sequential inference. Native typed routing
  has the same source-grounded rank as explicit printed routing.
- One explicit forward claim can be accepted without Pass B when it has a
  verified source span and unambiguous target. Pass B disagreement changes the
  edge to review state; it does not erase evidence.
- Incoming-only or fuzzy-target claims require review unless native typed source
  semantics make them deterministic.
- Reviewer actions are `confirm_candidate`, `replace_candidate`,
  `reject_candidate`, and `unresolved`. Corrections append decisions and never
  mutate the original evidence.
- Unresolved review creates `needs_human_review` state and a stable diagnostic.
- The primary routed artifact contains append-only `candidate_edges`,
  `discrepancies`, and `review_decisions`. Each decision records candidate IDs,
  evidence IDs, cited spans, action, replacement content when applicable,
  rationale, confidence, human-review flag, prompt version/hash, provider
  response digest, and predecessor decision ID when superseding a prior review.

### Canonical Graph Contract

- The accepted edge list is authoritative. The graph is a directed multigraph.
  Disputed, rejected, ambiguous, and unresolved alternatives exist only in
  `candidate_edges` and the audit trail.
- `next_node_ids`, `previous_node_ids`, `outgoing_edge_ids`, and
  `incoming_edge_ids` are materialized from edges in stable source/edge order.
- All edge endpoints exist. Entry nodes exist. Terminal nodes have no outgoing
  edges.
- Final model validation catches structural corruption. Semantic graph analysis
  emits diagnostics rather than making all warnings un-serializable.
- Structural errors include duplicate IDs, dangling accepted edges, impossible
  node shapes, and adjacency mismatch.
- Review warnings include ambiguous targets, uncovered opaque branches,
  unsupported inferred cycles, activation/routing disagreement, and no proven
  terminal path.
- Flow edge `kind` is exactly one of `conditional`, `default`, `unconditional`,
  or `sequential`. There is no `loop` edge kind and no independent `is_default`
  Boolean. Loop membership is topological metadata derived from accepted edges
  and declared repeat semantics.
- Strongly connected components use an iterative algorithm. Do not use recursive
  DFS for questionnaire-scale graphs.
- Create one `LoopDefinition` per declared logical repeat or supported strongly
  connected component region, with member nodes, entry, member, return, and exit
  edges. Never enumerate all simple cycles. Deterministically assign overlapping
  declared loops by source nesting; correction-return edges can belong to an SCC
  region without becoming a repeat template. An inferred cycle stays in the
  candidate/audit layer until resolved.

### Structured Output and Security Contract

- The LLM returns extraction evidence or reviewer decisions, not the final graph.
- Prompts use fixed system instructions plus separate task messages and explicit
  untrusted-data delimiters.
- Source questionnaire instructions cannot alter the extraction task, request
  tools, or change output format.
- The provider receives no tools. Schema retries address local response
  validation only, not global graph defects.
- Prompt constants have explicit semantic versions. Each request records prompt
  version and a digest, not prompt/source bodies, in diagnostics and manifests.
- The routing core imports no Instructor, OpenAI, LangChain, or provider SDK
  type. It consumes only the production `StructuredProvider` port after G3.
- Canonical Pydantic schemas and provider request schemas are separate. For each
  named provider/model capability row, record the canonical response-model hash,
  adapter-transformed request-schema hash, strict-schema support, and tested SDK
  version. Keep one protected optional live smoke for provider schema drift.
- One shared concurrency limiter covers base extraction, Pass A, Pass B,
  reviewer calls, and transport/validation retries. `CancelledError`,
  `KeyboardInterrupt`, and `SystemExit` propagate and publish no artifact.
- Exceptions use fixed safe templates that never interpolate request, response,
  source-derived fields, reviewer prose, native expressions, or nested provider
  text. When value redaction is still needed, collect every exact source-derived
  string at the request boundary, including question text, labels, raw
  references, notes, ambiguity text, source quotes, native expressions, and
  reviewer content.
- Questionnaire source quotes can appear in the local primary routed artifact.
  They cannot appear in logs, sidecars, cache keys, exception text, or telemetry.

### G6 Test Capture Versus Final Production Contract

G6 governs one optional protected test action. It is not the production runtime
configuration model and is not an approval that every production caller must
repeat. The package must keep these two concerns separate.

#### Testing-Phase G6 Requirements

- G6 is required only before a real provider receives a sanitized questionnaire
  during an optional model-quality smoke or benchmark capture. Unit, contract,
  integration, security, scale, package, and deterministic mechanics evaluation
  use fakes, recorded structured outputs, native routes, or synthetic sources and
  do not require G6.
- The human supplies only decisions the software cannot infer: confirmation that
  the source is sanitized and authorized for the institutional gateway, the
  intended gateway route/model alias, request and token ceilings, and the raw-
  output handling rule. Exact cost is optional when the gateway does not expose
  cost; request and token ceilings remain mandatory.
- The capture preflight discovers technical API details such as endpoint shape,
  authentication-header name, API version, SDK version, strict-schema support,
  and returned metadata. It records no credential value and asks for another
  decision only if the discovered route or behavior conflicts with the approved
  summary.
- An OpenAI-compatible institutional gateway such as World Bank mAI Factory is
  identified as the provider boundary. Record its configured route/model alias
  and the provider/model metadata returned by each call. A pinned backend is
  required only when the report makes a claim about one exact Azure OpenAI,
  Vertex AI, or Bedrock model. An unpinned route is reported only as a gateway-
  route benchmark.

#### Testing-Phase G6 Configuration

The protected capture runner uses an ephemeral, non-serialized configuration
with these fields:

- authorized source path and computed SHA-256;
- human source-safety and rights attestation;
- gateway provider name and route/model alias;
- credential environment-variable name, never its value;
- maximum requests, maximum input tokens, and maximum output tokens;
- optional maximum cost when reliable cost metadata exists;
- temporary private capture location or in-memory-only mode;
- raw-output deletion rule and fixed stop conditions.

The runner first emits a sanitized dry-run summary containing only source digest,
gateway/route identity, limits, output policy, and discovered capability status.
One explicit `APPROVE G6 CAPTURE` confirmation authorizes only that summary.

#### Testing-Phase Expected Behavior

- No call occurs before the dry-run summary is approved.
- The runner stops if the source digest, gateway route, strict-schema support,
  request/token ceilings, or output policy changes.
- The API key is read only from the approved environment variable. It never
  appears in command arguments, prompts, logs, reports, exceptions, fixtures,
  artifacts, or Git history.
- Raw questionnaire text, prompts, and provider responses remain temporary and
  are deleted after sanitized metrics and digests are produced. They are never
  committed. Gateway-side retention follows the approved institutional policy
  and is reported as policy context rather than controlled by this package.
- If G6 is declined, unavailable, or a protected capture fails, record the live
  model-quality result as deferred or failed without changing deterministic
  correctness evidence or blocking package completion. Do not claim real mAI
  Factory or exact-model quality when no passing capture exists.

#### Final Production Requirements And Configuration

- Production does not use interactive G6 approval for every request. A deployment
  administrator configures `SurveyScribeConfig`, the selected
  `StructuredProvider`, gateway policy, and organizational data-handling policy
  before the service accepts work.
- Package configuration contains non-secret provider name, model or gateway route
  alias, base URL, API version when needed, generation/retry settings, per-request
  token limits, and concurrency. Credentials come from one approved secret source
  such as an environment variable, bearer-token callback, or platform secret
  store and remain excluded from serialization and representation.
- Aggregate request, token, cost, rate, data-classification, and gateway-retention
  policy can be enforced by the hosting service or institutional gateway. This
  package must enforce its configured per-request/schema/concurrency bounds and
  must not claim control over APIM or backend retention that it cannot verify.
- Production startup or provider construction validates that one credential form
  is available, the configured route can represent the strict request schema,
  and required limits are valid before source content is sent.

#### Final Production Expected Behavior

- Authorized production requests run without a manual capture prompt and return
  normal success, partial, or failed routing results under the existing outcome
  contract.
- Every provider call records non-sensitive configured provider/route identity,
  returned provider/model identity when available, normalized token usage,
  prompt/schema hashes, attempts, and response digest. Dynamic gateway routing is
  visible in metadata and never presented as a pinned-model guarantee.
- Application logs, diagnostics, sidecars, and manifests remain content-safe.
  The application keeps no persistent raw prompt/response cache by default.
- Source authorization and gateway retention remain deployment-policy
  responsibilities. Documentation must state these responsibilities and must not
  imply that the testing G6 approval configures or certifies production.

### Public Routing API Contract

Keep routing separate from the production plan's SVIS-only `SurveyScribe` API:

```python
class QuestionnaireRouter:
    def __init__(
        self,
        provider: StructuredProvider | None,
        *,
        config: RoutingConfig | None = None,
        sources: SourceRegistry | None = None,
    ) -> None: ...

    def route(
        self,
        source: LocalSource | SourceBundle,
        svis: SurveySVIS,
        *,
        source_binding: RoutingSourceBinding,
    ) -> ExtractionResult[RoutedSurveySVIS]: ...

    async def aroute(
        self,
        source: LocalSource | SourceBundle,
        svis: SurveySVIS,
        *,
        source_binding: RoutingSourceBinding,
    ) -> ExtractionResult[RoutedSurveySVIS]: ...
```

- The caller supplies an existing SVIS result and the `RoutingSourceBinding`
  created from the exact validated private source snapshot used for that
  extraction. The binding contains survey ID, source name, media type, snapshot
  SHA-256, and source-conversion schema version.
- At method entry, rebuild a detached `SurveySVIS` from JSON-mode data, normalize
  the current source through its bounded private snapshot, and compare survey ID,
  source filename, source format/media type, source digest, and binding version.
  Return failed `ROUTING_SOURCE_MISMATCH` before any provider call when a value
  differs. Caller mutation after entry cannot change the detached snapshot.
- Routing does not repeat general variable extraction or add methods to
  `SurveyScribe` in this plan.
- `provider=None` is valid only when the selected native adapter supplies all
  required routing semantics. A document source without native routing and no
  provider returns a failed result with `ROUTING_PROVIDER_REQUIRED`.
- The router does not own or close the injected provider or source registry.
- `route()` rejects use inside a running event loop. `aroute()` is authoritative.
- `QuestionnaireRouter` is exported from `survey_scribe.routing`; routed model
  classes are exported from `survey_scribe.models` and the stable top-level
  package only after exact-wheel tests pass.

### Routing Limits and Risk Selection

`RoutingConfig` uses these fixed defaults. A change to a default is a public
policy deviation under `deviation-policy: ask`.

| Field | Default | Rule |
|---|---:|---|
| `max_source_quote_chars` | 2,000 | Longer evidence quotes fail local validation; use a smaller exact span |
| `max_request_tokens` | 32,000 | Effective limit is the lower of this value and provider capability minus output reserve |
| `max_inventory_items_per_call` | 250 | Split on section/repeat boundaries; do not truncate inventory silently |
| `max_candidate_targets_per_reference` | 10 | More candidates produce `AMBIGUOUS_TARGET` without a model guess |
| `max_discrepancies_per_review_call` | 25 | Split packets in stable source order |
| `max_source_spans_per_decision` | 8 | Reviewer cannot cite or receive more spans for one decision |
| `max_condition_depth` | 6 | Reject deeper extracted AST as review-required opaque evidence |
| `max_condition_nodes` | 100 | Reject larger extracted AST as review-required opaque evidence |
| `low_confidence_threshold` | 0.70 | Evidence below this value selects Pass B |
| `unusual_in_degree_threshold` | 4 | Preliminary target in-degree at or above this value selects Pass B |
| `unusual_out_degree_threshold` | 3 | Preliminary source out-degree at or above this value selects Pass B |

The per-run in-memory cache key is the tuple of provider adapter identity,
provider name, model/deployment, pass kind, prompt version and digest, canonical
response-model schema hash, provider request-schema hash, normalized generation
settings, and normalized complete request digest. A cache hit must match every
component. The cache stores parsed validated models only and is destroyed at run
end.

### Routing Result Outcome Table

| Condition | Output | Diagnostic/action | Status |
|---|---|---|---|
| Final accepted graph fails a structural invariant | none | `ROUTING_GRAPH_INVALID`; do not write artifacts | failed |
| Inventory is empty | none | `ROUTING_EMPTY_INVENTORY`; do not write artifacts | failed |
| Supplied SVIS snapshot does not match the typed source binding/current private snapshot | none | `ROUTING_SOURCE_MISMATCH` before provider calls; do not write artifacts | failed |
| All required source/model regions fail | none | failed blocks plus safe operational diagnostics | failed |
| Some source/model regions fail but a structurally valid graph remains | routed output | preserve failed regions and accepted graph | partial |
| Any legacy variable cannot link to a node | routed output with null link | `UNLINKED_VARIABLE` and preserve variable | partial |
| Ambiguous/unresolved candidate remains after complete source processing | routed output | warning, candidate, discrepancy, `needs_human_review`; no accepted edge | success |
| No proven terminal path or opaque coverage remains | routed output | review warning; no fabricated edge | success |
| Native typed routing is complete and valid | routed output | zero provider calls | success |
| Cancellation or process-control exception occurs | none | propagate exception; publish nothing | not converted to a result |

Review warnings do not redefine extraction completeness. `partial` is reserved
for missing processed regions or unlinked legacy variables. No routed artifact is
written when `output` is absent.

## Dependency Graph

| Phase | Depends on | Unlocks |
|---|---|---|
| 1. Foundation, contract, and models | Approved brainstorm plus G1/G2/G5 closure work | Deterministic graph work |
| 2. Deterministic graph core | Phase 1 models and rights-approved source cases | LLM evidence reconciliation |
| 3. Structured extraction and review | Phases 1-2; Step 8 supplies or reuses G3 before routing calls | End-to-end routed pipeline |
| 4. Pipeline, native path, and artifacts | Phases 1-3 plus G2; Step 9 supplies or reuses G4 | Public routed output |
| 5. Evaluation, docs, and package evidence | Phases 1-4; G6 only if an optional protected capture is selected | `/cg-work` completion |

Phases are sequential at their evidence gates. Phase 1 first closes or verifies
G1, G2, and G5, then freezes model/API/version/limit names before expected graph
fixtures are generated. Step 8 supplies or verifies G3 before its first routing
provider call. Step 9 supplies or verifies G4 before V9. Do not start artifact
integration before legacy projection tests and G2 evidence exist.

## Phase 1: Contract, Fixtures, and Public Models

### 1. Close and Verify the Production Foundation Gates

- **Requirements**: R2, R3, R7, R10, R12, R16, R19
- **Files**: `src/survey_scribe/sources/base.py`, `sources/chunking.py`,
  `sources/docling.py`, lossless table transport, `serialization/artifacts.py`,
  serializer port, `results.py`, source/artifact/coverage tests, production review
  and work-report evidence
- **Details**: Close or verify G1, G2, and G5 before routing code depends on
  them. For G1, add immutable source diagnostics, failed-unit/page coverage,
  bounded private source snapshots with digests, complete multi-page provenance,
  hard final token budgets including overlap, and lossless structured table
  transport. Split safe text deterministically; reject or structurally split an
  oversized table rather than exceed the provider limit. For G2, use a typed
  artifact serializer/plan port so generic results do not always emit SVIS,
  validate a detached survey identity snapshot, reject filesystem aliases and
  reserved names, hold an OS-owned crash-released lock for the full transaction,
  reject symlink/reparse internal components with no-follow operations, and add a
  durable recoverable publication protocol with required directory flushes and
  hard-process-exit recovery. For G5, add branch tests until the configured 95%
  threshold passes without exclusions or threshold reduction. Record each old
  finding ID, remediation scope, executed command, and result in this plan's
  execution report. Do not edit historical review status or another plan's work
  report. Do not mark routing Phase 1 complete while any named gate lacks passing
  evidence.
- **Test Scenarios**: Partial PDF/page conversion; multi-page block/table;
  oversized text/table/overlap; table cell pipes/newlines; source replacement;
  hard exit before/after each generation/projection/pointer stage; stale lock;
  concurrent writers; symlink and Windows reparse escape; case/trailing-dot/
  reserved survey IDs; generic non-SVIS write; coverage below/exactly/above gate.
- **Tests**: Source contract/integration suites; artifact fault, process, path,
  lock, serializer, and identity suites; exact command
  `uv run pytest tests --ignore=tests/package --cov=survey_scribe --cov-branch --cov-report=term-missing --cov-fail-under=95`.
- **Acceptance criteria**: G1, G2, and G5 each have executed passing evidence;
  production findings P0.3, P0.4, P0.5, P0.6, P0.7, P0.8, P0.9, P0.11, P1.8,
  P1.10, and P1.13 have passing remediation evidence in this plan's execution
  report; no
  routing request can observe incomplete source coverage, exceed the effective
  token limit, or publish through the known unsafe artifact path.

### 2. Preserve Compatibility and Prepare Routing Source Cases

- **Requirements**: R2, R8, R9, R10, R16, R17, R19
- **Files**: `tests/fixtures/routing/`, routing fixture manifest, manifest validator, `tests/characterization/test_schema_contract.py`, new routing fixture tests
- **Details**: Preserve every existing characterization assertion unchanged.
  Create synthetic, non-sensitive questionnaire source snippets only for: one
  skip plus implicit fallthrough; multiple
  answer-code branches plus default; section target; multiple incoming paths;
  activation without transition; roster loop with exit; correction return;
  unsupported inferred cycle; screen-out terminal; garbled target; repeated
  consumption template; duplicate source IDs in separate sections; prompt
  injection text; and a 1,000-node generated graph. Record source-case
  provenance, rights basis, expected logical cases, and SHA-256 values. Do not
  author expected evidence, canonical IDs, graphs, diagnostics, or model-quality
  responses until Steps 3-4 freeze the models and identity algorithm.
- **Test Scenarios**: Valid source-case corpus; checksum drift; missing rights/provenance;
  duplicate fixture ID; malformed source-case manifest; restricted-path or secret
  content; weakened expected-count thresholds.
- **Tests**: Fixture manifest validator and focused fixture-policy tests; existing
  `uv run pytest tests/characterization/test_schema_contract.py`.
- **Acceptance criteria**: All required source cases and rights records exist;
  invalid source manifests fail closed; the exact ordered v1 characterization
  remains unchanged and passing; no synthetic source is labeled a model-quality
  benchmark.

### 3. Implement Routed Public Models and Strict Extraction Contracts

- **Requirements**: R1, R2, R3, R4, R5, R6, R7, R8, R9, R10, R14, R15, R19
- **Files**: `src/survey_scribe/models/routing.py`,
  `src/survey_scribe/routing/contracts.py`, model exports,
  `tests/unit/test_routing_models.py`, JSON-Schema fixture/tests
- **Details**: Implement strict enums and Pydantic models for
  `RoutingSourceBinding`, source spans, item references, inventory items,
  separate extracted/canonical conditions, native
  expressions, transition/activation evidence, extraction batches, candidate
  edges, discrepancies, append-only reviewer decisions, repeat specs,
  containment hierarchy, nodes, accepted edges, loop regions, diagnostics,
  routing audit, graph, `RoutedSurveyVariable`, and `RoutedSurveySVIS`. Use
  `ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)` on every
  final nested model and immutable tuples/frozen JSON values throughout. Keep
  extraction response models separately strict and discriminated. Make
  `routing_node_id` nullable with the cardinality policy in the contract.
  Validate operator shapes, finite values, AST limits, native projections,
  acyclic containment and derived children, section/repeat entries, node-kind
  fields, terminal behavior, unique IDs, accepted endpoints, accepted-only
  adjacency, one default kind per source, equal `Literal["1.0"]` routing
  versions, and append-only review linkage. Generate canonical JSON Schema from
  Pydantic. Provider request-schema compatibility is deferred to the G3 adapter
  and named `ModelCapabilities` rows in Step 8; do not claim one generic offline
  provider subset. Keep G6 capture authorization, credentials, gateway endpoints,
  and production deployment policy out of the public routed graph schema.
  Provider execution metadata remains a separate non-sensitive operational
  record so the graph contract is identical under tests and production.
- **Test Scenarios**: Every valid operator; missing/extra/wrong-shape fields;
  Boolean/integer ambiguity; NaN/infinity; AST depth/node limits; ambiguous
  union; extracted-to-canonical reference conversion; native expression with
  supported/unsupported projection; duplicate nodes/edges/evidence; candidate
  without endpoint; dangling accepted edge; terminal out-edge; containment
  cycle; missing section entry; adjacency mismatch; mutable nested input;
  review-decision supersession; routed-to-v1 reconstruction; version mismatch;
  JSON and JSON-Schema round trip.
- **Tests**: `uv run pytest tests/unit/test_routing_models.py
  tests/characterization/test_schema_contract.py`; Pyright on public models.
- **Acceptance criteria**: The routed model represents every prepared source-case
  shape; invalid or mutable final structures fail with safe errors; canonical
  schema is deterministic; accepted graph facts and disputed audit records cannot
  be conflated; existing v1 model fields and ordered serialization remain exact.

## Phase 2: Inventory, Reconciliation, and Graph Validation

### 4. Build the Logical Item Inventory and Deterministic Identity Resolver

- **Requirements**: R3, R4, R7, R10, R13, R14
- **Files**: `src/survey_scribe/routing/inventory.py`,
  `src/survey_scribe/routing/identity.py`, internal extraction integration,
  `tests/unit/test_routing_inventory.py`, `test_routing_identity.py`
- **Details**: Build inventory records from normalized source blocks and extracted
  variables without changing public v1 variables. Preserve printed IDs, raw
  references, sections, source order, logical kinds, parent containment, section
  and repeat entries, repeat membership, block IDs, and variable links. Extend
  only internal item-extraction responses to
  retain printed question identity. Normalize exact aliases within section
  namespaces. Generate fallback IDs from stable normalized inputs and an
  explicit source-version digest. Detect duplicate/ambiguous printed IDs and
  retain candidates for review. Validate each evidence quote against its named
  normalized block with bounded whitespace normalization. Assign deterministic
  evidence IDs; ignore LLM final-ID suggestions. Generate and validate
  `RoutingSourceBinding` from the same bounded private snapshot and source digest
  used by source conversion; never recompute it from an unvalidated reopened
  path. Enforce many variables to one
  question and at most one node per variable index. Preserve unmatched variables
  for a nullable routed link and partial diagnostic. Resolve
  `ExtractedRoutingCondition.ItemReference` into canonical question node IDs only
  after scope resolution. After model and identity rules are frozen, generate
  expected evidence, IDs, candidate/accepted graphs, audit records, diagnostics,
  and checksums for the Step 2 mechanics fixtures; these outputs test
  deterministic mechanics and are not a model-quality benchmark.
- **Test Scenarios**: Printed ID; no ID; same ID in separate sections; same ID in
  one section; aliases; multilingual prefixes; valid/mismatched source binding;
  changed source digest; source replaced after binding; reordered
  blocks; repeated table template; invalid block; quote mismatch; quote too long;
  collision injection; several variables to one question; one variable to two
  nodes; unmatched variable; containment cycle; missing section entry; ambiguous
  extracted condition reference; expected-output checksum drift.
- **Tests**: `uv run pytest tests/unit/test_routing_inventory.py
  tests/unit/test_routing_identity.py`.
- **Acceptance criteria**: IDs, hierarchy, variable links, and inventory order are
  reproducible across runs; all accepted evidence and canonical condition
  references are resolved and verifiable; ambiguous references remain candidates;
  every deterministic mechanics source case now has executable checksummed
  expected output.

### 5. Reconcile Evidence into One Canonical Directed Multigraph

- **Requirements**: R4, R5, R6, R7, R8, R13, R14, R15
- **Files**: `src/survey_scribe/routing/reconcile.py`,
  `src/survey_scribe/routing/diagnostics.py`,
  `tests/unit/test_routing_reconcile.py`
- **Details**: Normalize evidence identities and combine compatible observations
  while preserving all evidence records. Resolve exact and scoped aliases before
  considering reviewer candidates. Build explicit/native conditional,
  unconditional, sequential, default, terminal, and return-edge candidates. Keep
  flow kind independent from later loop-region membership. Add an
  inferred sequential edge only when source order is unambiguous and no explicit
  route bypasses it. Enforce one default and source-defined priority. Accept
  source-verified unambiguous forward evidence; use incoming evidence as an
  independent check. Send disagreement, incoming-only, ambiguous, fuzzy,
  conflicting default, opaque coverage, ambiguous condition reference, and
  inferred-cycle cases to the candidate/discrepancy layer. Generate accepted-edge
  IDs from canonical normalized content. Build stable adjacency only from
  accepted edges after decisions. Candidates can preserve raw/unresolved targets
  and never participate in reachability, terminal, or SCC analysis. Never delete
  original evidence or candidate history when a reviewer rejects or replaces a
  candidate.
- **Test Scenarios**: Matching forward/incoming; explicit forward only; incoming
  only; conflicting target/condition; native plus LLM duplicate; multiple edges
  between nodes; implicit fallthrough; explicit default; multiple defaults;
  ordered routes; terminal route; ambiguous section target; unresolved target;
  overlap duplicate; unresolved candidate without canonical endpoint; accepted-
  only adjacency; reviewer replace/reject/unresolved with append-only audit.
- **Tests**: `uv run pytest tests/unit/test_routing_reconcile.py`.
- **Acceptance criteria**: Every mechanics evidence batch produces the expected
  accepted edge or separate candidate/discrepancy and stable order; node
  adjacency is an exact projection of accepted edges only; no source evidence,
  candidate, or review decision is lost.

### 6. Implement Deterministic Graph Integrity and Loop Analysis

- **Requirements**: R4, R8, R9, R10, R14, R18, R19
- **Files**: `src/survey_scribe/routing/validate.py`,
  `src/survey_scribe/routing/algorithms.py`,
  `tests/unit/test_routing_validation.py`, scale tests
- **Details**: Implement stable diagnostics for duplicate IDs/edges, dangling and
  ambiguous targets, unreachable nodes, nonterminal dead ends, multiple defaults,
  unknown condition references/codes, provable uncovered branches, unproven
  overlap, incoming mismatch, activation conflict, unsupported cycle, no loop
  exit, no terminal path, and adjacency mismatch. Use iterative traversal and an
  iterative strongly connected component algorithm with deterministic source
  ordering. Classify source-supported repeat-group, repeat-until, correction,
  and other loop regions without enumerating simple cycles. Use one loop record
  per declared logical repeat or supported SCC region; resolve overlapping
  declarations by validated containment nesting. Keep inferred cycles in the
  candidate/discrepancy layer. Validate hierarchy acyclicity separately from
  flow cycles. Prove branch coverage
  only for finite known categorical codes and non-opaque conditions. Do not add
  NetworkX or another graph runtime dependency.
- **Test Scenarios**: DAG; disconnected section; terminal; self-loop; two-node
  cycle; nested/overlapping declared loops; SCC with exponentially many possible
  simple cycles; correction-return inside a repeat region; explicit repeat exit;
  no exit; inferred cycle; duplicate parallel edge; opaque branch; exhaustive categories; missing
  category code; 1,000 nodes and at least 3,000 edges; deterministic diagnostic
  order.
- **Tests**: `uv run pytest tests/unit/test_routing_validation.py`; generated
  scale test and standalone benchmark report.
- **Acceptance criteria**: Mechanics-fixture diagnostics match exactly; a
  1,000-node graph
  validates without `RecursionError`, nondeterminism, or new dependency; every
  declared/SCC loop region has bounded metadata, no all-simple-cycle enumeration
  occurs, and every unsupported cycle is review-visible outside the accepted
  graph.

## Phase 3: Structured Extraction and Discrepancy Review

### 7. Implement Versioned Routing Prompts and Strict Prompt Contracts

- **Requirements**: R5, R6, R7, R8, R11, R12, R15, R16
- **Files**: `src/survey_scribe/routing/prompts.py`, prompt render helpers,
  `tests/unit/test_routing_prompts.py`, recorded structured response fixtures
- **Details**: Implement separate versioned system, forward task,
  incoming/activation task, and reviewer task prompts from the brainstorm. Require
  exact source quotes, actual flow direction, raw condition text, explicit versus
  inferred flags, unresolved references, and complete examined-item lists. The
  system prompt treats questionnaire content as untrusted, forbids tools and
  invented IDs/codes/targets, distinguishes activation from transition, and
  defines default/terminal/loop semantics. Pass B receives target items, relevant
  inventory, and retrieved source spans but no Pass A output. Reviewer packets
  contain only discrepancies and bounded evidence. Prompt rendering validates
  required placeholders and records semantic version plus SHA-256. Keep source
  braces and delimiters as data.
- **Test Scenarios**: All placeholders; braces/tags in source; questionnaire text
  tells model to ignore system or invoke tools; no-route item; multiple branches;
  default; cross-section target; loop; incoming paths; activation-only rule;
  reviewer unresolved; output with extra/missing keys; source quote too long.
- **Tests**: `uv run pytest tests/unit/test_routing_prompts.py`; schema validation
  of all recorded outputs.
- **Acceptance criteria**: Prompt versions and hashes are deterministic; every
  mechanics-fixture task has a strict valid expected response; malicious source text remains
  delimited data and cannot alter configured roles/tools/schema.

### 8. Add Adaptive Extraction, Independent Verification, and Reviewer Orchestration

- **Requirements**: R7, R8, R11, R12, R14, R15, R16, R17, R20, R21, R22
- **Files**: `src/survey_scribe/routing/extraction.py`,
  `src/survey_scribe/routing/review.py`, routing config additions,
  `src/survey_scribe/config.py`,
  `src/survey_scribe/providers/base.py`, `providers/capabilities.py`, the
  production provider package's Instructor-backed OpenAI-compatible adapter when
  absent, `tests/integration/test_routing_extraction.py`, production provider
  contract fakes/capability rows
- **Details**: Own G3. If the production `StructuredProvider` slice is absent,
  first implement its generic async port, normalized `ProviderResponse[T]`,
  `ModelCapabilities`, attempt counts, truncation/error/cancellation/redaction
  behavior, deterministic fakes, and Instructor-backed OpenAI-compatible adapter
  inside `survey_scribe.providers` as specified by production-plan Step 5. Do not
  implement a routing-specific adapter or all remaining providers. Execute the
  shared provider contract suite, then consume
  `StructuredProvider.generate()` and normalized `ProviderResponse[T]` directly.
  Do not define another generator protocol or Instructor adapter. Use the one
  shared global limiter across base extraction, Pass A, Pass B, reviewer, and
  every retry. Reuse existing retry/generation settings and provider capability
  checks; preserve transport and validation attempt counts; treat
  truncation and exhausted validation as failed evidence blocks. Run Pass A over
  stable section chunks with boundary inventory. Build a preliminary graph and
  select Pass B targets by fixed risk predicates. Reconcile both passes, then
  send bounded discrepancy packets to the reviewer. Validate every reviewer
  citation before applying its decision. Preserve partial valid sections and
  stable source order. Apply every named `RoutingConfig` bound. Use the complete
  per-run cache key from the contract. For each provider capability row, transform
  and validate the extraction/reviewer request schema, record canonical and
  request schema hashes, and reject unsupported strict output before sending
  source data. Keep one optional protected live schema smoke. Append every
  discrepancy and decision to `routing_audit`. Use safe operational templates
  and never log source, prompt, response, native expression, or reviewer bodies.
  Keep testing authorization outside the provider port. The provider adapter
  accepts production configuration supplied by the caller and records the
  configured gateway/provider identity, configured route/model alias, returned
  provider/model identity, normalized token usage when supplied, response ID,
  attempts, prompt/schema hashes, and response digest without raw content.
  OpenAI-compatible institutional gateways are valid provider boundaries. A
  dynamic gateway route is allowed for normal production operation and for a
  gateway-route smoke, but it cannot support an exact-backend benchmark claim
  unless the backend is pinned or proved by returned metadata. Do not require a
  cost field when the gateway exposes no reliable cost; preserve request/token
  usage so the capture runner or hosting service can enforce its own aggregate
  policy.
- **Test Scenarios**: No-risk section avoids Pass B; each risk predicate selects
  Pass B; Pass B cannot access Pass A; one/all chunks fail; truncation; malformed
  response; retry success/exhaustion; cancellation; out-of-order completion;
  reviewer correction/rejection/unresolved; invalid reviewer quote; repeated
  discrepancy; rate limit; exact shared concurrency ceiling; provider capability
  rejects schema; canonical/request hash drift; cache isolation across pass/model/
  prompt/schema/settings; optional live smoke absent; control exception; every
  source-derived field and nested model prose absent from errors.
- **Tests**: `uv run --extra openai pytest
  tests/integration/test_routing_extraction.py tests/contract/providers`;
  architecture import checks; optional protected live
  provider schema smoke is recorded but is not a pull-request requirement.
- **Acceptance criteria**: Fake/recorded runs are deterministic; simple sections
  use one pass; risky regions receive independent evidence; no uncited reviewer
  decision changes the graph; every review action round-trips in the audit;
  G3 has passing evidence in this plan's work report; outbound operations never
  exceed `max_concurrency`; cancellation and process-
  control exceptions propagate with no artifact; core imports no provider SDK;
  credentials and G6 approvals never enter provider call records or artifacts;
  configured and returned gateway/model identities are distinguishable.

## Phase 4: Routed Pipeline, Native Sources, and Artifacts

### 9. Assemble the Routed Pipeline and Native Routing Bypass

- **Requirements**: R1, R3, R6, R7, R8, R9, R10, R12, R13, R14, R15, R18, R21, R22
- **Files**: `src/survey_scribe/routing/pipeline.py`,
  `src/survey_scribe/routing/native.py`, `sources/registry.py`, the production
  core XLSForm adapter/support matrix when absent,
  `tests/contract/sources/test_native_routing.py`,
  `tests/integration/test_routing_pipeline.py`
- **Details**: Implement the exact public `QuestionnaireRouter` API from the
  contract over the G3 provider port. Keep
  `SourceRegistry.convert() -> SourceDocument` unchanged. Add the strictly
  additive `SourceRegistry.convert_with_native() -> SourceConversionResult`,
  where the result contains document, source binding, and optional native
  semantics; `QuestionnaireRouter` uses only the additive method. Existing tests,
  docs, and wheel smoke keep using `convert()`. Native-capable adapters return typed item/group/
  repeat/relevance/transition expressions through this wrapper without changing
  source text or making an LLM call. Supply a synthetic native adapter contract.
  Own G4: if the production core XLSForm adapter is absent, implement its bounded
  survey/choices/settings parsing, groups/repeats/relevance preservation,
  resource/path/formula controls, and versioned support matrix from production-
  plan Step 8, then integrate at least one real relevance and repeat route.
  Unsupported XLSForm functions and
  arithmetic remain `NativeExpression` plus opaque canonical projection, with no
  LLM call. At entry, detach the supplied SVIS and validate the complete typed
  source binding before inventory or provider work. Convert repeat structures to
  one logical template. Build
  `RoutedSurveyVariable` records by typed reconstruction and verified inventory
  links under the nullable/cardinality policy. Derive final graph indexes only
  from accepted edges and apply the routing result outcome table exactly.
  `QuestionnaireRouter` does not request interactive G6 approval. In production,
  it uses the provider and validated runtime configuration injected by the
  caller. The deployment is responsible for deciding which sources may be sent
  to its gateway; this package enforces exact source binding and content-safe
  operational boundaries but does not claim to infer institutional data rights.
- **Test Scenarios**: PDF-like text route; all-native route with zero model calls;
  mixed native plus LLM enrichment; no provider for native source; missing item
  link; duplicate link; section/repeat/terminal nodes; partial failed section;
  sync/async parity; running event loop; cancellation; valid source binding;
  filename/media type/digest/survey/version mismatch before model call; caller
  mutates SVIS after entry; empty inventory; structural failure; warning-only
  discrepancy; stable ordering; unchanged `convert()` plus additive
  `convert_with_native()` behavior; real core XLSForm supported/unsupported native
  expression.
- **Tests**: `uv run --extra tabular pytest
  tests/contract/sources/test_native_routing.py
  tests/contract/sources/test_xlsform.py
  tests/integration/test_routing_pipeline.py`.
- **Acceptance criteria**: The exact public signatures pass type/API tests;
  end-to-end mechanics sources produce expected routed SVIS; accepted edges and
  audit candidates remain separate; native typed routes make zero model calls;
  G4 has passing evidence in this plan's work report and supplies one real core
  native integration; source/SVIS mismatch fails before provider calls; repeated
  modules remain templates; result status follows the table; partial or disputed logic is
  visible rather than fabricated.

### 10. Publish Routed Artifacts, Configuration, and Public Exports Safely

- **Requirements**: R1, R2, R12, R16, R19, R20, R21, R22
- **Files**: `src/survey_scribe/serialization/routing.py`,
  `serialization/artifacts.py`, `results.py`, routing/public exports,
  `config.py`, `tests/unit/test_routing_artifacts.py`, public API and package tests
- **Details**: Block on G2. Add typed routed-to-v1 projection and routed JSON
  serialization through the G2 serializer/artifact-plan port. Revalidate a
  detached frozen snapshot, then write a routed main, semantically exact ordered
  legacy projection, sidecar, and routed manifest v2 through the durable
  recoverable publication protocol. Keep existing v1 manifest/write behavior
  unchanged. Validate equal routed/graph `Literal["1.0"]` versions and record
  both. Use safe error templates and collect every source-derived string at the
  request boundary; do not limit protection to `raw_text` and quotes. Record only
  versions and digests in sidecars/manifests.
  Add routing limits and thresholds as typed nested configuration without
  credentials or implicit provider selection. Keep production provider/model/
  base-URL/API-version configuration separate from the ephemeral G6 capture
  record. Secret values remain excluded from serialization and representation.
  Routed operational metadata may retain configured/returned provider and model
  identifiers, normalized usage, versions, and digests, but no endpoint query,
  authentication header value, source prose, prompt, or response body. Export routed models and
  `QuestionnaireRouter` from the stable paths in the API contract; no routing
  module imports Instructor.
- **Test Scenarios**: v1 ordered semantic compatibility; routed main round trip;
  exact keys/types/defaults/order in legacy projection; version mismatch;
  manifest v1/v2 parser behavior; projection/main/pointer hard-process failure
  and recovery; overwrite/collision;
  concurrent same-survey write; invalid route graph; raw source text in an error;
  every source-derived field, failed chunk, reviewer response, native expression,
  adapter error, and nested exception absent from sidecar/diagnostic; import/help
  without extras or credentials; wheel
  includes routing modules.
- **Tests**: `uv run pytest tests/unit/test_routing_artifacts.py
  tests/unit/test_artifacts.py tests/characterization/test_schema_contract.py
  tests/unit/test_public_api.py`.
- **Acceptance criteria**: Routed artifacts recover to one consistent generation
  after every fault and round-trip with immutable audit history; legacy keys,
  nesting, JSON types, defaults, enum values, field order, and variable order stay
  exact; no source/model prose enters operational artifacts; base package import
  does not load optional SDKs.

## Phase 5: Quality Evaluation, Documentation, and Package Evidence

### 11. Add Routing Quality Evaluation and Questionnaire-Scale Evidence

- **Requirements**: R8, R9, R10, R14, R16, R17, R19, R20, R22
- **Files**: `scripts/evaluate_routing.py`, deterministic mechanics fixtures,
  optional protected capture runner and private capture manifest,
  evaluation tests/report, scale benchmark
- **Details**: Implement deterministic comparison of expected and actual nodes,
  directed edges, targets, edge kinds, normalized condition ASTs, terminal/loop
  classes, unresolved references, and reviewer changes. Report first-pass and
  post-review metrics separately. Mechanics fixtures test scoring and graph
  behavior and are the required V11 evidence.

  The live model-quality capture is optional and separate. When selected, run a
  protected preflight that computes the source digest and discovers endpoint/API/
  SDK/schema capabilities without exposing credentials or source text. The human
  approves one sanitized summary containing: source authorization attestation,
  gateway route/model alias, credential environment-variable name only, maximum
  requests, maximum input/output tokens, optional cost ceiling when reliable,
  temporary-output/deletion policy, and stop conditions. Do not require the human
  to know APIM header names, SDK internals, or backend deployment metadata that
  the preflight can discover. Execute only after `APPROVE G6 CAPTURE` and only
  within the approved summary.

  For World Bank mAI Factory or another multi-cloud gateway, record the gateway
  identity, configured route/model alias, and returned provider/model metadata
  for each response. If the route is dynamic, label the result as a gateway-route
  benchmark and make no exact Azure OpenAI, Gemini, or Claude claim. If the route
  is pinned, record the exact returned backend/model when available. Record SDK,
  prompt version/hash, canonical and request-schema hashes, generation settings,
  capture date, source and response digests, normalized request/token usage, and
  reviewer-pass identity. Never record a key or raw endpoint credential.

  Evaluate any protected capture against edge precision >= 0.95, edge recall >=
  0.90, target accuracy >= 0.95, explicit normalized condition-AST exact match >=
  0.90, terminal/cycle classification at 1.00, and zero invented accepted source
  IDs. An unresolved expected edge is a recall false negative and target miss; it
  cannot protect precision. Report opaque and unresolved rates explicitly. A
  missing, declined, or below-threshold live capture limits model-quality claims
  but does not block deterministic V11, V12, or plan completion. Do not spend
  additional prompt/reconciliation rounds beyond the approved cap merely to make
  the benchmark pass.

  Add a generated 1,000-node/3,000-edge run that records hardware, duration, and
  peak-memory method without imposing a fragile cross-platform microbenchmark
  threshold. Prevent evaluator inputs/outputs from entering built distributions.
- **Test Scenarios**: Exact match; missing/extra/reversed edge; parallel edges;
  equivalent and non-equivalent AST; wrong target; unresolved; reviewer improves,
  degrades, or leaves quality; invented ID; zero denominator; large deterministic
  graph; authored synthetic response rejected as live model benchmark; dry-run
  without credential access; source digest or route changes after approval;
  dynamic route labeled as gateway-route evidence; request/token cap exhaustion;
  missing source attestation; temporary raw-output deletion; no source text in
  metric output.
- **Tests**: Evaluator unit tests and `uv run python scripts/evaluate_routing.py
  --manifest tests/fixtures/routing/manifest.toml`. Protected capture tests use a
  fake gateway and never require provider credentials in CI.
- **Acceptance criteria**: Deterministic mechanics checks and evaluator edge cases
  pass; first-pass quality is not hidden by review; the scale run completes
  without recursion failure or nondeterministic hashes; reports contain metrics
  and digests, not source text. When an optional G6 capture runs, its approval,
  discovered capability summary, actual-versus-budget usage, deletion result,
  and benchmark status are recorded. When it does not run, record `not_run` and
  prohibit real-provider/model quality claims without blocking completion.

### 12. Complete Routing Documentation, Schema Export, and Final Quality Gates

- **Requirements**: R1, R2, R3, R4, R5, R6, R7, R8, R9, R10, R11, R12, R13, R14, R15, R16, R17, R18, R19, R20, R21, R22
- **Files**: `README.md`, `docs/routing.md`, schema/API/provider/source/security/
  evaluation docs, `mkdocs.yml`, schema export command/tests, package allowlists,
  changelog
- **Details**: Document routing versus activation, canonical edges versus
  evidence, node/condition/loop semantics, previous/next derivation, confidence
  and review status, audit history, hierarchy, native expressions and bypass,
  large-questionnaire behavior, and integration through the production
  `StructuredProvider` capability contract. Explain that Instructor is internal
  to provider adapters and that direct OpenAI/LangChain integrations must adapt
  to `StructuredProvider` rather than enter the routing core,
  artifact/privacy behavior, known limitations, and migration from
  `skip_condition_raw`. Clearly document that G6 is an optional protected test
  capture, while final production uses administrator-owned `SurveyScribeConfig`,
  provider construction, gateway quotas, secret storage, source authorization,
  and institutional retention policy without an interactive approval on every
  request. Document gateway-route versus pinned-backend quality claims. Generate
  JSON Schema from Pydantic and verify drift.
  Provide small synthetic examples with a conditional/default path, multiple
  incoming paths, and a loop. State that output is not an interview engine.
  Update wheel/sdist allowlists and test the exact built wheel in isolation.
- **Test Scenarios**: Strict docs build; broken links/anchors; stale schema;
  example execution; missing optional dependency; editable-only import; omitted
  routing module; leaked fixtures/reports; legacy quick start unchanged.
- **Tests**: `uv run ruff check .`; `uv run ruff format --check .`;
  `uv run pyright`; focused tests; package-excluded 95% branch-coverage command
  from Step 1; `uv run mkdocs build --strict`; remove stale current-version
  distributions, then `uv build`; `uv run twine check --strict dist/*`;
  `uv run --no-config --no-project --default-index https://pypi.org/simple --with
  pip==25.2 python -m pip download --dest .cache/wheelhouse --requirement
  tests/fixtures/package/constraints.txt`; `uv run pytest tests/package` for the
  exact-wheel isolated install and distribution-content gates.
- **Acceptance criteria**: A package consumer can interpret and validate routed
  output from docs alone; schemas/examples are generated and executable. One
  explicit network-enabled, credential-free wheelhouse-preparation command is
  permitted before package tests. All local gates run without provider
  credentials. Only the exact-wheel installation test claims enforced offline
  execution after wheelhouse preparation; Ruff, Pyright, coverage, docs, build,
  and Twine use the locked development environment but do not claim network-
  denial evidence. A separately approved optional G6 capture is the only provider
  inference operation in the test/evidence workflow; normal production inference
  follows deployed runtime policy and is outside these package gates.

## Testing Strategy

Use an offline-first test pyramid:

| Layer | Purpose | Network policy |
|---|---|---|
| Unit | Models, identity, AST, reconciliation, diagnostics, algorithms, prompts, projection | Forbidden |
| Contract | Production `StructuredProvider` and native-routing adapter behavior | Fakes and synthetic fixtures only |
| Integration | Forward/reverse/reviewer orchestration and routed pipeline | Recorded responses; forbidden |
| Characterization | Exact legacy model/JSON behavior | Forbidden |
| Security | Prompt injection, quote verification, redaction, import boundaries | Forbidden |
| Scale | 1,000+ node deterministic graph and AST limits | Forbidden |
| Mechanics quality | Scoring, edge/target/condition/loop comparison | Authored synthetic fixtures; forbidden |
| Model quality | Optional captured first-pass and post-review extraction metrics | Lightweight G6 approval, approved sanitized source, bounded protected capture, and offline sanitized replay; not a PR or completion gate |
| Package/docs | Exact wheel/sdist, isolated import, schema/example/docs drift | No provider credentials; exact-wheel install is network denied after wheelhouse preparation |
| Optional live smoke | Provider schema/API drift | Protected manual/scheduled only; not required here |

Rules:

- Do not use restricted questionnaires, credentials, unsanitized traces, or raw
  provider responses as fixtures.
- Prefer property-style parametrization with deterministic seeds over snapshots
  of incidental Pydantic errors or logs.
- Assert stable IDs, ordering, and diagnostic codes.
- Test all malformed external values with safe validation messages that exclude
  rejected input.
- Keep model-quality thresholds separate from deterministic graph correctness.
- Treat a missing or failed G6 capture as `not_run` or failed optional evidence,
  not as a deterministic package failure. Limit claims instead of weakening
  mechanics gates.
- In production, use deployment configuration and institutional source/gateway
  policy. Do not reuse the test capture approval as a production secret or
  authorization mechanism.
- Build once and test the exact current-version wheel, not only the editable
  checkout.

## Documentation Checklist

- [ ] Explain routing logic versus activation/applicability.
- [ ] Document all node, edge, terminal, repeat, loop, and condition types.
- [ ] Explain canonical edges and derived previous/next adjacency.
- [ ] Explain explicit, inferred, native, incoming, and reviewer evidence.
- [ ] Document `opaque`, unresolved references, confidence, and review states.
- [ ] Provide Pydantic and generated JSON Schema references.
- [ ] Document integration through `StructuredProvider` and its capability rows;
      keep Instructor internal to provider adapters.
- [ ] Describe how OpenAI, Instructor, or LangChain adapters can satisfy the
      production provider port without making them routing-core dependencies.
- [ ] Document section chunking, target resolution, adaptive Pass B, and scale.
- [ ] Document native typed-routing bypass and exact supported adapters.
- [ ] Document routed main versus exact legacy projection and privacy behavior.
- [ ] Provide conditional/default, multiple-incoming, terminal, and loop examples.
- [ ] State deterministic mechanics limits, captured model-benchmark scope, and
      first-pass versus reviewer effect separately.
- [ ] Distinguish lightweight G6 test-capture requirements, configuration, and
      behavior from final production provider, secret, quota, source, logging,
      and retention policy.
- [ ] Explain gateway-route benchmarks versus pinned exact-backend claims,
      including World Bank mAI Factory-style multi-cloud routing.
- [ ] State that runtime interview execution and JSON Logic guarantees are out of
      scope.
- [ ] Add migration guidance from `skip_condition_raw` without deprecating the
      existing field in this plan.

## Plan Review Resolution Matrix

All findings from the 2026-08-31 `/cg-plan-review` are accepted for revision.

| Finding | Resolution in this revision |
|---|---|
| QRG-PLN-001 | G1 and Step 1 close source coverage, hard token, lossless table, provenance, and source-snapshot findings before routing extraction |
| QRG-PLN-002 | G2 and Steps 1/10 require crash recovery, no-follow paths, OS locking, detached identity, and serializer boundaries before routed publication |
| QRG-PLN-003 | R12, the structured-output contract, G3, and Step 8 remove the duplicate generator/Instructor path and require `StructuredProvider` |
| QRG-PLN-004 | Cross-Plan Scope Approval permits only the bounded source-cited `RoutingDiscrepancyReviewer` |
| QRG-PLN-005 | Canonical Graph Contract and Step 5 keep only accepted edges authoritative; candidates/disputes are separate |
| QRG-PLN-006 | Compatibility/Evidence contracts and Steps 3/5/8/10 require append-only discrepancies and review decisions in the primary artifact |
| QRG-PLN-007 | Identity/Graph contracts and Steps 3/4/9 add validated containment, children, and section/repeat entry semantics |
| QRG-PLN-008 | Condition Contract and Steps 3-5 split extracted `ItemReference` conditions from canonical node-ID conditions |
| QRG-PLN-009 | Compatibility/API/outcome contracts and Steps 3/4/9 define nullable links, many-to-one cardinality, `UNLINKED_VARIABLE`, and partial status |
| QRG-PLN-010 | Condition Contract and Steps 3/9 add typed native expressions, opaque projections, support matrix, and zero-LLM preservation |
| QRG-PLN-011 | Step 11 and V11 split required authored mechanics fixtures from an optional G6-protected real-questionnaire model benchmark |
| QRG-PLN-012 | Step 11 and V11 add condition exact match and count unresolved expected routes as recall/target failures |
| QRG-PLN-013 | Security contract and Steps 8/10 require safe templates plus complete source-derived string coverage and adversarial negatives |
| QRG-PLN-014 | Routing Result Outcome Table and Steps 9/10 define failed/partial/success, control-exception, empty-inventory, and artifact rules |
| QRG-PLN-015 | Public Routing API Contract and Step 9 define exact `QuestionnaireRouter.route/aroute` signatures separate from `SurveyScribe` |
| QRG-PLN-016 | Step 9 keeps `SourceRegistry.convert() -> SourceDocument` unchanged, adds `convert_with_native()`, owns G4, and tests one real core XLSForm integration |
| QRG-PLN-017 | Canonical Graph Contract and Steps 3/5/6 remove loop edge kind and redundant `is_default` state |
| QRG-PLN-018 | Step 3 freezes every final nested model and Step 10 revalidates a detached snapshot |
| QRG-PLN-019 | Compatibility Contract and Step 10 require equal routing versions plus legacy manifest v1/routed manifest v2 parsers |
| QRG-PLN-020 | Routing Limits contract and Step 8 define the complete per-run cache key |
| QRG-PLN-021 | Routing Limits contract freezes quote, request, inventory, candidate, discrepancy, span, AST, confidence, and degree defaults |
| QRG-PLN-022 | Canonical Graph Contract and Step 6 use one declared/SCC loop region and prohibit all-simple-cycle enumeration |
| QRG-PLN-023 | Steps 2-4 prepare source cases, then freeze models/identity before generating expected mechanics outputs |
| QRG-PLN-024 | Objective, compatibility contract, Steps 2/10, and completion outcome use ordered semantic JSON compatibility; whitespace is not contractual |
| QRG-PLN-025 | G5, Steps 1/12, and V12 use the executable package-excluded 95% coverage command; Step 12 builds and tests package artifacts separately |
| QRG-PLN-026 | Structured-output contract and Step 8 require one shared limiter and control-exception propagation with no publication |
| QRG-PLN-027 | Structured-output contract and Step 8 separate canonical/request schemas, use `ModelCapabilities`, record both hashes, and keep a protected drift smoke |
| QRG-VER-001 | C8 explicitly permits only the bounded per-run parsed cache, prohibits prose in keys/persistent caches, and requires run-end destruction |
| QRG-VER-002 | This plan owns G3 in Step 8 and G4 in Step 9, so `/cg-work` has no older-plan execution handoff |
| QRG-VER-003 | G6 is a lightweight action gate only for an optional protected test capture; Step 11 requires a sanitized dry-run summary and one approval, while deterministic Phase 5 and production runtime configuration remain independent |
| QRG-VER-004 | Step 1 and V1 record remediation evidence in this plan's work report without editing historical reviews or another work report |
| QRG-VER-005 | Public API, Steps 3/4/9, and C13 require a detached SVIS snapshot and typed exact-source binding before any provider call |
| QRG-FINAL-001 | Cross-Plan Scope Approval now permits only the reusable G3 provider and G4 core XLSForm slices without completing broader production-plan steps |
| QRG-FINAL-002 | Step 10 no longer runs package tests; Step 12 builds, prepares the wheelhouse, and then runs them |
| QRG-FINAL-003 | Step 8 uses the `openai` extra and Step 9 uses the `tabular` extra with the explicit XLSForm contract test |
| QRG-FINAL-004 | Step 12 permits one credential-free network wheelhouse preparation and keeps G6 separate from deterministic package evidence |
| QRG-CERT-001 | Testing Strategy and Step 12 claim enforced offline execution only for the exact-wheel install after wheelhouse preparation; other locked local gates claim no provider credentials, not network denial |
| QRG-G6-001 | Requirements R20-R22, the G6 contract, Steps 8-12, V11, and testing strategy distinguish optional mAI Factory-style test capture from administrator-owned final production configuration and behavior |

## Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Routed fields break exact SVIS compatibility | Downstream 1.x consumers fail | Add routed subclasses and typed legacy projection; keep original classes/tests exact |
| Recursive condition schema is rejected by a strict provider | Named provider/model call cannot run | Check the named `ModelCapabilities` row and adapter-transformed request schema; record both hashes; adjust only with approval |
| Same model repeats the same error in both passes | False agreement appears strong | Hide Pass A from Pass B; require source spans; use deterministic graph checks; report agreement as evidence, not proof |
| Reverse pass and reviewer increase cost | Large surveys become expensive | Use fixed risk selection and bounded discrepancy packets; simple sections use one pass |
| Fallback IDs drift after source edits | Cross-version links break | Scope IDs to normalized source version and expose source digest |
| Fuzzy target matching creates false edges | Graph is plausible but wrong | Fuzzy matches remain review candidates and cannot become accepted without cited evidence |
| Implied fallthrough is added across a skip | Incorrect incoming paths | Add sequential edges only after explicit-route analysis and source-order checks |
| Opaque conditions give false branch coverage | Validator reports a complete graph incorrectly | Never use opaque predicates as coverage proof; emit review diagnostic |
| Cycles cause recursion or nontermination | Large questionnaire validation fails | Use iterative graph algorithms; never traverse without visited state; keep runtime execution out of scope |
| Repeated tables explode graph size | High token, memory, and review cost | Use logical repeat templates and expand only structurally distinct rows |
| Source/model prose leaks into logs or sidecars | Privacy incident | Use fixed safe templates, complete request-boundary value inventory, digest-only metadata, adversarial negative tests, and no persistent raw cache |
| Native source logic is flattened and re-inferred | Loss of exact relevance/repeat semantics | Separate native routing protocol and zero-model-call contract tests |
| Reviewer silently rewrites evidence | Audit trail becomes unreliable | Append cited decisions; preserve original evidence; unresolved goes to human review |
| New graph dependency increases package surface | Build and maintenance burden | Use standard-library iterative algorithms; architecture test dependency boundary |
| Quality threshold overfits authored fixtures | Production quality is overstated | Keep deterministic mechanics required; treat protected live capture as optional evidence and limit provider/model claims when it is absent or below threshold |
| Parallel active production plan changes provider/artifact seams | Merge conflict or duplicate architecture | Gate on G2/G3/G4, consume production ports, re-read current seams at phase start, and pause before contract duplication |
| Open source/artifact production findings remain | Routing evidence or publication is unsafe | Step 1 owns G1/G2/G5 closure and blocks dependent work until executed evidence passes |

## Out of Scope

- Changes to existing `SurveyVariable` or `SurveySVIS` fields and default JSON.
- Runtime questionnaire or interview execution.
- Guarantees that every condition compiles to JSON Logic, Python, or a vendor
  expression language.
- Respondent-, household-member-, visit-, or item-instance loop unrolling.
- Interactive graph editor or visualization UI.
- LangChain as a runtime dependency.
- Implementation of every provider adapter or vendor-native questionnaire
  parser.
- Silent autonomous correction without source-cited review evidence.
- Persistent prompt/response caching by default.
- Broad quality claims beyond the approved benchmark corpus.

## Completion Contract

### Outcome

Survey Scribe can produce one versioned, LLM-readable `RoutedSurveySVIS`
artifact with source-grounded routing evidence, accepted canonical directed
multigraph edges, separate disputed candidates, append-only review audit,
validated containment, derived forward/backward adjacency, activation
conditions, native expressions, repeat templates, terminal states, bounded loop
regions, and stable diagnostics. Existing `SurveySVIS` models and legacy JSON
retain exact keys, nesting, JSON value types, defaults, enum values, field order,
and variable order; whitespace is not contractual.

### Verification Surface

| ID | Phase | Evidence Required | Command/Artifact | Required |
|----|-------|-------------------|------------------|----------|
| V1 | 1 | G1 source, G2 artifact, and G5 coverage findings have passing remediation evidence without rewriting historical review status | This plan's work report, source/artifact suites, hard-exit recovery, and package-excluded 95% coverage command | yes |
| V2 | 1 | Source-case fixtures have rights/provenance and existing `SurveySVIS` fields and ordered semantic JSON do not change | Fixture manifest tests and `uv run pytest tests/characterization/test_schema_contract.py` | yes |
| V3 | 1 | Frozen routed models enforce extracted/canonical conditions, hierarchy, accepted/candidate separation, audit, versions, AST shapes, and terminal/adjacency invariants | Routing model unit suite and canonical JSON Schema | yes |
| V4 | 2 | Source IDs, aliases, fallback/evidence IDs, variable links, condition references, and checksummed mechanics outputs are deterministic | Identity, inventory, and mechanics fixture suites | yes |
| V5 | 2 | Reconciliation keeps accepted edges authoritative and handles defaults, sequential paths, multiple incoming paths, native evidence, unresolved candidates, and append-only review | Reconciliation unit suite | yes |
| V6 | 2 | Iterative graph checks handle containment, reachability, terminal paths, bounded loop regions, unsupported cycles, repeat groups, and 1,000+ nodes without simple-cycle enumeration | Validator and scale tests | yes |
| V7 | 3 | Forward, incoming/activation, and reviewer prompts resist source prompt injection and emit bounded strict response models | Prompt contract and canonical-schema tests | yes |
| V8 | 3 | Step 8 supplies G3 provider capability/request-schema checks, adaptive verification, shared concurrency, cache isolation, cancellation, and audited review decisions under fakes/recorded responses | Provider contracts and routing extraction integration suite | yes |
| V9 | 4 | Step 9 supplies G4 through additive source-registry behavior and real core XLSForm relevance/repeat routing that preserves typed native expressions and makes zero LLM calls | Existing `convert()` compatibility, `convert_with_native()` contract, and real core XLSForm integration/support matrix | yes |
| V10 | 4 | Routed main, append-only audit, routed manifest v2, and ordered exact legacy projection recover transactionally, round-trip, and contain no source/model prose outside primary content | Artifact, fault-recovery, redaction, manifest, and compatibility suites | yes |
| V11 | 5 | Deterministic evaluator mechanics, first-pass/post-review separation, unresolved-edge penalties, invention detection, and 1,000-node scale evidence pass without provider credentials | Evaluator unit suite, synthetic mechanics manifest/report, and scale report | yes |
| V12 | final | Ruff, formatting, Pyright, exact 95% branch coverage, package build, strict docs, and exact-wheel checks pass | Step 12 commands, including Step 1 coverage command | yes |

Optional G6 capture is supplemental model-quality evidence, not a numbered
verification requirement. Record it under the work report's G6 status as
`not_run`, `passed`, or `failed`, together with the permitted claim scope.

### Constraints

| ID | Phase | Constraint | Check |
|----|-------|------------|-------|
| C1 | all | Legacy `SurveySVIS` models and ordered JSON semantics remain exact through 1.x; whitespace is not contractual | Characterization and projection tests |
| C2 | all | Only accepted canonical edges are authoritative; candidates/audit are separate; adjacency is derived from accepted edges | Model and reconciliation tests |
| C3 | all | Unclear logic stays `opaque` or unresolved; no unsupported precision | Mechanics, optional captured benchmark, and adversarial tests |
| C4 | 2 | Graph algorithms are iterative and have no new graph runtime dependency | Architecture and 1,000-node tests |
| C5 | 3 | Routing consumes `StructuredProvider`; core imports no Instructor, OpenAI, LangChain, or provider SDK types | Architecture and provider contract tests |
| C6 | 3 | Pass B cannot read Pass A output; reviewer changes always cite source evidence and persist in append-only audit | Orchestration and audit round-trip tests |
| C7 | 4 | Native typed logic never passes through LLM reconstruction | Native adapter call-count tests |
| C8 | all | Source-derived and model prose is allowed only in the primary routed artifact, bounded provider inputs, and the bounded per-run in-memory parsed cache; it is prohibited in cache keys, persistent caches, logs, diagnostics, sidecars, and manifests, and the in-memory cache is destroyed at run end | Safe-template, cache-lifetime, and redaction tests |
| C9 | all | Runtime interview execution and loop unrolling remain out of scope | Public API and dependency checks |
| C10 | final | Python 3.11-3.13 and exact wheel/sdist behavior remain supported | CI and package tests |
| C11 | all | Containment is acyclic and separate from flow; section/repeat targets have explicit entry semantics | Hierarchy and routing tests |
| C12 | 4 | Routed and graph versions are equal `1.0`; legacy manifest remains v1 and routed manifest is v2 | Model, manifest parser, and artifact tests |
| C13 | 4 | Routing uses a detached SVIS snapshot bound to the exact validated source snapshot; mismatch fails before provider calls | Public API, source-binding, mutation, and no-call tests |

### Boundaries

- Allowed: additive routed models, routing package, identity/inventory, condition
  AST, evidence, reconciliation, graph validation, versioned prompts, production
  `StructuredProvider` integration, native routing result wrapper, routed artifact, tests,
  evaluation, and documentation.
- Out of scope: changes to legacy SVIS fields, runtime interview execution, JSON
  Logic execution guarantees, respondent-instance loop expansion, a graph
  editor, LangChain as a runtime dependency, and silent reviewer repair.
- Out of scope: implementing all provider adapters or all vendor-native
  questionnaire parsers in this plan.

### Iteration Policy

1. Close or verify G1, G2, and G5 before dependent routing work.
2. Implement and test compatibility plus pure models before extraction.
3. Implement deterministic identity, reconciliation, and validation before LLM
   orchestration.
4. In Step 8, reuse existing G3 evidence or implement the production provider
   slice there; do not create routing-specific provider, Instructor, credential,
   retry, or capability contracts.
5. In Step 9, reuse existing G4 evidence or implement the bounded core XLSForm
   slice there; keep `SourceRegistry.convert()` unchanged and preserve unsupported
   native expressions without LLM reconstruction.
6. Complete required synthetic mechanics evidence without provider credentials.
   Request lightweight G6 approval only before an optional protected model
   capture. Never add restricted questionnaires or raw capture content.
7. Run at most two focused fix-and-retest rounds for a failed required gate.
8. Under `deviation-policy: ask`, stop before changing public compatibility,
   dependencies, quality thresholds, or native-source scope.
9. Do not mark a phase complete from static inspection; execute its required
   evidence.

### Blocked-Stop Conditions

- G1, G2, or G5 lacks passing remediation evidence after the allowed recovery
  rounds.
- Step 8 cannot supply G3's passing production `StructuredProvider` contract
  after the allowed recovery rounds.
- Step 9 cannot supply G4's passing additive registry/core XLSForm native adapter
  evidence after the allowed recovery rounds.
- Exact legacy model or ordered JSON semantic compatibility cannot be preserved.
- A named provider/model capability row or its adapter-transformed request schema
  cannot represent the bounded extraction response schema without an approved
  schema adjustment.
- Evidence source spans cannot be verified against normalized source blocks.
- Required graph invariants or 1,000-node checks fail after two focused recovery
  rounds.
- An optional G6 capture is selected but its sanitized dry-run summary is not
  approved, the source is not authorized, credentials cannot remain secret, or
  the run would exceed its request/token/output policy. Stop that capture and
  record `not_run`; continue deterministic Phase 5 without provider-quality
  claims.
- A change requires a new runtime dependency or broad provider architecture
  without approval.
- Required verification cannot run, fails after allowed recovery, or would cross
  a protected boundary.
- A required deviation is found while approval is unavailable.
