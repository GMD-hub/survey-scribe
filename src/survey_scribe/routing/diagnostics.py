"""Stable safe diagnostics for deterministic routing graph processing."""

from __future__ import annotations

import hashlib
import json

from survey_scribe.models.routing import (
    DiagnosticSeverity,
    DiscrepancyKind,
    RoutingDiagnostic,
    RoutingDiscrepancy,
)

_DIAGNOSTIC_MESSAGES = {
    "ACTIVATION_CONFLICT": "Independent activation evidence does not agree.",
    "ACTIVATION_ROUTING_CONFLICT": "Activation and routing evidence do not agree.",
    "ADJACENCY_INDEX_MISMATCH": "Materialized adjacency does not match accepted edges.",
    "AMBIGUOUS_ACTIVATION_REFERENCE": "An activation reference is not unambiguous.",
    "AMBIGUOUS_CONDITION_REFERENCE": "A routing condition reference is not unambiguous.",
    "AMBIGUOUS_TARGET": "A routing target has more than one exact identity match.",
    "CONDITION_UNKNOWN_REFERENCE": "A condition references an unknown controlling question.",
    "CONDITION_VALUE_NOT_IN_CATEGORIES": "A condition uses an unknown categorical code.",
    "CONTAINMENT_CYCLE": "The containment hierarchy contains a cycle.",
    "CONTAINMENT_DANGLING_PARENT": "A containment parent does not exist.",
    "CONTAINMENT_ENTRY_INVALID": "A container entry does not have one valid entry edge.",
    "CONTAINMENT_INDEX_MISMATCH": "Derived containment children do not match node order.",
    "CONFLICTING_CONDITION": "Independent routing evidence has conflicting conditions.",
    "CONFLICTING_PRIORITY": "Source-defined route priorities conflict.",
    "CONFLICTING_TARGET": "Independent routing evidence has conflicting targets.",
    "DANGLING_TARGET": "An accepted edge endpoint does not exist.",
    "DEAD_END_NONTERMINAL": "A reachable nonterminal node has no outgoing transition.",
    "DUPLICATE_EDGE": "An accepted edge identifier or canonical transition is duplicated.",
    "DUPLICATE_NODE_ID": "A canonical node identifier is duplicated.",
    "FUZZY_ACTIVATION_REFERENCE": "Activation evidence uses a non-exact item match.",
    "FUZZY_TARGET": "A routing target depends on a non-exact match.",
    "INCOMING_ONLY": "Incoming evidence has no compatible forward or native claim.",
    "INCOMING_EVIDENCE_MISMATCH": "Independent incoming evidence does not agree.",
    "INFERRED_CYCLE": "An inferred sequential transition would move backward or cycle.",
    "MULTIPLE_DEFAULTS": "A source node has conflicting default transitions.",
    "NO_LOOP_EXIT": "A supported loop region has no known exit.",
    "NO_TERMINAL_PATH": "An entry-reachable region has no proven terminal path.",
    "OPAQUE_ACTIVATION_CONDITION": "An activation condition is opaque and not executable.",
    "OPAQUE_CONDITION": "A routing condition is opaque and not executable.",
    "OVERLAPPING_BRANCH_UNPROVEN": "Conditional branches are not proven disjoint.",
    "SEQUENTIAL_BYPASSED": "An explicit route bypasses the inferred sequential transition.",
    "SEQUENTIAL_UNCLEAR": "A sequential transition is not the unambiguous next item.",
    "TERMINAL_OUTGOING": "A terminal node has an outgoing accepted transition.",
    "UNRESOLVED_ACTIVATION_REFERENCE": "An activation item reference cannot be resolved.",
    "UNRESOLVED_REVIEW": "A review decision requires human resolution.",
    "UNRESOLVED_TARGET": "A routing target cannot be resolved exactly.",
    "UNCOVERED_BRANCH": "Conditional branch coverage is incomplete or cannot be proven.",
    "UNKNOWN_ENTRY_NODE": "A graph entry does not identify a canonical entry node.",
    "UNREACHABLE_NODE": "A canonical node is unreachable from all graph entries.",
    "UNSUPPORTED_CYCLE": "A cycle has inferred flow without direct loop support.",
}

_DISCREPANCY_SUMMARIES = {
    DiscrepancyKind.ambiguous_target: "A target identity requires bounded review.",
    DiscrepancyKind.conflicting_condition: "Transition conditions require bounded review.",
    DiscrepancyKind.conflicting_target: "Transition targets require bounded review.",
    DiscrepancyKind.incoming_mismatch: "Independent incoming evidence requires bounded review.",
    DiscrepancyKind.multiple_defaults: "Default transitions require bounded review.",
    DiscrepancyKind.opaque_condition: "An opaque transition condition requires bounded review.",
    DiscrepancyKind.unsupported_cycle: "An inferred cycle requires bounded review.",
    DiscrepancyKind.unresolved_target: "An unresolved target requires bounded review.",
    DiscrepancyKind.other: "Routing evidence requires bounded review.",
}


def stable_identifier(namespace: str, payload: object) -> str:
    """Return a deterministic identifier from normalized JSON content."""
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"{namespace}:{hashlib.sha256(encoded).hexdigest()}"


def build_reconciliation_diagnostic(
    code: str,
    *,
    severity: DiagnosticSeverity = DiagnosticSeverity.warning,
    node_ids: tuple[str, ...] = (),
    edge_ids: tuple[str, ...] = (),
    evidence_ids: tuple[str, ...] = (),
    candidate_ids: tuple[str, ...] = (),
) -> RoutingDiagnostic:
    """Build one fixed-message diagnostic with a stable content identifier."""
    message = _DIAGNOSTIC_MESSAGES.get(code, "Routing evidence requires bounded review.")
    payload = {
        "candidate_ids": candidate_ids,
        "code": code,
        "edge_ids": edge_ids,
        "evidence_ids": evidence_ids,
        "node_ids": node_ids,
        "severity": severity.value,
    }
    return RoutingDiagnostic(
        diagnostic_id=stable_identifier("diagnostic", payload),
        code=code,
        severity=severity,
        message=message,
        node_ids=node_ids,
        edge_ids=edge_ids,
        evidence_ids=evidence_ids,
        candidate_ids=candidate_ids,
    )


def build_reconciliation_discrepancy(
    kind: DiscrepancyKind,
    *,
    candidate_ids: tuple[str, ...],
    evidence_ids: tuple[str, ...],
    source_span_ids: tuple[str, ...],
    needs_human_review: bool,
) -> RoutingDiscrepancy:
    """Build one stable discrepancy without source-derived text."""
    payload = {
        "candidate_ids": candidate_ids,
        "evidence_ids": evidence_ids,
        "kind": kind.value,
        "source_span_ids": source_span_ids,
    }
    return RoutingDiscrepancy(
        discrepancy_id=stable_identifier("discrepancy", payload),
        kind=kind,
        candidate_ids=candidate_ids,
        evidence_ids=evidence_ids,
        source_span_ids=source_span_ids,
        summary=_DISCREPANCY_SUMMARIES.get(
            kind,
            "Routing evidence requires bounded review.",
        ),
        needs_human_review=needs_human_review,
        resolved_by_decision_id=None,
    )


__all__ = [
    "build_reconciliation_diagnostic",
    "build_reconciliation_discrepancy",
    "stable_identifier",
]
