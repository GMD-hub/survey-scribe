"""Deterministic questionnaire graph integrity and bounded loop analysis."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import TypeVar

from survey_scribe.models.routing import (
    DiagnosticSeverity,
    DiscrepancyKind,
    EdgeKind,
    EvidenceRecord,
    LoopDefinition,
    LoopKind,
    QuestionnaireRoutingGraph,
    RepeatKind,
    RoutingAudit,
    RoutingDiagnostic,
    RoutingDiscrepancy,
    RoutingEdge,
    RoutingNode,
)
from survey_scribe.routing.algorithms import (
    iterative_reachable,
    iterative_strongly_connected_components,
    reverse_adjacency,
)
from survey_scribe.routing.contracts import (
    CanonicalRoutingCondition,
    ConditionOperator,
    EvidenceOrigin,
    NodeKind,
    RoutingScalar,
)
from survey_scribe.routing.diagnostics import (
    build_reconciliation_diagnostic,
    stable_identifier,
)

KnownCategoryCodes = Mapping[str, tuple[RoutingScalar, ...]]

_DIAGNOSTIC_ORDER = {
    code: position
    for position, code in enumerate(
        (
            "DUPLICATE_NODE_ID",
            "DUPLICATE_EDGE",
            "DANGLING_TARGET",
            "UNKNOWN_ENTRY_NODE",
            "ADJACENCY_INDEX_MISMATCH",
            "CONTAINMENT_DANGLING_PARENT",
            "CONTAINMENT_CYCLE",
            "CONTAINMENT_INDEX_MISMATCH",
            "CONTAINMENT_ENTRY_INVALID",
            "TERMINAL_OUTGOING",
            "MULTIPLE_DEFAULTS",
            "CONDITION_UNKNOWN_REFERENCE",
            "CONDITION_VALUE_NOT_IN_CATEGORIES",
            "AMBIGUOUS_TARGET",
            "UNCOVERED_BRANCH",
            "OVERLAPPING_BRANCH_UNPROVEN",
            "UNREACHABLE_NODE",
            "DEAD_END_NONTERMINAL",
            "UNSUPPORTED_CYCLE",
            "NO_LOOP_EXIT",
            "NO_TERMINAL_PATH",
            "INCOMING_EVIDENCE_MISMATCH",
            "ACTIVATION_ROUTING_CONFLICT",
        )
    )
}
_RECOMPUTED_DIAGNOSTIC_CODES = frozenset(_DIAGNOSTIC_ORDER)


@dataclass(frozen=True)
class RoutingGraphAnalysis:
    """Stable pre-construction diagnostics and bounded accepted loop records."""

    loops: tuple[LoopDefinition, ...]
    diagnostics: tuple[RoutingDiagnostic, ...]
    has_structural_errors: bool


def analyze_routing_components(
    *,
    nodes: Iterable[RoutingNode],
    edges: Iterable[RoutingEdge],
    entry_node_ids: Iterable[str],
    routing_audit: RoutingAudit,
    diagnostics: Iterable[RoutingDiagnostic] = (),
    known_category_codes: KnownCategoryCodes | None = None,
) -> RoutingGraphAnalysis:
    """Analyze raw components before final graph construction can reject them."""
    ordered_nodes = tuple(nodes)
    ordered_edges = tuple(edges)
    entries = tuple(entry_node_ids)
    existing = tuple(diagnostics)
    generated: list[RoutingDiagnostic] = []

    nodes_by_id = _first_index(ordered_nodes, lambda node: node.node_id)
    node_order = {node_id: position for position, node_id in enumerate(nodes_by_id)}

    _diagnose_duplicates(ordered_nodes, ordered_edges, generated)
    valid_edges = _diagnose_endpoints(ordered_edges, nodes_by_id, generated)
    outgoing, incoming = _edge_indexes(nodes_by_id, valid_edges)
    _diagnose_entries(entries, nodes_by_id, generated)
    _diagnose_adjacency(nodes_by_id, outgoing, incoming, generated)
    generated.extend(validate_containment(tuple(nodes_by_id.values())))
    _diagnose_containment_entries(nodes_by_id, valid_edges, generated)
    _diagnose_terminal_edges(nodes_by_id, outgoing, generated)
    _diagnose_defaults(valid_edges, generated)
    _diagnose_conditions(
        nodes_by_id,
        valid_edges,
        known_category_codes or {},
        generated,
    )
    _diagnose_audit(routing_audit, nodes_by_id, generated)
    _diagnose_branch_coverage(
        valid_edges,
        known_category_codes or {},
        generated,
    )

    adjacency = {
        node_id: tuple(edge.target_node_id for edge in outgoing[node_id]) for node_id in nodes_by_id
    }
    reachable = set(iterative_reachable(entries, adjacency))
    unreachable = tuple(node_id for node_id in nodes_by_id if node_id not in reachable)
    if unreachable:
        generated.append(_diagnostic("UNREACHABLE_NODE", node_ids=unreachable))
    dead_ends = tuple(
        node_id
        for node_id, node in nodes_by_id.items()
        if node_id in reachable and node.kind is not NodeKind.terminal and not outgoing[node_id]
    )
    if dead_ends:
        generated.append(_diagnostic("DEAD_END_NONTERMINAL", node_ids=dead_ends))

    containment_is_valid = not any(item.code.startswith("CONTAINMENT_") for item in generated)
    loops, cycle_diagnostics = _analyze_loops(
        nodes_by_id,
        valid_edges,
        adjacency,
        routing_audit,
        node_order,
        containment_is_valid=containment_is_valid,
    )
    generated.extend(cycle_diagnostics)
    _diagnose_terminal_paths(nodes_by_id, adjacency, reachable, generated)

    generated.sort(
        key=lambda item: (
            _DIAGNOSTIC_ORDER.get(item.code, len(_DIAGNOSTIC_ORDER)),
            item.diagnostic_id,
        )
    )
    combined = _deduplicate_diagnostics(existing, tuple(generated))
    return RoutingGraphAnalysis(
        loops=loops,
        diagnostics=combined,
        has_structural_errors=any(item.severity is DiagnosticSeverity.error for item in combined),
    )


def validate_routing_graph(
    graph: QuestionnaireRoutingGraph,
    *,
    known_category_codes: KnownCategoryCodes | None = None,
) -> QuestionnaireRoutingGraph:
    """Return a revalidated graph with derived diagnostics and bounded loops."""
    analysis = analyze_routing_components(
        nodes=graph.nodes,
        edges=graph.edges,
        entry_node_ids=graph.entry_node_ids,
        routing_audit=graph.routing_audit,
        diagnostics=tuple(
            item for item in graph.diagnostics if item.code not in _RECOMPUTED_DIAGNOSTIC_CODES
        ),
        known_category_codes=known_category_codes,
    )
    return QuestionnaireRoutingGraph(
        schema_version=graph.schema_version,
        entry_node_ids=graph.entry_node_ids,
        nodes=graph.nodes,
        edges=graph.edges,
        loops=analysis.loops,
        diagnostics=analysis.diagnostics,
        routing_audit=graph.routing_audit,
    )


def validate_containment(nodes: Iterable[RoutingNode]) -> tuple[RoutingDiagnostic, ...]:
    """Validate containment iteratively without treating hierarchy as flow."""
    ordered_nodes = tuple(nodes)
    nodes_by_id = _first_index(ordered_nodes, lambda node: node.node_id)
    diagnostics: list[RoutingDiagnostic] = []

    dangling = tuple(
        node.node_id
        for node in nodes_by_id.values()
        if node.containment.parent_node_id is not None
        and node.containment.parent_node_id not in nodes_by_id
    )
    if dangling:
        diagnostics.append(
            _diagnostic(
                "CONTAINMENT_DANGLING_PARENT",
                severity=DiagnosticSeverity.error,
                node_ids=dangling,
            )
        )

    cycle_members: set[str] = set()
    complete: set[str] = set()
    for start in nodes_by_id:
        if start in complete:
            continue
        path: list[str] = []
        positions: dict[str, int] = {}
        current: str | None = start
        while current is not None and current in nodes_by_id and current not in complete:
            if current in positions:
                cycle_members.update(path[positions[current] :])
                break
            positions[current] = len(path)
            path.append(current)
            current = nodes_by_id[current].containment.parent_node_id
        complete.update(path)
    if cycle_members:
        diagnostics.append(
            _diagnostic(
                "CONTAINMENT_CYCLE",
                severity=DiagnosticSeverity.error,
                node_ids=tuple(node_id for node_id in nodes_by_id if node_id in cycle_members),
            )
        )

    expected_children: dict[str, list[str]] = {node_id: [] for node_id in nodes_by_id}
    for node in nodes_by_id.values():
        parent_id = node.containment.parent_node_id
        if parent_id in expected_children:
            expected_children[parent_id].append(node.node_id)
    mismatched = tuple(
        node_id
        for node_id, node in nodes_by_id.items()
        if node.containment.child_node_ids != tuple(expected_children[node_id])
    )
    if mismatched:
        diagnostics.append(
            _diagnostic(
                "CONTAINMENT_INDEX_MISMATCH",
                severity=DiagnosticSeverity.error,
                node_ids=mismatched,
            )
        )

    invalid_entries = tuple(
        node.node_id
        for node in nodes_by_id.values()
        if (
            node.kind in {NodeKind.section, NodeKind.repeat_group}
            and node.containment.entry_child_node_id not in expected_children[node.node_id]
        )
        or (
            node.kind not in {NodeKind.section, NodeKind.repeat_group}
            and node.containment.entry_child_node_id is not None
        )
    )
    if invalid_entries:
        diagnostics.append(
            _diagnostic(
                "CONTAINMENT_ENTRY_INVALID",
                severity=DiagnosticSeverity.error,
                node_ids=invalid_entries,
            )
        )
    return tuple(diagnostics)


def _diagnose_duplicates(
    nodes: tuple[RoutingNode, ...],
    edges: tuple[RoutingEdge, ...],
    diagnostics: list[RoutingDiagnostic],
) -> None:
    duplicate_nodes = _duplicate_values(node.node_id for node in nodes)
    if duplicate_nodes:
        diagnostics.append(
            _diagnostic(
                "DUPLICATE_NODE_ID",
                severity=DiagnosticSeverity.error,
                node_ids=duplicate_nodes,
            )
        )

    duplicate_edge_ids = set(_duplicate_values(edge.edge_id for edge in edges))
    semantic_groups: dict[str, list[str]] = {}
    for edge in edges:
        semantic_groups.setdefault(_edge_identity(edge), []).append(edge.edge_id)
    duplicate_semantic = {
        edge_id
        for edge_ids in semantic_groups.values()
        if len(edge_ids) > 1
        for edge_id in edge_ids
    }
    duplicate_edges = tuple(
        dict.fromkeys(
            edge.edge_id
            for edge in edges
            if edge.edge_id in duplicate_edge_ids or edge.edge_id in duplicate_semantic
        )
    )
    if duplicate_edges:
        diagnostics.append(
            _diagnostic(
                "DUPLICATE_EDGE",
                severity=DiagnosticSeverity.error,
                edge_ids=duplicate_edges,
            )
        )


def _diagnose_endpoints(
    edges: tuple[RoutingEdge, ...],
    nodes: Mapping[str, RoutingNode],
    diagnostics: list[RoutingDiagnostic],
) -> tuple[RoutingEdge, ...]:
    dangling = tuple(
        edge
        for edge in edges
        if edge.source_node_id not in nodes or edge.target_node_id not in nodes
    )
    if dangling:
        diagnostics.append(
            _diagnostic(
                "DANGLING_TARGET",
                severity=DiagnosticSeverity.error,
                node_ids=tuple(
                    dict.fromkeys(
                        node_id
                        for edge in dangling
                        for node_id in (edge.source_node_id, edge.target_node_id)
                        if node_id in nodes
                    )
                ),
                edge_ids=tuple(dict.fromkeys(edge.edge_id for edge in dangling)),
            )
        )
    return tuple(edge for edge in edges if edge not in dangling)


def _edge_indexes(
    nodes: Mapping[str, RoutingNode],
    edges: tuple[RoutingEdge, ...],
) -> tuple[dict[str, list[RoutingEdge]], dict[str, list[RoutingEdge]]]:
    outgoing: dict[str, list[RoutingEdge]] = {node_id: [] for node_id in nodes}
    incoming: dict[str, list[RoutingEdge]] = {node_id: [] for node_id in nodes}
    for edge in edges:
        outgoing[edge.source_node_id].append(edge)
        incoming[edge.target_node_id].append(edge)
    return outgoing, incoming


def _diagnose_entries(
    entries: tuple[str, ...],
    nodes: Mapping[str, RoutingNode],
    diagnostics: list[RoutingDiagnostic],
) -> None:
    invalid = tuple(
        node_id
        for node_id in dict.fromkeys(entries)
        if node_id not in nodes or nodes[node_id].kind is not NodeKind.entry
    )
    if invalid:
        diagnostics.append(
            _diagnostic(
                "UNKNOWN_ENTRY_NODE",
                severity=DiagnosticSeverity.error,
                node_ids=tuple(node_id for node_id in invalid if node_id in nodes),
            )
        )


def _diagnose_adjacency(
    nodes: Mapping[str, RoutingNode],
    outgoing: Mapping[str, list[RoutingEdge]],
    incoming: Mapping[str, list[RoutingEdge]],
    diagnostics: list[RoutingDiagnostic],
) -> None:
    mismatched: list[str] = []
    for node_id, node in nodes.items():
        expected_outgoing = tuple(edge.edge_id for edge in outgoing[node_id])
        expected_incoming = tuple(edge.edge_id for edge in incoming[node_id])
        expected_next = tuple(dict.fromkeys(edge.target_node_id for edge in outgoing[node_id]))
        expected_previous = tuple(dict.fromkeys(edge.source_node_id for edge in incoming[node_id]))
        if (
            node.outgoing_edge_ids != expected_outgoing
            or node.incoming_edge_ids != expected_incoming
            or node.next_node_ids != expected_next
            or node.previous_node_ids != expected_previous
        ):
            mismatched.append(node_id)
    if mismatched:
        diagnostics.append(
            _diagnostic(
                "ADJACENCY_INDEX_MISMATCH",
                severity=DiagnosticSeverity.error,
                node_ids=tuple(mismatched),
            )
        )


def _diagnose_containment_entries(
    nodes: Mapping[str, RoutingNode],
    edges: tuple[RoutingEdge, ...],
    diagnostics: list[RoutingDiagnostic],
) -> None:
    invalid: list[str] = []
    for node in nodes.values():
        entry_id = node.containment.entry_child_node_id
        if entry_id is None:
            continue
        matching = tuple(
            edge
            for edge in edges
            if edge.source_node_id == node.node_id and edge.target_node_id == entry_id
        )
        if len(matching) != 1 or matching[0].kind is not EdgeKind.unconditional:
            invalid.append(node.node_id)
    if invalid:
        diagnostics.append(
            _diagnostic(
                "CONTAINMENT_ENTRY_INVALID",
                severity=DiagnosticSeverity.error,
                node_ids=tuple(invalid),
            )
        )


def _diagnose_terminal_edges(
    nodes: Mapping[str, RoutingNode],
    outgoing: Mapping[str, list[RoutingEdge]],
    diagnostics: list[RoutingDiagnostic],
) -> None:
    invalid = tuple(
        edge
        for node_id, node in nodes.items()
        if node.kind is NodeKind.terminal
        for edge in outgoing[node_id]
    )
    if invalid:
        diagnostics.append(
            _diagnostic(
                "TERMINAL_OUTGOING",
                severity=DiagnosticSeverity.error,
                node_ids=tuple(dict.fromkeys(edge.source_node_id for edge in invalid)),
                edge_ids=tuple(dict.fromkeys(edge.edge_id for edge in invalid)),
            )
        )


def _diagnose_defaults(
    edges: tuple[RoutingEdge, ...],
    diagnostics: list[RoutingDiagnostic],
) -> None:
    defaults: dict[str, list[str]] = {}
    for edge in edges:
        if edge.kind is EdgeKind.default:
            defaults.setdefault(edge.source_node_id, []).append(edge.edge_id)
    sources = tuple(source for source, edge_ids in defaults.items() if len(edge_ids) > 1)
    if sources:
        diagnostics.append(
            _diagnostic(
                "MULTIPLE_DEFAULTS",
                severity=DiagnosticSeverity.error,
                node_ids=sources,
                edge_ids=tuple(edge_id for source in sources for edge_id in defaults[source]),
            )
        )


def _diagnose_conditions(
    nodes: Mapping[str, RoutingNode],
    edges: tuple[RoutingEdge, ...],
    known_categories: KnownCategoryCodes,
    diagnostics: list[RoutingDiagnostic],
) -> None:
    contexts: list[tuple[CanonicalRoutingCondition, str | None, str | None]] = []
    contexts.extend(
        (edge.condition, None, edge.edge_id) for edge in edges if edge.condition is not None
    )
    for node in nodes.values():
        if node.activation_condition is not None:
            contexts.append((node.activation_condition, node.node_id, None))
        if node.repeat_spec is not None and node.repeat_spec.continuation_condition is not None:
            contexts.append((node.repeat_spec.continuation_condition, node.node_id, None))

    unknown_reference_nodes: list[str] = []
    unknown_reference_edges: list[str] = []
    unknown_code_nodes: list[str] = []
    unknown_code_edges: list[str] = []
    typed_categories = {
        node_id: {_scalar_key(value) for value in values}
        for node_id, values in known_categories.items()
    }
    for condition, context_node_id, context_edge_id in contexts:
        for leaf in _condition_nodes(condition):
            question_id = leaf.question_node_id
            if question_id is not None:
                question = nodes.get(question_id)
                if question is None or question.kind is not NodeKind.question:
                    if context_node_id is not None:
                        unknown_reference_nodes.append(context_node_id)
                    if context_edge_id is not None:
                        unknown_reference_edges.append(context_edge_id)
                    continue
            checked_values = _categorical_values(leaf)
            if question_id not in typed_categories or checked_values is None:
                continue
            if any(
                _scalar_key(value) not in typed_categories[question_id] for value in checked_values
            ):
                if context_node_id is not None:
                    unknown_code_nodes.append(context_node_id)
                if context_edge_id is not None:
                    unknown_code_edges.append(context_edge_id)
    if unknown_reference_nodes or unknown_reference_edges:
        diagnostics.append(
            _diagnostic(
                "CONDITION_UNKNOWN_REFERENCE",
                severity=DiagnosticSeverity.error,
                node_ids=tuple(dict.fromkeys(unknown_reference_nodes)),
                edge_ids=tuple(dict.fromkeys(unknown_reference_edges)),
            )
        )
    if unknown_code_nodes or unknown_code_edges:
        diagnostics.append(
            _diagnostic(
                "CONDITION_VALUE_NOT_IN_CATEGORIES",
                node_ids=tuple(dict.fromkeys(unknown_code_nodes)),
                edge_ids=tuple(dict.fromkeys(unknown_code_edges)),
            )
        )


def _diagnose_branch_coverage(
    edges: tuple[RoutingEdge, ...],
    known_categories: KnownCategoryCodes,
    diagnostics: list[RoutingDiagnostic],
) -> None:
    by_source: dict[str, list[RoutingEdge]] = {}
    for edge in edges:
        by_source.setdefault(edge.source_node_id, []).append(edge)
    for source, source_edges in by_source.items():
        conditional = tuple(edge for edge in source_edges if edge.kind is EdgeKind.conditional)
        if not conditional:
            continue
        has_default = any(edge.kind is EdgeKind.default for edge in source_edges)
        branch_sets = tuple(
            _condition_category_set(edge.condition, known_categories) for edge in conditional
        )
        proven_sets = tuple(item[1] for item in branch_sets if item is not None)
        one_domain = {item[0] for item in branch_sets if item is not None and item[0] is not None}
        coverage_proven = False
        if len(proven_sets) == len(conditional) and len(one_domain) == 1 and one_domain:
            question_id = next(iter(one_domain))
            known = {_scalar_key(value) for value in known_categories[question_id]}
            coverage_proven = bool(known) and set().union(*proven_sets) == known
        if not has_default and not coverage_proven:
            diagnostics.append(
                _diagnostic(
                    "UNCOVERED_BRANCH",
                    node_ids=(source,),
                    edge_ids=tuple(edge.edge_id for edge in conditional),
                )
            )

        overlap_unproven = len(proven_sets) != len(conditional)
        if not overlap_unproven:
            overlap_unproven = any(
                left.intersection(right)
                for index, left in enumerate(proven_sets)
                for right in proven_sets[index + 1 :]
            )
        if len(conditional) > 1 and overlap_unproven:
            diagnostics.append(
                _diagnostic(
                    "OVERLAPPING_BRANCH_UNPROVEN",
                    node_ids=(source,),
                    edge_ids=tuple(edge.edge_id for edge in conditional),
                )
            )


def _diagnose_audit(
    audit: RoutingAudit,
    nodes: Mapping[str, RoutingNode],
    diagnostics: list[RoutingDiagnostic],
) -> None:
    mapping = {
        DiscrepancyKind.ambiguous_target: "AMBIGUOUS_TARGET",
        DiscrepancyKind.incoming_mismatch: "INCOMING_EVIDENCE_MISMATCH",
        DiscrepancyKind.multiple_defaults: "MULTIPLE_DEFAULTS",
        DiscrepancyKind.activation_routing_conflict: "ACTIVATION_ROUTING_CONFLICT",
        DiscrepancyKind.unsupported_cycle: "UNSUPPORTED_CYCLE",
    }
    candidates = {item.candidate_id: item for item in audit.candidate_edges}
    grouped: dict[str, list[RoutingDiscrepancy]] = {}
    for discrepancy in audit.discrepancies:
        code = mapping.get(discrepancy.kind)
        if code is not None and discrepancy.resolved_by_decision_id is None:
            grouped.setdefault(code, []).append(discrepancy)
    for code, discrepancies in grouped.items():
        candidate_ids = tuple(
            dict.fromkeys(
                candidate_id
                for discrepancy in discrepancies
                for candidate_id in discrepancy.candidate_ids
            )
        )
        node_ids = tuple(
            dict.fromkeys(
                candidate.source_node_id
                for candidate_id in candidate_ids
                if (candidate := candidates.get(candidate_id)) is not None
                and candidate.source_node_id in nodes
            )
        )
        evidence_ids = tuple(
            dict.fromkeys(
                evidence_id
                for discrepancy in discrepancies
                for evidence_id in discrepancy.evidence_ids
            )
        )
        diagnostics.append(
            _diagnostic(
                code,
                node_ids=node_ids,
                evidence_ids=evidence_ids,
                candidate_ids=candidate_ids,
            )
        )


def _analyze_loops(
    nodes: Mapping[str, RoutingNode],
    edges: tuple[RoutingEdge, ...],
    adjacency: Mapping[str, tuple[str, ...]],
    audit: RoutingAudit,
    node_order: Mapping[str, int],
    *,
    containment_is_valid: bool,
) -> tuple[tuple[LoopDefinition, ...], tuple[RoutingDiagnostic, ...]]:
    components = iterative_strongly_connected_components(nodes, adjacency)
    edge_by_id = {edge.edge_id: edge for edge in edges}
    cyclic = tuple(component for component in components if _component_is_cyclic(component, edges))
    declared = _declared_regions(nodes, node_order) if containment_is_valid else ()
    evidence = {item.evidence_id: item for item in audit.evidence}
    loops: list[LoopDefinition] = []
    diagnostics: list[RoutingDiagnostic] = []

    for repeat_node_id, members in declared:
        repeat_spec = nodes[repeat_node_id].repeat_spec
        roles = _loop_edge_roles(
            members,
            edges,
            node_order,
            declared_regions=declared,
            owner_repeat_node_id=repeat_node_id,
        )
        loop = _make_loop(
            kind=(
                LoopKind.repeat_until
                if repeat_spec is not None and repeat_spec.repeat_kind is RepeatKind.until_condition
                else LoopKind.repeat_group
            ),
            repeat_group_node_id=repeat_node_id,
            members=members,
            roles=roles,
            edge_by_id=edge_by_id,
        )
        loops.append(loop)

    declared_sets = tuple(set(members) for _repeat_id, members in declared)
    for component in cyclic:
        members = set(component)
        if any(members.issubset(region) for region in declared_sets):
            continue
        roles = _loop_edge_roles(
            component,
            edges,
            node_order,
            declared_regions=(),
            owner_repeat_node_id=None,
        )
        return_edges = tuple(edge_by_id[edge_id] for edge_id in roles[2])
        supported = bool(return_edges) and all(
            _edge_is_source_supported(edge, evidence) for edge in return_edges
        )
        if not supported:
            diagnostics.append(
                _diagnostic(
                    "UNSUPPORTED_CYCLE",
                    node_ids=component,
                    edge_ids=tuple(edge.edge_id for edge in return_edges),
                    evidence_ids=tuple(
                        dict.fromkeys(
                            evidence_id
                            for edge in return_edges
                            for evidence_id in edge.evidence_ids
                        )
                    ),
                )
            )
            continue
        loops.append(
            _make_loop(
                kind=(LoopKind.correction_return if len(return_edges) == 1 else LoopKind.other),
                repeat_group_node_id=None,
                members=component,
                roles=roles,
                edge_by_id=edge_by_id,
            )
        )

    loops.sort(key=lambda loop: min(node_order[node_id] for node_id in loop.member_node_ids))
    for loop in loops:
        if not loop.exit_edge_ids:
            diagnostics.append(
                _diagnostic(
                    "NO_LOOP_EXIT",
                    node_ids=loop.member_node_ids,
                    edge_ids=loop.return_edge_ids,
                    evidence_ids=loop.evidence_ids,
                )
            )
    return tuple(loops), tuple(diagnostics)


def _component_is_cyclic(
    component: tuple[str, ...],
    edges: tuple[RoutingEdge, ...],
) -> bool:
    if len(component) > 1:
        return True
    if not component:
        return False
    node_id = component[0]
    return any(edge.source_node_id == node_id and edge.target_node_id == node_id for edge in edges)


def _declared_regions(
    nodes: Mapping[str, RoutingNode],
    node_order: Mapping[str, int],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    declared: list[tuple[str, tuple[str, ...]]] = []
    for node in nodes.values():
        if node.kind is not NodeKind.repeat_group:
            continue
        members: set[str] = set()
        stack = [node.node_id]
        while stack:
            node_id = stack.pop()
            if node_id in members:
                continue
            members.add(node_id)
            stack.extend(reversed(nodes[node_id].containment.child_node_ids))
        declared.append(
            (
                node.node_id,
                tuple(sorted(members, key=node_order.__getitem__)),
            )
        )
    return tuple(declared)


def _loop_edge_roles(
    member_node_ids: Iterable[str],
    edges: tuple[RoutingEdge, ...],
    node_order: Mapping[str, int],
    *,
    declared_regions: tuple[tuple[str, tuple[str, ...]], ...],
    owner_repeat_node_id: str | None,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    members = set(member_node_ids)
    entry: list[str] = []
    internal: list[str] = []
    returns: list[str] = []
    exits: list[str] = []
    region_sets = tuple((repeat_id, set(region)) for repeat_id, region in declared_regions)
    for edge in edges:
        source_inside = edge.source_node_id in members
        target_inside = edge.target_node_id in members
        if not source_inside and target_inside:
            entry.append(edge.edge_id)
        elif source_inside and not target_inside:
            exits.append(edge.edge_id)
        elif source_inside and target_inside:
            if owner_repeat_node_id is not None:
                owners = tuple(
                    (repeat_id, region)
                    for repeat_id, region in region_sets
                    if edge.source_node_id in region and edge.target_node_id in region
                )
                if owners:
                    owner = min(
                        owners,
                        key=lambda item: (len(item[1]), node_order[item[0]]),
                    )[0]
                    if owner != owner_repeat_node_id:
                        continue
            if (
                edge.source_node_id == edge.target_node_id
                or node_order[edge.target_node_id] <= node_order[edge.source_node_id]
            ):
                returns.append(edge.edge_id)
            else:
                internal.append(edge.edge_id)
    return tuple(entry), tuple(internal), tuple(returns), tuple(exits)


def _make_loop(
    *,
    kind: LoopKind,
    repeat_group_node_id: str | None,
    members: tuple[str, ...],
    roles: tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]],
    edge_by_id: Mapping[str, RoutingEdge],
) -> LoopDefinition:
    entry, internal, returns, exits = roles
    evidence_ids = tuple(
        dict.fromkeys(
            evidence_id
            for edge_id in entry + internal + returns + exits
            for evidence_id in edge_by_id[edge_id].evidence_ids
        )
    )
    payload = {
        "kind": kind.value,
        "member_node_ids": members,
        "repeat_group_node_id": repeat_group_node_id,
    }
    return LoopDefinition(
        loop_id=stable_identifier("loop", payload),
        kind=kind,
        repeat_group_node_id=repeat_group_node_id,
        member_node_ids=members,
        entry_edge_ids=entry,
        member_edge_ids=internal,
        return_edge_ids=returns,
        exit_edge_ids=exits,
        source_supported=True,
        evidence_ids=evidence_ids,
    )


def _edge_is_source_supported(
    edge: RoutingEdge,
    evidence: Mapping[str, EvidenceRecord],
) -> bool:
    if edge.review_decision_id is not None:
        return True
    for evidence_id in edge.evidence_ids:
        record = evidence.get(evidence_id)
        if record is not None and (
            (observation := record.observation).explicitly_stated
            or observation.origin is EvidenceOrigin.native_parser
        ):
            return True
    return False


def _diagnose_terminal_paths(
    nodes: Mapping[str, RoutingNode],
    adjacency: Mapping[str, tuple[str, ...]],
    reachable: set[str],
    diagnostics: list[RoutingDiagnostic],
) -> None:
    terminal_ids = tuple(
        node_id for node_id, node in nodes.items() if node.kind is NodeKind.terminal
    )
    can_reach_terminal = set(iterative_reachable(terminal_ids, reverse_adjacency(nodes, adjacency)))
    without_path = tuple(
        node_id for node_id in nodes if node_id in reachable and node_id not in can_reach_terminal
    )
    if without_path:
        diagnostics.append(_diagnostic("NO_TERMINAL_PATH", node_ids=without_path))


def _condition_category_set(
    condition: CanonicalRoutingCondition | None,
    known_categories: KnownCategoryCodes,
) -> tuple[str | None, frozenset[tuple[type[object], object]]] | None:
    if condition is None or condition.children is not None:
        return None
    if condition.operator in {
        ConditionOperator.always,
        ConditionOperator.selected,
        ConditionOperator.not_selected,
    }:
        return None
    question_id = condition.question_node_id
    if question_id is None or question_id not in known_categories:
        return None
    known = {_scalar_key(value) for value in known_categories[question_id]}
    values = _categorical_values(condition)
    if values is None:
        return None
    selected = {_scalar_key(value) for value in values}
    if not selected.issubset(known):
        return None
    if condition.operator in {ConditionOperator.not_equals, ConditionOperator.not_in_set}:
        selected = known.difference(selected)
    return question_id, frozenset(selected)


def _categorical_values(
    condition: CanonicalRoutingCondition,
) -> tuple[RoutingScalar, ...] | None:
    if condition.operator in {
        ConditionOperator.equals,
        ConditionOperator.not_equals,
        ConditionOperator.selected,
        ConditionOperator.not_selected,
    }:
        return (condition.value,) if condition.value is not None else None
    if condition.operator in {ConditionOperator.in_set, ConditionOperator.not_in_set}:
        return condition.values
    return None


def _condition_nodes(
    root: CanonicalRoutingCondition,
) -> tuple[CanonicalRoutingCondition, ...]:
    nodes: list[CanonicalRoutingCondition] = []
    stack = [root]
    while stack:
        current = stack.pop()
        nodes.append(current)
        if current.children:
            stack.extend(reversed(current.children))
    return tuple(nodes)


def _scalar_key(value: RoutingScalar) -> tuple[type[object], object]:
    return type(value), value


def _edge_identity(edge: RoutingEdge) -> str:
    condition = edge.condition.model_dump(mode="json") if edge.condition is not None else None
    if condition is not None:
        stack: list[object] = [condition]
        while stack:
            current = stack.pop()
            if isinstance(current, dict):
                current.pop("raw_text", None)
                stack.extend(current.values())
            elif isinstance(current, list):
                stack.extend(current)
    return json.dumps(
        {
            "condition": condition,
            "kind": edge.kind.value,
            "priority": edge.priority,
            "source": edge.source_node_id,
            "target": edge.target_node_id,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _diagnostic(
    code: str,
    *,
    severity: DiagnosticSeverity = DiagnosticSeverity.warning,
    node_ids: tuple[str, ...] = (),
    edge_ids: tuple[str, ...] = (),
    evidence_ids: tuple[str, ...] = (),
    candidate_ids: tuple[str, ...] = (),
) -> RoutingDiagnostic:
    return build_reconciliation_diagnostic(
        code,
        severity=severity,
        node_ids=node_ids,
        edge_ids=edge_ids,
        evidence_ids=evidence_ids,
        candidate_ids=candidate_ids,
    )


def _deduplicate_diagnostics(
    existing: tuple[RoutingDiagnostic, ...],
    generated: tuple[RoutingDiagnostic, ...],
) -> tuple[RoutingDiagnostic, ...]:
    result: list[RoutingDiagnostic] = list(existing)
    identifiers = {item.diagnostic_id for item in existing}
    existing_codes = {item.code for item in existing}
    for diagnostic in generated:
        if diagnostic.diagnostic_id in identifiers or diagnostic.code in existing_codes:
            continue
        identifiers.add(diagnostic.diagnostic_id)
        result.append(diagnostic)
    return tuple(result)


def _duplicate_values(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return tuple(duplicates)


_IndexValue = TypeVar("_IndexValue")


def _first_index(
    items: Iterable[_IndexValue],
    key: Callable[[_IndexValue], str],
) -> dict[str, _IndexValue]:
    indexed: dict[str, _IndexValue] = {}
    for item in items:
        indexed.setdefault(key(item), item)
    return indexed


__all__ = [
    "KnownCategoryCodes",
    "RoutingGraphAnalysis",
    "analyze_routing_components",
    "validate_containment",
    "validate_routing_graph",
]
