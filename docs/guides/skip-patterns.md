# Skip Patterns

Survey Scribe represents questionnaire flow. It does not execute an interview or
apply flow to respondent answers. This guide shows how common printed and
XLSForm patterns appear in routed SVIS output.

## Three distinct fields

| Representation | Purpose | Executable by Survey Scribe |
| --- | --- | --- |
| `SurveyVariable.skip_condition_raw` | Preserve source skip or relevance text | No |
| `RoutingNode.activation_condition` | State whether a node applies | No |
| `RoutingEdge.condition` | Describe a source-supported transition | No |

Activation does not create a flow edge. A transition needs separate source
evidence.

## Pattern summary

| Questionnaire pattern | Routed representation |
| --- | --- |
| Yes/no relevance | Activation condition on the dependent node |
| Conditional branch | `conditional` edge plus a `default` or other fallthrough |
| Section jump | Source-supported edge to a section or question node |
| Screening termination | Conditional edge to a `screened_out` terminal |
| End interview | Edge to an `interview_terminated` terminal |
| Multiple incoming paths | Several accepted edges with one target |
| Roster or repeat | Repeat-group containment and a logical loop record |
| Unsupported expression | `opaque` condition and audit evidence |
| Ambiguous printed target | Candidate edge, discrepancy, and review item |

## Yes/no relevance

An XLSForm expression such as `${consent} = 'yes'` becomes an activation
condition on the dependent question:

```json
{
  "operator": "equals",
  "question_node_id": "<consent-node-id>",
  "value": "yes"
}
```

Native XLSForm routing keeps the normal sequential transition. The relevance
expression does not become a conditional jump edge.

Empty-string checks have exact projections:

| XLSForm expression | Operator |
| --- | --- |
| `${question} = ''` | `not_answered` |
| `${question} != ''` | `answered` |

No package function evaluates these operators against a completed record.

## Conditional branch and fallthrough

A conditional branch uses one accepted `conditional` edge:

```json
{
  "source_node_id": "Q1",
  "target_node_id": "Q4",
  "kind": "conditional",
  "condition": {
    "operator": "equals",
    "question_node_id": "Q1",
    "value": "no",
    "raw_text": "If no, go to Q4."
  },
  "priority": 0
}
```

A separate `default` edge can represent all other values. Each source node can
have at most one accepted default edge.

The validator can prove finite branch coverage only for simple conditions on one
question with known categorical values. Nested Boolean conditions, selected
checks, unknown codes, and opaque logic can require review even when the source
looks complete.

## Explicit jump over questions

For a printed instruction such as "If no, go to Q4", the accepted graph can
contain `Q1 -> Q4`. A sequential `Q1 -> Q2` fallthrough is valid only when it is
the immediate next logical item in the same parent and no explicit route bypasses
it for that path.

Survey Scribe does not infer backward sequential flow. A backward edge needs
direct source support, such as a documented correction return.

## Screening and other terminals

Terminal classes are:

- `survey_complete`
- `screened_out`
- `interview_terminated`
- `unknown_terminal`

A terminal cannot have an accepted outgoing edge. For non-XLSForm documents, the
public fallback inventory creates one `survey_complete` terminal only. It does
not discover arbitrary screening or termination nodes. Do not claim those
terminal classes were checked unless they are present in the inventory and have
source evidence.

## Multiple incoming paths

Several accepted edges can target the same node. The node's
`previous_node_ids` field is a stable projection of those accepted incoming
edges. Incoming-only model evidence stays in the audit until review confirms a
source-supported edge.

Use the audit to distinguish accepted truth from unresolved evidence:

```python
graph = routed.routing_graph
accepted = graph.edges
candidate_edges = graph.routing_audit.candidate_edges
discrepancies = graph.routing_audit.discrepancies
decisions = graph.routing_audit.review_decisions
```

## Repeats and rosters

A repeat group is one logical template. It does not expand into household
members, visits, plots, products, or other respondent instances.

Current native XLSForm repeat records use `RepeatKind.other`. Their collection
source, continuation condition, and maximum iteration count are unset. A
preserved XLSForm `repeat_count` does not become an executable maximum.

A loop record proves topology and source evidence. It is not a runtime iterator.
Declared repeat containment can create a loop record without a return edge.

## Supported XLSForm conditions

The native parser projects these expression forms:

- `=`, `!=`, `>`, `>=`, `<`, and `<=`
- `selected(...)` and `not(selected(...))`
- Boolean `and`, `or`, and `not`
- Empty-string answered and not-answered checks
- Quoted strings, integers, decimal values, `true()`, and `false()`

Arithmetic, other XPath functions, dynamic instances, constraints,
calculations, and choice filters are not evaluated. Unsupported or unresolved
logic becomes `opaque`. If one child of an `and` or `or` expression is opaque,
the full expression becomes opaque.

## Route an existing SVIS

Use the exact source snapshot for normalization and routing:

```python
from datetime import date
from pathlib import Path

from survey_scribe import QuestionnaireRouter
from survey_scribe.sources import SourceRegistry

source = Path("questionnaire.xlsx")
registry = SourceRegistry.default()
native = registry.convert_for_svis(
    source,
    extraction_date=date.today(),
)
if native.svis is None:
    raise RuntimeError("The workbook is not a supported XLSForm")

conversion = registry.convert_with_native(source, native.svis)
result = QuestionnaireRouter(None, sources=registry).route(
    source,
    native.svis,
    source_binding=conversion.source_binding,
)

if result.output is not None:
    graph = result.output.routing_graph
    accepted_edges = graph.edges
    review_queue = graph.routing_audit.candidate_edges
```

`provider=None` is valid only when native routing is complete. Other documents
need a `StructuredProvider`.
The routing source binding accepts the native `source_format="xlsform"` identity
for a validated XLSX snapshot. Do not modify the source between conversion and
routing.

## Ambiguous and unsupported routes

Ambiguous targets, unresolved references, fuzzy matches, opaque conditions,
conflicting evidence, multiple defaults, and unsupported inferred cycles remain
outside accepted adjacency. They stay in candidate edges, discrepancies,
evidence, diagnostics, and append-only review decisions.

The provider-backed routing sequence has separate forward, incoming, and review
phases. The review phase can confirm, replace, reject, or keep a candidate
unresolved. It does not delete the original observation.

## Known limits

- Routing does not evaluate respondent values.
- Opaque conditions are not executable branch proof.
- Repeats are templates and are not respondent instances.
- The non-XLSForm fallback inventory does not discover arbitrary sections, repeat groups, or terminal classes.
- There is no public API to inject human review decisions through `QuestionnaireRouter`.
- Native support is versioned and does not cover every vendor expression.
- Synthetic graph tests do not establish live model quality.

See the [Routing Model](../routing.md) for graph invariants, evidence, artifacts,
and schema export. See [Completed Questionnaires](completed-questionnaires.md)
for the answer-data boundary.
