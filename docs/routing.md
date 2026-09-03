# Questionnaire Routing

Survey Scribe can add a source-grounded routing graph to an existing
`SurveySVIS`. The output is a `RoutedSurveySVIS` with a versioned directed
multigraph, separate evidence and review history, activation conditions,
containment, terminals, and bounded loop definitions.

Routing output is not an interview engine. It does not evaluate respondent data,
unroll repeat instances, guarantee JSON Logic, or choose the next runtime screen.

## Routing and activation

Routing describes movement from one logical node to another. Activation describes
whether an item or group applies. An activation condition does not create a flow
edge unless the source also states a transition.

Accepted edge kinds are:

| Kind | Meaning |
| --- | --- |
| `conditional` | Follow when its canonical condition applies |
| `default` | Follow only when no conditional edge applies |
| `unconditional` | Follow an explicit source-supported transition |
| `sequential` | Follow deterministic source order when no explicit route bypasses it |

Each source node has at most one default edge. Parallel conditional edges are
valid, so the graph is a multigraph rather than a simple graph.

## Graph layers

The accepted `edges` tuple is authoritative. Every accepted endpoint exists and
terminal nodes have no accepted outgoing edges. Node fields such as
`next_node_ids`, `previous_node_ids`, `outgoing_edge_ids`, and
`incoming_edge_ids` are derived only from accepted edges in stable order.

Evidence, candidates, discrepancies, and review decisions are stored in
`routing_audit`. A disputed, rejected, ambiguous, or unresolved route never enters
accepted adjacency, reachability, terminal-path, or loop analysis.

```text
source spans -> evidence -> candidate/discrepancy -> cited review decision
                         \-> accepted edge when source support is sufficient
```

Review decisions are append-only. A replacement cites supplied evidence and
creates a new accepted edge. It does not rewrite the original observation.
`unresolved` keeps the candidate outside the graph and marks it for human review.

## Nodes and hierarchy

Node kinds are `entry`, `question`, `section`, `repeat_group`, and `terminal`.
Terminal classes are `survey_complete`, `screened_out`,
`interview_terminated`, and `unknown_terminal`.

Containment is separate from flow. `parent_node_id` and derived
`child_node_ids` form an acyclic hierarchy. A section or repeat group has an
explicit entry child and one unconditional flow edge to that child.

Repeat groups are logical templates. Household members, consumption items,
visits, plots, and enterprises are not expanded into respondent instances.
Supported source-grounded cycles become bounded loop records. The validator uses
iterative traversal and strongly connected components. It never enumerates all
simple cycles.

## Conditions

Canonical conditions use resolved question node IDs and strict scalar types.
Supported operators include equality and order comparisons, set membership,
answered or selected checks, `all`, `any`, `not`, and `opaque`.

`opaque` preserves unsupported source logic but cannot prove branch coverage.
Conditions are bounded to depth 6 and 100 AST nodes. Boolean values do not equal
integers, and numeric strings are not coerced.

This synthetic conditional/default fragment illustrates the shape:

```json
{
  "source_node_id": "Q1",
  "target_node_id": "Q2",
  "kind": "conditional",
  "condition": {
    "operator": "equals",
    "question_node_id": "Q1",
    "value": "yes",
    "values": null,
    "children": null,
    "raw_text": "If yes, continue to Q2."
  },
  "priority": 0
}
```

A separate default edge from `Q1` supplies the fallthrough. Multiple accepted
edges from different sources can target `Q2`; `previous_node_ids` is the ordered
projection of those incoming accepted edges.

## Route an existing SVIS

First normalize the exact source snapshot and obtain its binding. Then pass the
same source, existing SVIS, and binding to the router:

```python
from datetime import date
from pathlib import Path

from survey_scribe import (
    DataType,
    QuestionnaireRouter,
    SurveySVIS,
    SurveyVariable,
)
from survey_scribe.sources import SourceRegistry

source = Path("questionnaire.xlsx")
survey = SurveySVIS(
    survey_id="TST_2026_ROUTING",
    country_code="TST",
    year=2026,
    survey_name="Synthetic routing example",
    variables=[
        SurveyVariable(
            raw_name="consent",
            data_type=DataType.categorical_single,
            extraction_confidence=1.0,
        ),
        SurveyVariable(
            raw_name="age",
            data_type=DataType.numeric,
            extraction_confidence=1.0,
        ),
    ],
    source_file=source.name,
    source_format="xlsx",
    extraction_date=date(2026, 9, 2),
)
registry = SourceRegistry.default()
conversion = registry.convert_with_native(source, survey)

result = QuestionnaireRouter(None, sources=registry).route(
    source,
    survey,
    source_binding=conversion.source_binding,
)

if result.output is None:
    error_codes = tuple(diagnostic.code for diagnostic in result.diagnostics)
else:
    graph = result.output.routing_graph
    accepted_edges = graph.edges
    audit = graph.routing_audit
    incoming_by_node = {
        node.node_id: node.previous_node_ids
        for node in graph.nodes
        if len(node.previous_node_ids) > 1
    }
    loop_classes = tuple(loop.kind for loop in graph.loops)
    human_review_items = tuple(
        candidate
        for candidate in audit.candidates
        if candidate.status.value == "needs_human_review"
    )
```

`provider=None` is valid only when the native adapter supplies complete routing.
The core XLSForm adapter preserves groups, repeats, relevance, choices, settings,
and native expressions. Supported comparisons, `selected()`, and Boolean
expressions project exactly. Unsupported functions or arithmetic remain typed
native expressions with an `opaque` projection and make no reconstruction call.

For document sources, inject an implementation of `StructuredProvider`.
`QuestionnaireRouter.aroute()` is authoritative for asynchronous applications;
`route()` rejects use inside a running event loop.

## Provider boundary

The routing core consumes only `StructuredProvider.generate()` and normalized
`ProviderResponse` metadata. It does not import OpenAI, Instructor, LangChain, or
another provider SDK. Instructor stays internal to the packaged
OpenAI-compatible adapter.

Each named `ModelCapabilities` row validates strict schema support, transformed
request-schema identity, token limits, and generation settings before source data
is sent. Direct OpenAI or LangChain integrations must adapt to this port rather
than enter the routing core.

Pass A extracts outgoing routes. Risk-selected Pass B independently examines
incoming paths and activation without receiving Pass A output. Review calls
receive only bounded discrepancies and cited evidence. One shared limiter covers
all outbound attempts and retries.

## Artifacts and privacy

The routed main is `<survey_id>_routed_svis.json`. The stable
`<survey_id>_svis.json` remains an exact ordered legacy projection. Routed
generations use manifest version 2; legacy generations remain version 1.

The primary routed artifact can contain questionnaire prose and bounded source
quotes. Logs, diagnostics, sidecars, manifests, cache keys, persistent caches,
and evaluation reports contain only safe codes, metadata, and digests. Raw prompt
or provider response bodies are not persisted by default.

## Schema and evaluation

Export the canonical schema without provider configuration:

```console
survey-scribe schema export routing > questionnaire-routing-graph-v1.0.json
```

The committed schema is checked against Pydantic generation. Deterministic
quality evaluation uses synthetic fixtures and reports first-pass and post-review
metrics separately. See [Evaluation Policy](evaluation.md).

The graph algorithms and evaluator have deterministic 1,000-node/3,000-edge
evidence. Duration and peak memory are recorded as evidence, not enforced as a
fragile cross-platform microbenchmark.

## Test capture and production

G6 is an optional protected live test capture. It requires one human-approved,
sanitized summary before an authorized source reaches a gateway. It is not a
production configuration and is not required for synthetic mechanics, package,
or documentation gates.

Production administrators own provider construction, gateway quota, secret
storage, source authorization, and institutional retention policy. A dynamic
institutional route, including an mAI Factory-style multi-cloud route, supports
only a gateway-route quality claim. An exact backend claim requires a pinned
backend. Returned provider/model metadata can describe an observed dynamic
response but does not authorize an exact-backend quality claim.

## Migration from `skip_condition_raw`

Keep existing `SurveyVariable.skip_condition_raw` values unchanged for legacy
consumers. Use `RoutedSurveyVariable.routing_node_id` to link each variable to a
canonical question node, and use accepted `RoutingEdge.condition` for structured
flow. A variable that cannot be linked remains in source order with a null link
and a visible partial-result diagnostic.

No legacy field is deprecated by the additive routed contract.

For a complete machine-valid contract, export the schema and validate the routed
main against it. The package tests generate a synthetic conditional/default
XLSForm, validate native evidence and variable links, publish manifest v2, and
compare the legacy projection byte for byte. The committed routing fixture corpus
also covers multiple incoming paths, supported loops, unresolved targets, and
terminal classes.

## Known limits

- Runtime interview execution and respondent-instance loop expansion are out of scope.
- `opaque` conditions are preserved but not executable branch-coverage proof.
- Fuzzy or unresolved targets remain candidates until cited review resolves them.
- Native support is versioned and does not cover every vendor function or parser.
- A synthetic mechanics pass does not establish live provider or exact-model quality.
