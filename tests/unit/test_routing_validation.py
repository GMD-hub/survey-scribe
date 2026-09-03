"""Deterministic graph integrity, loop analysis, and questionnaire-scale evidence."""

from __future__ import annotations

import platform
import tracemalloc
from collections.abc import Callable, Iterable, Mapping
from time import perf_counter

from survey_scribe.models.routing import (
    CandidateEdge,
    CandidateStatus,
    Containment,
    DiscrepancyKind,
    EdgeKind,
    EvidenceRecord,
    InventoryItem,
    LoopKind,
    QuestionnaireRoutingGraph,
    RepeatKind,
    RepeatSpec,
    RoutingAudit,
    RoutingDiagnostic,
    RoutingDiscrepancy,
    RoutingEdge,
    RoutingNode,
    RoutingSourceBinding,
    TerminalKind,
)
from survey_scribe.routing.algorithms import (
    iterative_reachable,
    iterative_strongly_connected_components,
)
from survey_scribe.routing.contracts import (
    CanonicalRoutingCondition,
    ConditionOperator,
    EvidenceOrigin,
    EvidencePerspective,
    ExtractedRoutingCondition,
    ItemReference,
    NodeKind,
    SourceSpan,
    TransitionEvidence,
    TransitionKind,
)
from survey_scribe.routing.reconcile import reconcile_routing_graph
from survey_scribe.routing.validate import (
    analyze_routing_components,
    validate_containment,
    validate_routing_graph,
)


def _reference(item_id: str, kind: NodeKind = NodeKind.question) -> ItemReference:
    return ItemReference(
        raw_reference=item_id,
        source_item_id=item_id,
        canonical_hint=None,
        section_path=("Main",),
        node_kind=kind,
    )


def _span(identifier: str = "1") -> SourceSpan:
    return SourceSpan(
        span_id=f"span:{identifier}",
        block_id="block:1",
        source_name="questionnaire.txt",
        pages=(1,),
        sheet=None,
        row_start=None,
        row_end=None,
        source_quote="A synthetic routing instruction.",
    )


def _evidence(*, explicitly_stated: bool = True) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id="evidence:1",
        observation=TransitionEvidence(
            evidence_type="transition",
            local_id="local:1",
            perspective=EvidencePerspective.outgoing,
            origin=EvidenceOrigin.forward_extraction,
            source=_reference("Q1"),
            target=_reference("Q2"),
            transition_kind=TransitionKind.unconditional,
            condition=None,
            source_span=_span(),
            native_expression=None,
            explicitly_stated=explicitly_stated,
            confidence=1.0,
            ambiguity_note=None,
        ),
    )


def _binding() -> RoutingSourceBinding:
    return RoutingSourceBinding(
        survey_id="TST_2024_SYNTH",
        source_name="questionnaire.txt",
        media_type="text/plain",
        snapshot_sha256="a" * 64,
        source_conversion_schema_version="1.0",
    )


def _audit(
    *,
    explicitly_stated: bool = True,
    candidates: tuple[CandidateEdge, ...] = (),
    discrepancies: tuple[RoutingDiscrepancy, ...] = (),
) -> RoutingAudit:
    record = _evidence(explicitly_stated=explicitly_stated)
    return RoutingAudit(
        source_binding=_binding(),
        inventory=(),
        source_spans=(record.observation.source_span,),
        evidence=(record,),
        candidate_edges=candidates,
        discrepancies=discrepancies,
        review_decisions=(),
    )


def _condition(
    question_node_id: str,
    value: str | int = 1,
    *,
    operator: ConditionOperator = ConditionOperator.equals,
    values: tuple[str | int, ...] | None = None,
) -> CanonicalRoutingCondition:
    return CanonicalRoutingCondition(
        operator=operator,
        question_node_id=question_node_id if operator is not ConditionOperator.opaque else None,
        value=value if operator is ConditionOperator.equals else None,
        values=values if operator is ConditionOperator.in_set else None,
        children=None,
        raw_text="synthetic condition",
    )


def _repeat_spec(kind: RepeatKind = RepeatKind.household_member) -> RepeatSpec:
    return RepeatSpec(
        repeat_kind=kind,
        iterator_label="item",
        collection_source="synthetic collection",
        continuation_condition=None,
        maximum_iterations=100,
    )


def _node(
    node_id: str,
    kind: NodeKind = NodeKind.question,
    *,
    parent: str | None = None,
    children: tuple[str, ...] = (),
    entry_child: str | None = None,
    repeat_kind: RepeatKind = RepeatKind.household_member,
    activation_condition: CanonicalRoutingCondition | None = None,
    next_node_ids: tuple[str, ...] = (),
    previous_node_ids: tuple[str, ...] = (),
    outgoing_edge_ids: tuple[str, ...] = (),
    incoming_edge_ids: tuple[str, ...] = (),
) -> RoutingNode:
    return RoutingNode(
        node_id=node_id,
        kind=kind,
        source_item_id=node_id if kind is NodeKind.question else None,
        raw_name=node_id if kind is NodeKind.question else None,
        label=node_id,
        terminal_kind=TerminalKind.survey_complete if kind is NodeKind.terminal else None,
        activation_condition=activation_condition,
        repeat_spec=_repeat_spec(repeat_kind) if kind is NodeKind.repeat_group else None,
        containment=Containment(
            parent_node_id=parent,
            child_node_ids=children,
            entry_child_node_id=entry_child,
        ),
        next_node_ids=next_node_ids,
        previous_node_ids=previous_node_ids,
        outgoing_edge_ids=outgoing_edge_ids,
        incoming_edge_ids=incoming_edge_ids,
    )


def _edge(
    edge_id: str,
    source: str,
    target: str,
    *,
    kind: EdgeKind = EdgeKind.unconditional,
    condition: CanonicalRoutingCondition | None = None,
    priority: int | None = None,
) -> RoutingEdge:
    return RoutingEdge(
        edge_id=edge_id,
        source_node_id=source,
        target_node_id=target,
        kind=kind,
        condition=condition,
        priority=priority,
        evidence_ids=("evidence:1",),
        confidence=1.0,
        review_decision_id=None,
    )


def _with_adjacency(
    nodes: Iterable[RoutingNode],
    edges: tuple[RoutingEdge, ...],
) -> tuple[RoutingNode, ...]:
    materialized = tuple(nodes)
    outgoing: dict[str, list[RoutingEdge]] = {node.node_id: [] for node in materialized}
    incoming: dict[str, list[RoutingEdge]] = {node.node_id: [] for node in materialized}
    for edge in edges:
        outgoing[edge.source_node_id].append(edge)
        incoming[edge.target_node_id].append(edge)
    return tuple(
        node.model_copy(
            update={
                "next_node_ids": tuple(
                    dict.fromkeys(edge.target_node_id for edge in outgoing[node.node_id])
                ),
                "previous_node_ids": tuple(
                    dict.fromkeys(edge.source_node_id for edge in incoming[node.node_id])
                ),
                "outgoing_edge_ids": tuple(edge.edge_id for edge in outgoing[node.node_id]),
                "incoming_edge_ids": tuple(edge.edge_id for edge in incoming[node.node_id]),
            }
        )
        for node in materialized
    )


def _graph(
    nodes: Iterable[RoutingNode],
    edges: tuple[RoutingEdge, ...],
    *,
    entries: tuple[str, ...] = ("entry",),
    audit: RoutingAudit | None = None,
) -> QuestionnaireRoutingGraph:
    materialized_nodes = tuple(nodes)
    explicitly_stated = (
        audit.evidence[0].observation.explicitly_stated
        if audit is not None
        and audit.evidence
        and isinstance(audit.evidence[0].observation, TransitionEvidence)
        else True
    )
    normalized_edges = tuple(
        edge.model_copy(
            update={"evidence_ids": ("evidence:1" if index == 0 else f"evidence:{edge.edge_id}",)}
        )
        for index, edge in enumerate(edges)
    )
    inventory = tuple(
        InventoryItem(
            node_id=node.node_id,
            source_item_id=node.node_id,
            raw_reference=node.node_id,
            section_path=("Main",),
            source_order=index,
            block_ids=("block:1",),
            kind=node.kind,
            repeat_group_node_id=(
                node.containment.parent_node_id
                if node.containment.parent_node_id is not None
                and next(
                    candidate
                    for candidate in materialized_nodes
                    if candidate.node_id == node.containment.parent_node_id
                ).kind
                is NodeKind.repeat_group
                else None
            ),
            parent_node_id=node.containment.parent_node_id,
            linked_variable_indices=(),
        )
        for index, node in enumerate(materialized_nodes)
    )
    nodes_by_id = {node.node_id: node for node in materialized_nodes}
    evidence = tuple(
        _edge_evidence(
            edge,
            nodes_by_id,
            evidence_id=edge.evidence_ids[0],
            span_id=str(index + 1),
            explicitly_stated=explicitly_stated,
        )
        for index, edge in enumerate(normalized_edges)
    )
    base_audit = audit or _audit()
    graph_audit = RoutingAudit(
        source_binding=base_audit.source_binding,
        inventory=inventory,
        source_spans=tuple(record.observation.source_span for record in evidence),
        evidence=evidence,
        candidate_edges=base_audit.candidate_edges,
        discrepancies=base_audit.discrepancies,
        review_decisions=base_audit.review_decisions,
    )
    return QuestionnaireRoutingGraph(
        schema_version="1.0",
        entry_node_ids=entries,
        nodes=_with_adjacency(materialized_nodes, normalized_edges),
        edges=normalized_edges,
        loops=(),
        diagnostics=(),
        routing_audit=graph_audit,
    )


def _edge_evidence(
    edge: RoutingEdge,
    nodes: Mapping[str, RoutingNode],
    *,
    evidence_id: str,
    span_id: str,
    explicitly_stated: bool,
) -> EvidenceRecord:
    condition = _extracted_condition(edge.condition)
    return EvidenceRecord(
        evidence_id=evidence_id,
        observation=TransitionEvidence(
            evidence_type="transition",
            local_id=f"local:{edge.edge_id}",
            perspective=EvidencePerspective.outgoing,
            origin=EvidenceOrigin.forward_extraction,
            source=_reference(edge.source_node_id, nodes[edge.source_node_id].kind),
            target=_reference(edge.target_node_id, nodes[edge.target_node_id].kind),
            transition_kind=TransitionKind(edge.kind.value),
            condition=condition,
            source_span=_span(span_id),
            native_expression=None,
            explicitly_stated=explicitly_stated,
            confidence=1.0,
            ambiguity_note=None,
        ),
    )


def _extracted_condition(
    condition: CanonicalRoutingCondition | None,
) -> ExtractedRoutingCondition | None:
    if condition is None:
        return None
    return ExtractedRoutingCondition(
        operator=condition.operator,
        item_reference=(
            _reference(condition.question_node_id)
            if condition.question_node_id is not None
            else None
        ),
        value=condition.value,
        values=condition.values,
        children=(
            tuple(
                child
                for item in condition.children
                if (child := _extracted_condition(item)) is not None
            )
            if condition.children is not None
            else None
        ),
        raw_text=condition.raw_text,
    )


def _codes(diagnostics: Iterable[RoutingDiagnostic]) -> tuple[str, ...]:
    return tuple(item.code for item in diagnostics)


def test_iterative_traversal_and_scc_are_deterministic_in_declared_node_order() -> None:
    node_ids = ("a", "b", "c", "d", "e")
    adjacency = {
        "a": ("b", "d"),
        "b": ("c",),
        "c": ("b", "d"),
        "d": ("e",),
        "e": ("d",),
    }

    assert iterative_reachable(("a",), adjacency) == node_ids
    assert iterative_strongly_connected_components(node_ids, adjacency) == (
        ("a",),
        ("b", "c"),
        ("d", "e"),
    )
    assert iterative_strongly_connected_components(node_ids, adjacency) == (
        ("a",),
        ("b", "c"),
        ("d", "e"),
    )


def test_valid_dag_reaches_a_terminal_without_diagnostics() -> None:
    nodes = (
        _node("entry", NodeKind.entry),
        _node("q1"),
        _node("terminal", NodeKind.terminal),
    )
    edges = (
        _edge("e1", "entry", "q1"),
        _edge("e2", "q1", "terminal"),
    )

    validated = validate_routing_graph(_graph(nodes, edges))

    assert validated.loops == ()
    assert validated.diagnostics == ()


def test_structural_diagnostics_are_stable_and_precede_semantic_checks() -> None:
    entry = _node("entry", NodeKind.entry, outgoing_edge_ids=("wrong",))
    q1 = _node("q1")
    terminal = _node("terminal", NodeKind.terminal)
    edges = (
        _edge("default-1", "entry", "q1", kind=EdgeKind.default),
        _edge("default-2", "entry", "q1", kind=EdgeKind.default),
        _edge("dangling", "q1", "missing"),
    )

    first = analyze_routing_components(
        nodes=(entry, q1, q1, terminal),
        edges=edges,
        entry_node_ids=("entry",),
        routing_audit=_audit(),
    )
    second = analyze_routing_components(
        nodes=(entry, q1, q1, terminal),
        edges=edges,
        entry_node_ids=("entry",),
        routing_audit=_audit(),
    )

    assert _codes(first.diagnostics)[:5] == (
        "DUPLICATE_NODE_ID",
        "DUPLICATE_EDGE",
        "DANGLING_TARGET",
        "ADJACENCY_INDEX_MISMATCH",
        "MULTIPLE_DEFAULTS",
    )
    assert first == second
    assert first.has_structural_errors


def test_entry_terminal_and_containment_corruption_are_diagnosed_before_construction() -> None:
    terminal = _node("terminal", NodeKind.terminal)
    question = _node("q1").model_copy(
        update={
            "containment": Containment(
                parent_node_id="missing-parent",
                child_node_ids=(),
                entry_child_node_id=None,
            )
        }
    )
    section = _node(
        "section",
        NodeKind.section,
        children=("q1",),
        entry_child="q1",
    )
    analysis = analyze_routing_components(
        nodes=(terminal, question, section),
        edges=(_edge("terminal-out", "terminal", "q1"),),
        entry_node_ids=("missing-entry", "q1"),
        routing_audit=_audit(),
    )

    assert _codes(analysis.diagnostics)[:5] == (
        "UNKNOWN_ENTRY_NODE",
        "ADJACENCY_INDEX_MISMATCH",
        "CONTAINMENT_DANGLING_PARENT",
        "CONTAINMENT_INDEX_MISMATCH",
        "CONTAINMENT_ENTRY_INVALID",
    )
    assert "TERMINAL_OUTGOING" in _codes(analysis.diagnostics)


def test_audit_target_incoming_and_activation_conflicts_get_fixed_diagnostics() -> None:
    candidate = CandidateEdge(
        candidate_id="candidate:1",
        source_node_id="q1",
        target_node_id=None,
        target_reference=_reference("unclear target"),
        kind=EdgeKind.unconditional,
        condition=None,
        priority=None,
        evidence_ids=("evidence:1",),
        confidence=0.5,
        status=CandidateStatus.needs_human_review,
    )
    discrepancies = (
        RoutingDiscrepancy(
            discrepancy_id="discrepancy:ambiguous",
            kind=DiscrepancyKind.ambiguous_target,
            candidate_ids=(candidate.candidate_id,),
            evidence_ids=("evidence:1",),
            source_span_ids=("span:1",),
            summary="A bounded target discrepancy.",
            needs_human_review=True,
            resolved_by_decision_id=None,
        ),
        RoutingDiscrepancy(
            discrepancy_id="discrepancy:incoming",
            kind=DiscrepancyKind.incoming_mismatch,
            candidate_ids=(candidate.candidate_id,),
            evidence_ids=("evidence:1",),
            source_span_ids=("span:1",),
            summary="A bounded incoming discrepancy.",
            needs_human_review=False,
            resolved_by_decision_id=None,
        ),
        RoutingDiscrepancy(
            discrepancy_id="discrepancy:activation",
            kind=DiscrepancyKind.activation_routing_conflict,
            candidate_ids=(candidate.candidate_id,),
            evidence_ids=("evidence:1",),
            source_span_ids=("span:1",),
            summary="A bounded activation discrepancy.",
            needs_human_review=False,
            resolved_by_decision_id=None,
        ),
    )
    audit = _audit(candidates=(candidate,), discrepancies=discrepancies)
    nodes = (
        _node("entry", NodeKind.entry),
        _node("q1"),
        _node("terminal", NodeKind.terminal),
    )
    edges = (_edge("e1", "entry", "terminal"),)

    validated = validate_routing_graph(_graph(nodes, edges, audit=audit))

    assert _codes(validated.diagnostics) == (
        "AMBIGUOUS_TARGET",
        "UNREACHABLE_NODE",
        "INCOMING_EVIDENCE_MISMATCH",
        "ACTIVATION_ROUTING_CONFLICT",
    )
    assert validated.diagnostics[0].candidate_ids == ("candidate:1",)


def test_reachability_dead_end_and_terminal_path_diagnostics_are_entry_scoped() -> None:
    nodes = (
        _node("entry", NodeKind.entry),
        _node("dead-end"),
        _node("unreachable"),
        _node("terminal", NodeKind.terminal),
    )
    edges = (_edge("e1", "entry", "dead-end"),)

    validated = validate_routing_graph(_graph(nodes, edges))

    assert _codes(validated.diagnostics) == (
        "UNREACHABLE_NODE",
        "DEAD_END_NONTERMINAL",
        "NO_TERMINAL_PATH",
    )
    assert validated.diagnostics[0].node_ids == ("unreachable", "terminal")
    assert validated.diagnostics[1].node_ids == ("dead-end",)
    assert validated.diagnostics[-1].node_ids == ("entry", "dead-end")


def test_condition_references_and_known_category_codes_are_checked_without_coercion() -> None:
    nodes = (
        _node("entry", NodeKind.entry),
        _node("controller"),
        _node("branch"),
        _node("terminal", NodeKind.terminal),
    )
    edges = (
        _edge("e1", "entry", "branch"),
        _edge(
            "unknown-reference",
            "branch",
            "terminal",
            kind=EdgeKind.conditional,
            condition=_condition("missing", 1),
        ),
        _edge(
            "unknown-code",
            "controller",
            "terminal",
            kind=EdgeKind.conditional,
            condition=_condition("controller", "1"),
        ),
    )

    analysis = analyze_routing_components(
        nodes=nodes,
        edges=edges,
        entry_node_ids=("entry",),
        routing_audit=_audit(),
        known_category_codes={"controller": (1, 2)},
    )

    assert "CONDITION_UNKNOWN_REFERENCE" in _codes(analysis.diagnostics)
    assert "CONDITION_VALUE_NOT_IN_CATEGORIES" in _codes(analysis.diagnostics)


def test_node_conditions_use_the_same_reference_and_category_checks_as_edges() -> None:
    activation = _condition("controller", "unknown")
    nodes = (
        _node("entry", NodeKind.entry),
        _node("controller"),
        _node("activated", activation_condition=activation),
        _node("terminal", NodeKind.terminal),
    )
    edges = (
        _edge("e1", "entry", "activated"),
        _edge("e2", "activated", "terminal"),
    )
    analysis = analyze_routing_components(
        nodes=_with_adjacency(nodes, edges),
        edges=edges,
        entry_node_ids=("entry",),
        routing_audit=_audit(),
        known_category_codes={"controller": (1, 2)},
    )

    code_diagnostic = next(
        item for item in analysis.diagnostics if item.code == "CONDITION_VALUE_NOT_IN_CATEGORIES"
    )
    assert code_diagnostic.node_ids == ("activated",)


def test_branch_coverage_is_proved_only_for_complete_finite_known_categories() -> None:
    nodes = (
        _node("entry", NodeKind.entry),
        _node("controller"),
        _node("branch"),
        _node("terminal", NodeKind.terminal),
    )
    base = (
        _edge("e1", "entry", "branch"),
        _edge(
            "b1",
            "branch",
            "terminal",
            kind=EdgeKind.conditional,
            condition=_condition("controller", 1),
        ),
        _edge(
            "b2",
            "branch",
            "terminal",
            kind=EdgeKind.conditional,
            condition=_condition("controller", 2),
        ),
    )
    known: Mapping[str, tuple[str | int | float | bool, ...]] = {"controller": (1, 2, 3)}

    uncovered = analyze_routing_components(
        nodes=nodes,
        edges=base,
        entry_node_ids=("entry",),
        routing_audit=_audit(),
        known_category_codes=known,
    )
    complete = analyze_routing_components(
        nodes=nodes,
        edges=base
        + (
            _edge(
                "b3",
                "branch",
                "terminal",
                kind=EdgeKind.conditional,
                condition=_condition("controller", 3),
            ),
        ),
        entry_node_ids=("entry",),
        routing_audit=_audit(),
        known_category_codes=known,
    )
    unknown_domain = analyze_routing_components(
        nodes=nodes,
        edges=base,
        entry_node_ids=("entry",),
        routing_audit=_audit(),
    )

    assert "UNCOVERED_BRANCH" in _codes(uncovered.diagnostics)
    assert "UNCOVERED_BRANCH" not in _codes(complete.diagnostics)
    assert "UNCOVERED_BRANCH" in _codes(unknown_domain.diagnostics)


def test_finite_complements_and_default_edges_cover_without_false_overlap() -> None:
    nodes = (
        _node("entry", NodeKind.entry),
        _node("controller"),
        _node("branch"),
        _node("terminal", NodeKind.terminal),
    )
    not_one = CanonicalRoutingCondition(
        operator=ConditionOperator.not_equals,
        question_node_id="controller",
        value=1,
        values=None,
        children=None,
        raw_text="controller is not one",
    )
    edges = (
        _edge("e1", "entry", "branch"),
        _edge(
            "one",
            "branch",
            "terminal",
            kind=EdgeKind.conditional,
            condition=_condition("controller", 1),
        ),
        _edge(
            "not-one",
            "branch",
            "terminal",
            kind=EdgeKind.conditional,
            condition=not_one,
        ),
    )
    complete = analyze_routing_components(
        nodes=nodes,
        edges=edges,
        entry_node_ids=("entry",),
        routing_audit=_audit(),
        known_category_codes={"controller": (1, 2, 3)},
    )
    defaulted = analyze_routing_components(
        nodes=nodes,
        edges=edges[:-1] + (_edge("default", "branch", "terminal", kind=EdgeKind.default),),
        entry_node_ids=("entry",),
        routing_audit=_audit(),
    )

    assert "UNCOVERED_BRANCH" not in _codes(complete.diagnostics)
    assert "OVERLAPPING_BRANCH_UNPROVEN" not in _codes(complete.diagnostics)
    assert "UNCOVERED_BRANCH" not in _codes(defaulted.diagnostics)


def test_later_finite_category_metadata_recomputes_validator_owned_coverage() -> None:
    nodes = (
        _node("entry", NodeKind.entry),
        _node("controller"),
        _node("branch"),
        _node("terminal", NodeKind.terminal),
    )
    edges = (
        _edge("e1", "entry", "branch"),
        _edge(
            "b1",
            "branch",
            "terminal",
            kind=EdgeKind.conditional,
            condition=_condition("controller", 1),
        ),
        _edge(
            "b2",
            "branch",
            "terminal",
            kind=EdgeKind.conditional,
            condition=_condition("controller", 2),
        ),
    )
    initial = validate_routing_graph(_graph(nodes, edges))

    revalidated = validate_routing_graph(
        initial,
        known_category_codes={"controller": (1, 2)},
    )

    assert "UNCOVERED_BRANCH" in _codes(initial.diagnostics)
    assert "UNCOVERED_BRANCH" not in _codes(revalidated.diagnostics)


def test_opaque_and_overlapping_conditions_never_prove_branch_coverage() -> None:
    nodes = (
        _node("entry", NodeKind.entry),
        _node("controller"),
        _node("branch"),
        _node("terminal", NodeKind.terminal),
    )
    opaque = CanonicalRoutingCondition(
        operator=ConditionOperator.opaque,
        question_node_id=None,
        value=None,
        values=None,
        children=None,
        raw_text="unsupported expression",
    )
    edges = (
        _edge("e1", "entry", "branch"),
        _edge(
            "opaque",
            "branch",
            "terminal",
            kind=EdgeKind.conditional,
            condition=opaque,
        ),
        _edge(
            "set-one",
            "branch",
            "terminal",
            kind=EdgeKind.conditional,
            condition=_condition(
                "controller",
                operator=ConditionOperator.in_set,
                values=(1, 2),
            ),
        ),
        _edge(
            "set-two",
            "branch",
            "terminal",
            kind=EdgeKind.conditional,
            condition=_condition(
                "controller",
                operator=ConditionOperator.in_set,
                values=(2, 3),
            ),
        ),
    )

    analysis = analyze_routing_components(
        nodes=nodes,
        edges=edges,
        entry_node_ids=("entry",),
        routing_audit=_audit(),
        known_category_codes={"controller": (1, 2, 3)},
    )

    assert "UNCOVERED_BRANCH" in _codes(analysis.diagnostics)
    assert "OVERLAPPING_BRANCH_UNPROVEN" in _codes(analysis.diagnostics)


def _repeat_graph(kind: RepeatKind = RepeatKind.household_member) -> QuestionnaireRoutingGraph:
    nodes = (
        _node("entry", NodeKind.entry),
        _node(
            "repeat",
            NodeKind.repeat_group,
            children=("item",),
            entry_child="item",
            repeat_kind=kind,
        ),
        _node("item", parent="repeat"),
        _node("terminal", NodeKind.terminal),
    )
    edges = (
        _edge("enter-repeat", "entry", "repeat"),
        _edge("enter-item", "repeat", "item"),
        _edge(
            "return",
            "item",
            "item",
            kind=EdgeKind.conditional,
            condition=_condition("item", 1),
        ),
        _edge("exit", "item", "terminal", kind=EdgeKind.default),
    )
    return _graph(nodes, edges)


def test_declared_repeat_group_and_repeat_until_have_one_bounded_record_each() -> None:
    repeat = validate_routing_graph(_repeat_graph())
    repeat_until = validate_routing_graph(_repeat_graph(RepeatKind.until_condition))

    assert len(repeat.loops) == 1
    assert repeat.loops[0].kind is LoopKind.repeat_group
    assert repeat.loops[0].member_node_ids == ("repeat", "item")
    assert repeat.loops[0].entry_edge_ids == ("enter-repeat",)
    assert repeat.loops[0].member_edge_ids == ("enter-item",)
    assert repeat.loops[0].return_edge_ids == ("return",)
    assert repeat.loops[0].exit_edge_ids == ("exit",)
    assert repeat_until.loops[0].kind is LoopKind.repeat_until


def test_declared_repeat_without_return_edge_still_has_one_logical_loop_record() -> None:
    graph = _repeat_graph()
    edges = tuple(edge for edge in graph.edges if edge.edge_id != "return")
    declared_only = _graph(graph.nodes, edges)

    validated = validate_routing_graph(declared_only)

    assert len(validated.loops) == 1
    assert validated.loops[0].kind is LoopKind.repeat_group
    assert validated.loops[0].return_edge_ids == ()


def test_supported_correction_and_dense_scc_do_not_enumerate_simple_cycles() -> None:
    nodes = [_node("entry", NodeKind.entry)]
    nodes.extend(_node(f"q{index}") for index in range(8))
    nodes.append(_node("terminal", NodeKind.terminal))
    edges = [_edge("enter", "entry", "q0")]
    for source in range(8):
        for target in range(8):
            if source != target:
                edges.append(_edge(f"dense:{source}:{target}", f"q{source}", f"q{target}"))
    edges.append(_edge("exit", "q7", "terminal"))

    validated = validate_routing_graph(_graph(nodes, tuple(edges)))

    assert len(validated.loops) == 1
    assert validated.loops[0].kind is LoopKind.other
    assert len(validated.loops[0].member_node_ids) == 8
    assert len(validated.loops[0].member_edge_ids) + len(validated.loops[0].return_edge_ids) == 56


def test_two_node_supported_cycle_is_a_correction_return_region() -> None:
    nodes = (
        _node("entry", NodeKind.entry),
        _node("q1"),
        _node("q2"),
        _node("terminal", NodeKind.terminal),
    )
    edges = (
        _edge("enter", "entry", "q1"),
        _edge("forward", "q1", "q2"),
        _edge("return", "q2", "q1"),
        _edge("exit", "q2", "terminal"),
    )

    validated = validate_routing_graph(_graph(nodes, edges))

    assert len(validated.loops) == 1
    assert validated.loops[0].kind is LoopKind.correction_return
    assert validated.loops[0].return_edge_ids == ("return",)


def test_unsupported_inferred_cycle_has_no_accepted_loop_record() -> None:
    nodes = (
        _node("entry", NodeKind.entry),
        _node("q1"),
        _node("q2"),
        _node("terminal", NodeKind.terminal),
    )
    edges = (
        _edge("enter", "entry", "q1"),
        _edge("forward", "q1", "q2"),
        _edge("inferred-return", "q2", "q1", kind=EdgeKind.sequential),
    )

    validated = validate_routing_graph(_graph(nodes, edges, audit=_audit(explicitly_stated=False)))

    assert validated.loops == ()
    assert "UNSUPPORTED_CYCLE" in _codes(validated.diagnostics)


def test_loop_without_exit_and_terminal_path_is_review_visible() -> None:
    nodes = (
        _node("entry", NodeKind.entry),
        _node("q1"),
        _node("q2"),
        _node("terminal", NodeKind.terminal),
    )
    edges = (
        _edge("enter", "entry", "q1"),
        _edge("forward", "q1", "q2"),
        _edge("return", "q2", "q1"),
    )

    validated = validate_routing_graph(_graph(nodes, edges))

    assert _codes(validated.diagnostics) == (
        "UNREACHABLE_NODE",
        "NO_LOOP_EXIT",
        "NO_TERMINAL_PATH",
    )


def test_nested_repeat_regions_follow_containment_without_duplicate_scc_records() -> None:
    nodes = (
        _node("entry", NodeKind.entry),
        _node(
            "outer",
            NodeKind.repeat_group,
            children=("outer-item", "inner"),
            entry_child="outer-item",
        ),
        _node("outer-item", parent="outer"),
        _node(
            "inner",
            NodeKind.repeat_group,
            parent="outer",
            children=("inner-item",),
            entry_child="inner-item",
            repeat_kind=RepeatKind.consumption_item,
        ),
        _node("inner-item", parent="inner"),
        _node("terminal", NodeKind.terminal),
    )
    edges = (
        _edge("enter-outer", "entry", "outer"),
        _edge("outer-entry", "outer", "outer-item"),
        _edge("outer-return", "outer-item", "outer-item"),
        _edge("to-inner", "outer-item", "inner"),
        _edge("inner-entry", "inner", "inner-item"),
        _edge("inner-return", "inner-item", "inner-item"),
        _edge("exit", "inner-item", "terminal"),
    )

    validated = validate_routing_graph(_graph(nodes, edges))

    assert [loop.repeat_group_node_id for loop in validated.loops] == ["outer", "inner"]
    assert validated.loops[0].member_node_ids == (
        "outer",
        "outer-item",
        "inner",
        "inner-item",
    )
    assert validated.loops[1].member_node_ids == ("inner", "inner-item")


def test_containment_cycles_are_checked_separately_from_flow_sccs() -> None:
    nodes = (
        _node(
            "section-a",
            NodeKind.section,
            parent="section-b",
            children=("section-b",),
            entry_child="section-b",
        ),
        _node(
            "section-b",
            NodeKind.section,
            parent="section-a",
            children=("section-a",),
            entry_child="section-a",
        ),
    )

    diagnostics = validate_containment(nodes)
    analysis = analyze_routing_components(
        nodes=nodes,
        edges=(),
        entry_node_ids=("section-a",),
        routing_audit=_audit(),
    )

    assert _codes(diagnostics) == ("CONTAINMENT_CYCLE",)
    assert "CONTAINMENT_CYCLE" in _codes(analysis.diagnostics)
    assert "UNSUPPORTED_CYCLE" not in _codes(analysis.diagnostics)


def test_reconciliation_keeps_inferred_cycle_in_audit_and_analyzes_supported_cycle() -> None:
    from tests.unit.test_routing_reconcile import (
        _inventory,
        _transition,
        _verified,
    )
    from tests.unit.test_routing_reconcile import (
        _node as reconciliation_node,
    )

    inventory = _inventory()
    inferred = _transition(
        "evidence:inferred",
        "Q3",
        "Q2",
        kind=TransitionKind.sequential,
        explicitly_stated=False,
    )
    supported = (
        _transition("evidence:forward", "Q1", "Q2"),
        _transition("evidence:return", "Q2", "Q1"),
        _transition("evidence:exit", "Q2", "END", target_kind=NodeKind.terminal),
    )

    graph = reconcile_routing_graph(
        nodes=tuple(reconciliation_node(item) for item in inventory),
        entry_node_ids=("entry:start",),
        inventory=inventory,
        source_binding=_binding(),
        verified_evidence=_verified((inferred,) + supported),
    )

    assert "evidence:inferred" not in {
        evidence_id for edge in graph.edges for evidence_id in edge.evidence_ids
    }
    assert "INFERRED_CYCLE" in _codes(graph.diagnostics)
    assert len(graph.loops) == 1
    assert graph.loops[0].kind is LoopKind.correction_return


def _scale_graph() -> QuestionnaireRoutingGraph:
    node_count = 1_000
    edge_count = 3_000
    nodes = [
        _node(
            f"n{index:04d}",
            NodeKind.entry
            if index == 0
            else NodeKind.terminal
            if index == node_count - 1
            else NodeKind.question,
        )
        for index in range(node_count)
    ]
    pairs = [(index, index + 1) for index in range(node_count - 1)]
    distance = 2
    while len(pairs) < edge_count:
        for source in range(node_count - distance):
            pairs.append((source, source + distance))
            if len(pairs) == edge_count:
                break
        distance += 1
    edges = tuple(
        _edge(f"scale:{index:04d}", f"n{source:04d}", f"n{target:04d}")
        for index, (source, target) in enumerate(pairs)
    )
    return _graph(nodes, edges, entries=("n0000",))


def test_scale_1000_nodes_3000_edges_is_iterative_deterministic_and_measured(
    record_property: Callable[[str, object], None],
) -> None:
    graph = _scale_graph()
    assert len(graph.nodes) == 1_000
    assert len(graph.edges) == 3_000

    tracemalloc.start()
    started = perf_counter()
    first = validate_routing_graph(graph)
    second = validate_routing_graph(graph)
    duration_seconds = perf_counter() - started
    _current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    record_property("platform", platform.platform())
    record_property("machine", platform.machine())
    record_property("processor", platform.processor() or "not reported")
    record_property("python", platform.python_version())
    record_property("node_count", len(graph.nodes))
    record_property("edge_count", len(graph.edges))
    record_property("two_run_duration_seconds", f"{duration_seconds:.6f}")
    record_property("tracemalloc_peak_bytes", peak_bytes)

    assert first.loops == second.loops == ()
    assert first.diagnostics == second.diagnostics == ()
    assert peak_bytes > 0
