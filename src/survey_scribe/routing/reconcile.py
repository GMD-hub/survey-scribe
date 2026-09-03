"""Deterministic reconciliation of routing evidence into a canonical multigraph."""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from pydantic import ValidationError

from survey_scribe.models.routing import (
    CandidateEdge,
    CandidateStatus,
    DiscrepancyKind,
    EdgeKind,
    EvidenceRecord,
    InventoryItem,
    QuestionnaireRoutingGraph,
    ReviewAction,
    ReviewDecision,
    RoutingAudit,
    RoutingDiagnostic,
    RoutingDiscrepancy,
    RoutingEdge,
    RoutingNode,
    RoutingSourceBinding,
)
from survey_scribe.routing.contracts import (
    ActivationEvidence,
    CanonicalRoutingCondition,
    ConditionOperator,
    EvidenceOrigin,
    ExtractedRoutingCondition,
    ItemReference,
    NodeKind,
    TransitionEvidence,
)
from survey_scribe.routing.diagnostics import (
    build_reconciliation_diagnostic,
    build_reconciliation_discrepancy,
    stable_identifier,
)
from survey_scribe.routing.identity import (
    ConditionResolution,
    IdentityError,
    IdentityResolver,
    ReferenceResolution,
    VerifiedEvidence,
    normalize_section_path,
    normalized_alias,
    resolve_extracted_condition,
)
from survey_scribe.routing.validate import KnownCategoryCodes, validate_routing_graph

_ISSUE_ORDER = (
    "CONFLICTING_TARGET",
    "CONFLICTING_CONDITION",
    "CONFLICTING_PRIORITY",
    "MULTIPLE_DEFAULTS",
    "INCOMING_ONLY",
    "AMBIGUOUS_TARGET",
    "UNRESOLVED_TARGET",
    "FUZZY_TARGET",
    "AMBIGUOUS_CONDITION_REFERENCE",
    "OPAQUE_CONDITION",
    "INFERRED_CYCLE",
    "SEQUENTIAL_BYPASSED",
    "SEQUENTIAL_UNCLEAR",
)

_DISCREPANCY_BY_ISSUE = {
    "AMBIGUOUS_CONDITION_REFERENCE": DiscrepancyKind.conflicting_condition,
    "AMBIGUOUS_TARGET": DiscrepancyKind.ambiguous_target,
    "CONFLICTING_CONDITION": DiscrepancyKind.conflicting_condition,
    "CONFLICTING_PRIORITY": DiscrepancyKind.conflicting_condition,
    "CONFLICTING_TARGET": DiscrepancyKind.conflicting_target,
    "FUZZY_TARGET": DiscrepancyKind.ambiguous_target,
    "INCOMING_ONLY": DiscrepancyKind.incoming_mismatch,
    "INFERRED_CYCLE": DiscrepancyKind.unsupported_cycle,
    "MULTIPLE_DEFAULTS": DiscrepancyKind.multiple_defaults,
    "OPAQUE_CONDITION": DiscrepancyKind.opaque_condition,
    "SEQUENTIAL_BYPASSED": DiscrepancyKind.other,
    "SEQUENTIAL_UNCLEAR": DiscrepancyKind.other,
    "UNRESOLVED_TARGET": DiscrepancyKind.unresolved_target,
}

_HUMAN_REVIEW_ISSUES = frozenset(
    {
        "AMBIGUOUS_TARGET",
        "FUZZY_TARGET",
        "INFERRED_CYCLE",
        "UNRESOLVED_TARGET",
    }
)


class ReconciliationError(ValueError):
    """Evidence or review input cannot be reconciled without inventing graph facts."""


@dataclass
class _TransitionClaim:
    first_position: int
    source_node_id: str
    source_item: InventoryItem
    target_resolution: ReferenceResolution
    target_reference: ItemReference
    kind: EdgeKind
    extracted_condition: ExtractedRoutingCondition | None
    condition_resolution: ConditionResolution | None
    evidence_ids: list[str] = field(default_factory=list)
    observations: list[TransitionEvidence] = field(default_factory=list)
    priorities: list[int] = field(default_factory=list)
    issues: set[str] = field(default_factory=set)
    candidate_id: str | None = None

    @property
    def target_node_id(self) -> str | None:
        return self.target_resolution.node_id

    @property
    def canonical_condition(self) -> CanonicalRoutingCondition | None:
        if self.condition_resolution is None:
            return None
        return self.condition_resolution.condition

    @property
    def priority(self) -> int | None:
        values = tuple(dict.fromkeys(self.priorities))
        return values[0] if len(values) == 1 else None

    @property
    def has_outgoing_support(self) -> bool:
        return any(
            item.origin in {EvidenceOrigin.forward_extraction, EvidenceOrigin.native_parser}
            for item in self.observations
        )

    @property
    def has_incoming_support(self) -> bool:
        return any(item.origin is EvidenceOrigin.incoming_extraction for item in self.observations)


def reconcile_routing_graph(
    *,
    nodes: Iterable[RoutingNode],
    entry_node_ids: tuple[str, ...],
    inventory: Iterable[InventoryItem],
    source_binding: RoutingSourceBinding,
    verified_evidence: VerifiedEvidence,
    source_priorities: Mapping[str, int] | None = None,
    review_decisions: Iterable[ReviewDecision] = (),
    known_category_codes: KnownCategoryCodes | None = None,
) -> QuestionnaireRoutingGraph:
    """Reconcile verified evidence and return an accepted-only canonical graph."""
    ordered_inventory = tuple(sorted(inventory, key=lambda item: item.source_order))
    ordered_nodes = tuple(nodes)
    inventory_by_id = _unique_items(ordered_inventory)
    nodes_by_id = _unique_nodes(ordered_nodes)
    if any(node_id not in nodes_by_id for node_id in inventory_by_id):
        raise ReconciliationError("every inventory item must have one canonical graph node")
    _validate_verified_evidence(verified_evidence)
    priorities = _validate_source_priorities(source_priorities, verified_evidence)

    resolver = IdentityResolver(ordered_inventory)
    evidence_positions = {
        record.evidence_id: position for position, record in enumerate(verified_evidence.records)
    }
    transition_records = tuple(
        (position, record.evidence_id, record.observation)
        for position, record in enumerate(verified_evidence.records)
        if isinstance(record.observation, TransitionEvidence)
    )
    claims = _build_transition_claims(
        transition_records,
        resolver,
        inventory_by_id,
        priorities,
    )
    _mark_incoming_disagreements(claims)
    _mark_default_and_priority_conflicts(claims)
    _mark_sequential_inference_issues(claims, ordered_inventory)

    candidates = _build_candidates(claims)
    discrepancies, transition_diagnostics = _build_discrepancies_and_diagnostics(claims)
    accepted_edges = tuple(
        _edge_from_claim(claim)
        for claim in claims
        if not claim.issues and claim.has_outgoing_support
    )
    accepted_edges = _merge_and_sort_edges(
        accepted_edges,
        inventory_by_id,
        evidence_positions,
    )
    _ensure_one_default(accepted_edges)

    activation_updates, activation_diagnostics = _reconcile_activation_evidence(
        verified_evidence,
        resolver,
        inventory_by_id,
        nodes_by_id,
    )
    updated_nodes = tuple(
        node.model_copy(
            update={
                "activation_condition": activation_updates.get(
                    node.node_id, node.activation_condition
                )
            }
        )
        for node in ordered_nodes
    )
    updated_nodes = _derive_adjacency(updated_nodes, accepted_edges)
    audit = RoutingAudit(
        source_binding=source_binding,
        inventory=ordered_inventory,
        source_spans=verified_evidence.source_spans,
        evidence=verified_evidence.records,
        candidate_edges=candidates,
        discrepancies=discrepancies,
        review_decisions=(),
    )
    try:
        graph = validate_routing_graph(
            QuestionnaireRoutingGraph(
                schema_version="1.0",
                entry_node_ids=entry_node_ids,
                nodes=updated_nodes,
                edges=accepted_edges,
                loops=(),
                diagnostics=activation_diagnostics + transition_diagnostics,
                routing_audit=audit,
            ),
            known_category_codes=known_category_codes,
        )
    except ValidationError as error:
        raise ReconciliationError("reconciled graph failed a structural invariant") from error

    decisions = tuple(review_decisions)
    return (
        append_review_decisions(
            graph,
            decisions,
            known_category_codes=known_category_codes,
        )
        if decisions
        else graph
    )


def append_review_decisions(
    graph: QuestionnaireRoutingGraph,
    decisions: Iterable[ReviewDecision],
    *,
    known_category_codes: KnownCategoryCodes | None = None,
) -> QuestionnaireRoutingGraph:
    """Append source-cited decisions and project only active decisions into accepted edges."""
    appended = tuple(decisions)
    if not appended:
        return graph
    audit = graph.routing_audit
    candidates = {item.candidate_id: item for item in audit.candidate_edges}
    discrepancies = {item.discrepancy_id: item for item in audit.discrepancies}
    evidence = {item.evidence_id: item for item in audit.evidence}
    spans = {item.span_id: item for item in audit.source_spans}
    existing_ids = {item.decision_id for item in audit.review_decisions}
    new_ids = [item.decision_id for item in appended]
    if len(set(new_ids)) != len(new_ids) or existing_ids.intersection(new_ids):
        raise ReconciliationError("review decision identifiers must be append-only and unique")
    for decision in appended:
        _validate_review_decision(decision, candidates, discrepancies, evidence, spans)

    all_decisions = audit.review_decisions + appended
    active_decisions = _active_review_decisions(all_decisions)
    inventory_by_id = _unique_items(audit.inventory)
    nodes_by_id = _unique_nodes(graph.nodes)
    resolver = IdentityResolver(audit.inventory)
    evidence_positions = {
        record.evidence_id: position for position, record in enumerate(audit.evidence)
    }

    edges = [edge for edge in graph.edges if edge.review_decision_id is None]
    decision_diagnostics: list[RoutingDiagnostic] = []
    for decision in active_decisions:
        if decision.action is ReviewAction.confirm_candidate:
            for candidate_id in decision.candidate_ids:
                edges.append(
                    _edge_from_confirmed_candidate(
                        candidates[candidate_id],
                        decision,
                        resolver,
                        inventory_by_id,
                    )
                )
        elif decision.action is ReviewAction.replace_candidate:
            edges.append(
                _edge_from_replacement(
                    decision,
                    resolver,
                    inventory_by_id,
                    nodes_by_id,
                )
            )
        elif decision.action is ReviewAction.unresolved:
            decision_diagnostics.append(
                build_reconciliation_diagnostic(
                    "UNRESOLVED_REVIEW",
                    evidence_ids=decision.evidence_ids,
                    candidate_ids=decision.candidate_ids,
                )
            )

    accepted_edges = _merge_and_sort_edges(tuple(edges), inventory_by_id, evidence_positions)
    _ensure_one_default(accepted_edges)
    updated_candidates = _apply_candidate_statuses(
        audit.candidate_edges,
        active_decisions,
    )
    resolved_discrepancies = _apply_discrepancy_resolutions(
        audit.discrepancies,
        active_decisions,
    )
    try:
        updated_audit = RoutingAudit(
            source_binding=audit.source_binding,
            inventory=audit.inventory,
            source_spans=audit.source_spans,
            evidence=audit.evidence,
            candidate_edges=updated_candidates,
            discrepancies=resolved_discrepancies,
            review_decisions=all_decisions,
        )
        base_diagnostics = tuple(
            diagnostic for diagnostic in graph.diagnostics if diagnostic.code != "UNRESOLVED_REVIEW"
        )
        return validate_routing_graph(
            QuestionnaireRoutingGraph(
                schema_version=graph.schema_version,
                entry_node_ids=graph.entry_node_ids,
                nodes=_derive_adjacency(graph.nodes, accepted_edges),
                edges=accepted_edges,
                loops=(),
                diagnostics=base_diagnostics + tuple(decision_diagnostics),
                routing_audit=updated_audit,
            ),
            known_category_codes=known_category_codes,
        )
    except ValidationError as error:
        raise ReconciliationError(
            "review decisions violate the append-only audit contract"
        ) from error


def _unique_items(items: tuple[InventoryItem, ...]) -> dict[str, InventoryItem]:
    indexed = {item.node_id: item for item in items}
    if len(indexed) != len(items):
        raise ReconciliationError("inventory node identifiers must be unique")
    return indexed


def _unique_nodes(nodes: tuple[RoutingNode, ...]) -> dict[str, RoutingNode]:
    indexed = {node.node_id: node for node in nodes}
    if len(indexed) != len(nodes):
        raise ReconciliationError("canonical node identifiers must be unique")
    return indexed


def _validate_verified_evidence(verified: VerifiedEvidence) -> None:
    spans = {span.span_id: span for span in verified.source_spans}
    if len(spans) != len(verified.source_spans):
        raise ReconciliationError("verified source span identifiers must be unique")
    evidence_ids = {record.evidence_id for record in verified.records}
    if len(evidence_ids) != len(verified.records):
        raise ReconciliationError("verified evidence identifiers must be unique")
    for record in verified.records:
        span = spans.get(record.observation.source_span.span_id)
        if span is None or span != record.observation.source_span:
            raise ReconciliationError("every evidence record must cite one verified source span")


def _validate_source_priorities(
    supplied: Mapping[str, int] | None,
    verified: VerifiedEvidence,
) -> dict[str, int]:
    priorities = dict(supplied or {})
    evidence = {record.evidence_id: record.observation for record in verified.records}
    unknown = set(priorities).difference(evidence)
    if unknown:
        raise ReconciliationError("source priorities reference unknown evidence")
    for evidence_id, priority in priorities.items():
        if isinstance(priority, bool) or not isinstance(priority, int) or priority < 0:
            raise ReconciliationError("source priority must be one nonnegative integer")
        observation = evidence[evidence_id]
        if not isinstance(
            observation, TransitionEvidence
        ) or observation.transition_kind.value not in {
            EdgeKind.conditional.value,
            EdgeKind.default.value,
        }:
            raise ReconciliationError(
                "source priority is valid only for conditional or default flow"
            )
        if not observation.explicitly_stated:
            raise ReconciliationError("source priority requires explicitly ordered source evidence")
    return priorities


def _build_transition_claims(
    records: tuple[tuple[int, str, TransitionEvidence], ...],
    resolver: IdentityResolver,
    inventory_by_id: Mapping[str, InventoryItem],
    priorities: Mapping[str, int],
) -> list[_TransitionClaim]:
    grouped: dict[str, _TransitionClaim] = {}
    for position, evidence_id, observation in records:
        source_resolution = _resolve_reference(resolver, observation.source)
        if source_resolution.status != "resolved" or source_resolution.node_id is None:
            raise ReconciliationError("transition source must resolve to one exact inventory item")
        source_item = inventory_by_id[source_resolution.node_id]
        target_resolution = _resolve_reference(
            resolver,
            observation.target,
            default_section_path=source_item.section_path,
        )
        condition_resolution = (
            _resolve_condition(
                observation.condition,
                resolver,
                default_section_path=source_item.section_path,
            )
            if observation.condition is not None
            else None
        )
        key = stable_identifier(
            "claim",
            {
                "condition": _condition_identity(
                    condition_resolution.condition
                    if condition_resolution is not None
                    and condition_resolution.condition is not None
                    else observation.condition
                ),
                "fuzzy": observation.ambiguity_note is not None,
                "kind": observation.transition_kind.value,
                "source_node_id": source_resolution.node_id,
                "target": _target_identity(target_resolution, observation.target),
            },
        )
        claim = grouped.get(key)
        if claim is None:
            claim = _TransitionClaim(
                first_position=position,
                source_node_id=source_resolution.node_id,
                source_item=source_item,
                target_resolution=target_resolution,
                target_reference=observation.target,
                kind=EdgeKind(observation.transition_kind.value),
                extracted_condition=observation.condition,
                condition_resolution=condition_resolution,
            )
            grouped[key] = claim
        claim.evidence_ids.append(evidence_id)
        claim.observations.append(observation)
        if evidence_id in priorities:
            claim.priorities.append(priorities[evidence_id])
        _mark_local_claim_issues(claim, observation, condition_resolution)
    claims = sorted(grouped.values(), key=lambda item: item.first_position)
    for claim in claims:
        if len(set(claim.priorities)) > 1:
            claim.issues.add("CONFLICTING_PRIORITY")
        _validate_native_projection(claim)
    return claims


def _resolve_reference(
    resolver: IdentityResolver,
    reference: ItemReference,
    *,
    default_section_path: tuple[str, ...] = (),
) -> ReferenceResolution:
    try:
        return resolver.resolve(reference, default_section_path=default_section_path)
    except IdentityError:
        return ReferenceResolution(status="unresolved", node_id=None, candidate_node_ids=())


def _resolve_condition(
    condition: ExtractedRoutingCondition,
    resolver: IdentityResolver,
    *,
    default_section_path: tuple[str, ...],
) -> ConditionResolution:
    try:
        return resolve_extracted_condition(
            condition,
            resolver,
            default_section_path=default_section_path,
        )
    except IdentityError:
        return ConditionResolution(
            condition=None,
            references=(
                ReferenceResolution(status="unresolved", node_id=None, candidate_node_ids=()),
            ),
        )


def _mark_local_claim_issues(
    claim: _TransitionClaim,
    observation: TransitionEvidence,
    condition_resolution: ConditionResolution | None,
) -> None:
    if claim.target_resolution.status == "ambiguous":
        claim.issues.add("AMBIGUOUS_TARGET")
    elif claim.target_resolution.status == "unresolved":
        claim.issues.add("UNRESOLVED_TARGET")
    if observation.ambiguity_note is not None:
        claim.issues.add("FUZZY_TARGET")
    if observation.condition is not None:
        if observation.condition.operator is ConditionOperator.opaque:
            claim.issues.add("OPAQUE_CONDITION")
        if condition_resolution is None or condition_resolution.condition is None:
            claim.issues.add("AMBIGUOUS_CONDITION_REFERENCE")
    if (
        not observation.explicitly_stated
        and observation.transition_kind.value != EdgeKind.sequential.value
        and observation.origin is not EvidenceOrigin.native_parser
    ):
        claim.issues.add("SEQUENTIAL_UNCLEAR")


def _validate_native_projection(claim: _TransitionClaim) -> None:
    canonical = claim.canonical_condition
    for observation in claim.observations:
        native = observation.native_expression
        if native is None:
            continue
        projection = native.canonical_projection
        if projection.operator is ConditionOperator.opaque:
            claim.issues.add("OPAQUE_CONDITION")
        elif canonical is not None and _condition_identity(projection) != _condition_identity(
            canonical
        ):
            claim.issues.add("CONFLICTING_CONDITION")


def _mark_incoming_disagreements(claims: list[_TransitionClaim]) -> None:
    by_source: dict[str, list[_TransitionClaim]] = {}
    for claim in claims:
        by_source.setdefault(claim.source_node_id, []).append(claim)

    for source_claims in by_source.values():
        outgoing = [
            claim
            for claim in source_claims
            if claim.has_outgoing_support and not claim.has_incoming_support
        ]
        incoming = [
            claim
            for claim in source_claims
            if claim.has_incoming_support and not claim.has_outgoing_support
        ]
        unmatched_incoming: list[_TransitionClaim] = []
        unmatched_outgoing = list(outgoing)
        for incoming_claim in incoming:
            matching = [
                outgoing_claim
                for outgoing_claim in outgoing
                if _branch_identity(outgoing_claim) == _branch_identity(incoming_claim)
            ]
            if not matching:
                unmatched_incoming.append(incoming_claim)
                continue
            for outgoing_claim in matching:
                outgoing_claim.issues.add("CONFLICTING_TARGET")
                incoming_claim.issues.add("CONFLICTING_TARGET")
                if outgoing_claim in unmatched_outgoing:
                    unmatched_outgoing.remove(outgoing_claim)

        for claim in unmatched_incoming:
            claim.issues.add("INCOMING_ONLY")


def _branch_identity(claim: _TransitionClaim) -> str:
    return stable_identifier(
        "branch",
        {
            "condition": _condition_identity(
                claim.canonical_condition or claim.extracted_condition
            ),
            "kind": claim.kind.value,
            "priority": claim.priority,
        },
    )


def _mark_default_and_priority_conflicts(claims: list[_TransitionClaim]) -> None:
    by_source: dict[str, list[_TransitionClaim]] = {}
    for claim in claims:
        by_source.setdefault(claim.source_node_id, []).append(claim)
    for source_claims in by_source.values():
        defaults = [claim for claim in source_claims if claim.kind is EdgeKind.default]
        if len(defaults) > 1:
            for claim in defaults:
                claim.issues.add("MULTIPLE_DEFAULTS")
        by_priority: dict[int, list[_TransitionClaim]] = {}
        for claim in source_claims:
            if claim.priority is not None:
                by_priority.setdefault(claim.priority, []).append(claim)
        for same_priority in by_priority.values():
            if len(same_priority) > 1:
                for claim in same_priority:
                    claim.issues.add("CONFLICTING_PRIORITY")


def _mark_sequential_inference_issues(
    claims: list[_TransitionClaim],
    inventory: tuple[InventoryItem, ...],
) -> None:
    for claim in claims:
        if claim.kind is not EdgeKind.sequential or any(
            observation.explicitly_stated for observation in claim.observations
        ):
            continue
        target = next(
            (item for item in inventory if item.node_id == claim.target_node_id),
            None,
        )
        if target is None:
            continue
        if target.source_order <= claim.source_item.source_order:
            claim.issues.add("INFERRED_CYCLE")
            continue
        successors = tuple(
            item
            for item in inventory
            if item.source_order > claim.source_item.source_order
            and item.section_path == claim.source_item.section_path
            and item.parent_node_id == claim.source_item.parent_node_id
            and item.kind is not NodeKind.entry
        )
        expected = successors[0] if successors else None
        if expected is None or expected.node_id != target.node_id:
            claim.issues.add("SEQUENTIAL_UNCLEAR")
            continue
        bypassed = any(
            other is not claim
            and other.source_node_id == claim.source_node_id
            and other.target_node_id != claim.target_node_id
            and other.has_outgoing_support
            and any(observation.explicitly_stated for observation in other.observations)
            and other.kind in {EdgeKind.default, EdgeKind.sequential, EdgeKind.unconditional}
            for other in claims
        )
        if bypassed:
            claim.issues.add("SEQUENTIAL_BYPASSED")


def _build_candidates(claims: list[_TransitionClaim]) -> tuple[CandidateEdge, ...]:
    candidates: list[CandidateEdge] = []
    for claim in claims:
        if not claim.issues:
            continue
        status = (
            CandidateStatus.needs_human_review
            if claim.issues.intersection(_HUMAN_REVIEW_ISSUES)
            else CandidateStatus.needs_agent_review
        )
        payload = {
            "condition": _condition_identity(
                claim.canonical_condition or claim.extracted_condition
            ),
            "evidence_ids": claim.evidence_ids,
            "issues": sorted(claim.issues),
            "kind": claim.kind.value,
            "priority": claim.priority,
            "source_node_id": claim.source_node_id,
            "target": _target_identity(claim.target_resolution, claim.target_reference),
        }
        candidate_id = stable_identifier("candidate", payload)
        claim.candidate_id = candidate_id
        candidates.append(
            CandidateEdge(
                candidate_id=candidate_id,
                source_node_id=claim.source_node_id,
                target_node_id=claim.target_node_id,
                target_reference=claim.target_reference,
                kind=claim.kind,
                condition=claim.extracted_condition,
                priority=claim.priority,
                evidence_ids=tuple(claim.evidence_ids),
                confidence=max(item.confidence for item in claim.observations),
                status=status,
            )
        )
    return tuple(candidates)


def _build_discrepancies_and_diagnostics(
    claims: list[_TransitionClaim],
) -> tuple[tuple[RoutingDiscrepancy, ...], tuple[RoutingDiagnostic, ...]]:
    discrepancies: list[RoutingDiscrepancy] = []
    diagnostics: list[RoutingDiagnostic] = []
    for issue in _ISSUE_ORDER:
        sources = tuple(
            dict.fromkeys(claim.source_node_id for claim in claims if issue in claim.issues)
        )
        for source_node_id in sources:
            affected = tuple(
                claim
                for claim in claims
                if issue in claim.issues and claim.source_node_id == source_node_id
            )
            candidate_ids = tuple(
                claim.candidate_id for claim in affected if claim.candidate_id is not None
            )
            evidence_ids = _ordered_unique(
                evidence_id for claim in affected for evidence_id in claim.evidence_ids
            )
            source_span_ids = _ordered_unique(
                observation.source_span.span_id
                for claim in affected
                for observation in claim.observations
            )
            discrepancy = build_reconciliation_discrepancy(
                _DISCREPANCY_BY_ISSUE[issue],
                candidate_ids=candidate_ids,
                evidence_ids=evidence_ids,
                source_span_ids=source_span_ids,
                needs_human_review=bool(set(candidate_ids))
                and any(claim.issues.intersection(_HUMAN_REVIEW_ISSUES) for claim in affected),
            )
            discrepancies.append(discrepancy)
            target_ids = _ordered_unique(
                claim.target_node_id for claim in affected if claim.target_node_id is not None
            )
            diagnostics.append(
                build_reconciliation_diagnostic(
                    issue,
                    node_ids=(source_node_id,)
                    + tuple(target for target in target_ids if target != source_node_id),
                    evidence_ids=evidence_ids,
                    candidate_ids=candidate_ids,
                )
            )
    return tuple(discrepancies), tuple(diagnostics)


def _edge_from_claim(claim: _TransitionClaim) -> RoutingEdge:
    if claim.target_node_id is None:
        raise ReconciliationError("accepted edge target must be canonical")
    return _make_edge(
        source_node_id=claim.source_node_id,
        target_node_id=claim.target_node_id,
        kind=claim.kind,
        condition=claim.canonical_condition,
        priority=claim.priority,
        evidence_ids=tuple(claim.evidence_ids),
        confidence=max(item.confidence for item in claim.observations),
        review_decision_id=None,
    )


def _make_edge(
    *,
    source_node_id: str,
    target_node_id: str,
    kind: EdgeKind,
    condition: CanonicalRoutingCondition | None,
    priority: int | None,
    evidence_ids: tuple[str, ...],
    confidence: float,
    review_decision_id: str | None,
) -> RoutingEdge:
    payload = {
        "condition": _condition_identity(condition),
        "edge_schema": "routing-edge-v1",
        "kind": kind.value,
        "priority": priority,
        "source_node_id": source_node_id,
        "target_node_id": target_node_id,
    }
    return RoutingEdge(
        edge_id=stable_identifier("edge", payload),
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        kind=kind,
        condition=condition,
        priority=priority,
        evidence_ids=evidence_ids,
        confidence=confidence,
        review_decision_id=review_decision_id,
    )


def _reconcile_activation_evidence(
    verified: VerifiedEvidence,
    resolver: IdentityResolver,
    inventory_by_id: Mapping[str, InventoryItem],
    nodes_by_id: Mapping[str, RoutingNode],
) -> tuple[dict[str, CanonicalRoutingCondition], tuple[RoutingDiagnostic, ...]]:
    grouped: dict[str, list[tuple[str, ActivationEvidence, CanonicalRoutingCondition]]] = {}
    diagnostics: list[RoutingDiagnostic] = []
    for record in verified.records:
        observation = record.observation
        if not isinstance(observation, ActivationEvidence):
            continue
        item_resolution = _resolve_reference(resolver, observation.item)
        if item_resolution.status != "resolved" or item_resolution.node_id is None:
            code = (
                "AMBIGUOUS_ACTIVATION_REFERENCE"
                if item_resolution.status == "ambiguous"
                else "UNRESOLVED_ACTIVATION_REFERENCE"
            )
            diagnostics.append(
                build_reconciliation_diagnostic(code, evidence_ids=(record.evidence_id,))
            )
            continue
        item = inventory_by_id[item_resolution.node_id]
        condition = _resolve_condition(
            observation.condition,
            resolver,
            default_section_path=item.section_path,
        ).condition
        if observation.ambiguity_note is not None:
            diagnostics.append(
                build_reconciliation_diagnostic(
                    "FUZZY_ACTIVATION_REFERENCE",
                    node_ids=(item.node_id,),
                    evidence_ids=(record.evidence_id,),
                )
            )
            continue
        if condition is None:
            diagnostics.append(
                build_reconciliation_diagnostic(
                    "AMBIGUOUS_ACTIVATION_REFERENCE",
                    node_ids=(item.node_id,),
                    evidence_ids=(record.evidence_id,),
                )
            )
            continue
        native = observation.native_expression
        if condition.operator is ConditionOperator.opaque or (
            native is not None and native.canonical_projection.operator is ConditionOperator.opaque
        ):
            diagnostics.append(
                build_reconciliation_diagnostic(
                    "OPAQUE_ACTIVATION_CONDITION",
                    node_ids=(item.node_id,),
                    evidence_ids=(record.evidence_id,),
                )
            )
            continue
        grouped.setdefault(item.node_id, []).append((record.evidence_id, observation, condition))

    updates: dict[str, CanonicalRoutingCondition] = {}
    for node_id, records in grouped.items():
        conditions: dict[str, CanonicalRoutingCondition] = {}
        for _evidence_id, _observation, condition in records:
            conditions.setdefault(_condition_key(condition), condition)
        existing = nodes_by_id[node_id].activation_condition
        if existing is not None:
            conditions.setdefault(_condition_key(existing), existing)
        evidence_ids = tuple(item[0] for item in records)
        if len(conditions) == 1:
            updates[node_id] = next(iter(conditions.values()))
        else:
            diagnostics.append(
                build_reconciliation_diagnostic(
                    "ACTIVATION_CONFLICT",
                    node_ids=(node_id,),
                    evidence_ids=evidence_ids,
                )
            )
    return updates, tuple(diagnostics)


def _derive_adjacency(
    nodes: Iterable[RoutingNode],
    edges: tuple[RoutingEdge, ...],
) -> tuple[RoutingNode, ...]:
    ordered_nodes = tuple(nodes)
    outgoing: dict[str, list[RoutingEdge]] = {node.node_id: [] for node in ordered_nodes}
    incoming: dict[str, list[RoutingEdge]] = {node.node_id: [] for node in ordered_nodes}
    for edge in edges:
        outgoing[edge.source_node_id].append(edge)
        incoming[edge.target_node_id].append(edge)
    return tuple(
        node.model_copy(
            update={
                "incoming_edge_ids": tuple(edge.edge_id for edge in incoming[node.node_id]),
                "next_node_ids": _ordered_unique(
                    edge.target_node_id for edge in outgoing[node.node_id]
                ),
                "outgoing_edge_ids": tuple(edge.edge_id for edge in outgoing[node.node_id]),
                "previous_node_ids": _ordered_unique(
                    edge.source_node_id for edge in incoming[node.node_id]
                ),
            }
        )
        for node in ordered_nodes
    )


def _merge_and_sort_edges(
    edges: tuple[RoutingEdge, ...],
    inventory_by_id: Mapping[str, InventoryItem],
    evidence_positions: Mapping[str, int],
) -> tuple[RoutingEdge, ...]:
    merged: dict[str, RoutingEdge] = {}
    for edge in edges:
        existing = merged.get(edge.edge_id)
        if existing is None:
            merged[edge.edge_id] = edge
            continue
        evidence_ids = _ordered_unique(existing.evidence_ids + edge.evidence_ids)
        merged[edge.edge_id] = existing.model_copy(
            update={
                "confidence": max(existing.confidence, edge.confidence),
                "evidence_ids": evidence_ids,
                "review_decision_id": edge.review_decision_id or existing.review_decision_id,
            }
        )

    def edge_order(edge: RoutingEdge) -> tuple[int, int, int, str]:
        source_order = inventory_by_id.get(edge.source_node_id)
        first_evidence = min(
            (
                evidence_positions.get(evidence_id, len(evidence_positions))
                for evidence_id in edge.evidence_ids
            ),
            default=len(evidence_positions),
        )
        return (
            source_order.source_order if source_order is not None else len(inventory_by_id),
            edge.priority if edge.priority is not None else 2**31,
            first_evidence,
            edge.edge_id,
        )

    return tuple(sorted(merged.values(), key=edge_order))


def _ensure_one_default(edges: tuple[RoutingEdge, ...]) -> None:
    defaults: dict[str, int] = {}
    for edge in edges:
        if edge.kind is EdgeKind.default:
            defaults[edge.source_node_id] = defaults.get(edge.source_node_id, 0) + 1
    if any(count > 1 for count in defaults.values()):
        raise ReconciliationError("review decisions cannot accept conflicting default edges")


def _validate_review_decision(
    decision: ReviewDecision,
    candidates: Mapping[str, CandidateEdge],
    discrepancies: Mapping[str, RoutingDiscrepancy],
    evidence: Mapping[str, EvidenceRecord],
    spans: Mapping[str, object],
) -> None:
    if any(candidate_id not in candidates for candidate_id in decision.candidate_ids):
        raise ReconciliationError("review decision must reference existing candidates")
    if any(discrepancy_id not in discrepancies for discrepancy_id in decision.discrepancy_ids):
        raise ReconciliationError("review decision must reference existing discrepancies")
    candidate_evidence = {
        evidence_id
        for candidate_id in decision.candidate_ids
        for evidence_id in candidates[candidate_id].evidence_ids
    }
    if any(evidence_id not in candidate_evidence for evidence_id in decision.evidence_ids):
        raise ReconciliationError("review decision evidence must be candidate evidence")
    if any(evidence_id not in evidence for evidence_id in decision.evidence_ids):
        raise ReconciliationError("review decision evidence must exist")
    cited_spans = {
        evidence[evidence_id].observation.source_span.span_id
        for evidence_id in decision.evidence_ids
    }
    if any(
        span_id not in spans or span_id not in cited_spans for span_id in decision.cited_span_ids
    ):
        raise ReconciliationError("review decision cited spans must belong to its evidence")
    discrepancy_candidates = {
        candidate_id
        for discrepancy_id in decision.discrepancy_ids
        for candidate_id in discrepancies[discrepancy_id].candidate_ids
    }
    if any(candidate_id not in discrepancy_candidates for candidate_id in decision.candidate_ids):
        raise ReconciliationError("review candidates must belong to the cited discrepancies")
    replacement = decision.replacement
    if replacement is not None and any(
        evidence_id not in decision.evidence_ids for evidence_id in replacement.evidence_ids
    ):
        raise ReconciliationError("replacement evidence must be cited by its review decision")


def _active_review_decisions(decisions: tuple[ReviewDecision, ...]) -> tuple[ReviewDecision, ...]:
    superseded = {
        decision.supersedes_decision_id
        for decision in decisions
        if decision.supersedes_decision_id is not None
    }
    return tuple(decision for decision in decisions if decision.decision_id not in superseded)


def _edge_from_confirmed_candidate(
    candidate: CandidateEdge,
    decision: ReviewDecision,
    resolver: IdentityResolver,
    inventory_by_id: Mapping[str, InventoryItem],
) -> RoutingEdge:
    if candidate.target_node_id is None:
        raise ReconciliationError("ambiguous or unresolved candidates require replacement content")
    source_item = inventory_by_id[candidate.source_node_id]
    condition = (
        _resolve_condition(
            candidate.condition,
            resolver,
            default_section_path=source_item.section_path,
        ).condition
        if candidate.condition is not None
        else None
    )
    if candidate.condition is not None and (
        condition is None or condition.operator is ConditionOperator.opaque
    ):
        raise ReconciliationError("review cannot confirm an unresolved or opaque condition")
    return _make_edge(
        source_node_id=candidate.source_node_id,
        target_node_id=candidate.target_node_id,
        kind=candidate.kind,
        condition=condition,
        priority=candidate.priority,
        evidence_ids=candidate.evidence_ids,
        confidence=max(candidate.confidence, decision.confidence),
        review_decision_id=decision.decision_id,
    )


def _edge_from_replacement(
    decision: ReviewDecision,
    resolver: IdentityResolver,
    inventory_by_id: Mapping[str, InventoryItem],
    nodes_by_id: Mapping[str, RoutingNode],
) -> RoutingEdge:
    replacement = decision.replacement
    if replacement is None:
        raise ReconciliationError("replace review requires replacement content")
    if (
        replacement.source_node_id not in nodes_by_id
        or replacement.target_node_id not in nodes_by_id
    ):
        raise ReconciliationError("replacement endpoints must be canonical graph nodes")
    source_item = inventory_by_id.get(replacement.source_node_id)
    if source_item is None:
        raise ReconciliationError("replacement source must exist in the inventory")
    condition = (
        _resolve_condition(
            replacement.condition,
            resolver,
            default_section_path=source_item.section_path,
        ).condition
        if replacement.condition is not None
        else None
    )
    if replacement.condition is not None and (
        condition is None or condition.operator is ConditionOperator.opaque
    ):
        raise ReconciliationError("replacement condition must resolve exactly")
    return _make_edge(
        source_node_id=replacement.source_node_id,
        target_node_id=replacement.target_node_id,
        kind=replacement.kind,
        condition=condition,
        priority=replacement.priority,
        evidence_ids=replacement.evidence_ids,
        confidence=decision.confidence,
        review_decision_id=decision.decision_id,
    )


def _apply_discrepancy_resolutions(
    discrepancies: tuple[RoutingDiscrepancy, ...],
    active_decisions: tuple[ReviewDecision, ...],
) -> tuple[RoutingDiscrepancy, ...]:
    decision_by_discrepancy: dict[str, ReviewDecision] = {}
    for decision in active_decisions:
        for discrepancy_id in decision.discrepancy_ids:
            decision_by_discrepancy[discrepancy_id] = decision
    return tuple(
        discrepancy.model_copy(
            update={
                "needs_human_review": (
                    decision_by_discrepancy[discrepancy.discrepancy_id].needs_human_review
                    if discrepancy.discrepancy_id in decision_by_discrepancy
                    else discrepancy.needs_human_review
                ),
                "resolved_by_decision_id": (
                    decision_by_discrepancy[discrepancy.discrepancy_id].decision_id
                    if discrepancy.discrepancy_id in decision_by_discrepancy
                    and decision_by_discrepancy[discrepancy.discrepancy_id].action
                    is not ReviewAction.unresolved
                    else None
                ),
            }
        )
        for discrepancy in discrepancies
    )


def _apply_candidate_statuses(
    candidates: tuple[CandidateEdge, ...],
    active_decisions: tuple[ReviewDecision, ...],
) -> tuple[CandidateEdge, ...]:
    decision_by_candidate: dict[str, ReviewDecision] = {}
    for decision in active_decisions:
        for candidate_id in decision.candidate_ids:
            decision_by_candidate[candidate_id] = decision

    def current_status(candidate: CandidateEdge) -> CandidateStatus:
        decision = decision_by_candidate.get(candidate.candidate_id)
        if decision is None:
            return candidate.status
        if decision.action is ReviewAction.confirm_candidate:
            return CandidateStatus.accepted
        if decision.action is ReviewAction.unresolved:
            return CandidateStatus.needs_human_review
        return CandidateStatus.rejected

    return tuple(
        candidate.model_copy(update={"status": current_status(candidate)})
        for candidate in candidates
    )


def _condition_key(condition: CanonicalRoutingCondition) -> str:
    return json.dumps(
        _condition_identity(condition),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _condition_identity(
    condition: CanonicalRoutingCondition | ExtractedRoutingCondition | None,
) -> object:
    if condition is None:
        return None
    data = condition.model_dump(mode="json")
    _normalize_condition_data(data)
    return data


def _normalize_condition_data(value: object) -> None:
    if isinstance(value, dict):
        value.pop("raw_text", None)
        reference = value.get("item_reference")
        if isinstance(reference, dict):
            identity = reference.get("source_item_id") or reference.get("raw_reference")
            node_kind = reference.get("node_kind")
            section_path = reference.get("section_path")
            try:
                alias = normalized_alias(str(identity))
            except IdentityError:
                alias = _normalize_text(str(identity))
            reference.clear()
            reference.update(
                {
                    "alias": alias,
                    "node_kind": node_kind,
                    "section_path": section_path,
                }
            )
        for nested in value.values():
            _normalize_condition_data(nested)
    elif isinstance(value, list):
        for nested in value:
            _normalize_condition_data(nested)


def _target_identity(resolution: ReferenceResolution, reference: ItemReference) -> object:
    if resolution.status == "resolved":
        return {"node_id": resolution.node_id, "status": resolution.status}
    try:
        alias = normalized_alias(reference.source_item_id or reference.raw_reference)
    except IdentityError:
        alias = _normalize_text(reference.source_item_id or reference.raw_reference)
    return {
        "alias": alias,
        "candidate_node_ids": resolution.candidate_node_ids,
        "node_kind": reference.node_kind.value,
        "section_path": normalize_section_path(reference.section_path),
        "status": resolution.status,
    }


def _normalize_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _ordered_unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


__all__ = [
    "ReconciliationError",
    "append_review_decisions",
    "reconcile_routing_graph",
]
