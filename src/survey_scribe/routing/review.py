"""Bounded discrepancy packet construction and source-citation validation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from typing import TypeVar

from survey_scribe.models.routing import (
    InventoryItem,
    QuestionnaireRoutingGraph,
    ReplacementEdge,
    ReviewDecision,
    RoutingDiscrepancy,
)
from survey_scribe.routing.config import RoutingConfig
from survey_scribe.routing.diagnostics import stable_identifier
from survey_scribe.routing.identity import IdentityError, IdentityResolver, normalized_alias
from survey_scribe.routing.prompts import ReviewerPromptPacket, RoutingReviewerResponse

_SAFE_REVIEW_RATIONALE = "The bounded cited evidence supports the recorded action."


class ReviewValidationError(ValueError):
    """A reviewer output does not cite the supplied bounded evidence closure."""


def build_reviewer_packets(
    graph: QuestionnaireRoutingGraph,
    config: RoutingConfig,
) -> tuple[ReviewerPromptPacket, ...]:
    """Build stable exact-closure packets without unrelated questionnaire regions."""
    audit = graph.routing_audit
    candidates = {item.candidate_id: item for item in audit.candidate_edges}
    evidence = {item.evidence_id: item for item in audit.evidence}
    spans = {item.span_id: item for item in audit.source_spans}
    inventory = {item.node_id: item for item in audit.inventory}
    unresolved = tuple(
        discrepancy
        for discrepancy in audit.discrepancies
        if discrepancy.resolved_by_decision_id is None
    )
    packets: list[ReviewerPromptPacket] = []
    for discrepancies in _coalesced_discrepancy_batches(
        unresolved,
        config.max_discrepancies_per_review_call,
    ):
        packet_candidates = _ordered_records(
            (candidate_id for item in discrepancies for candidate_id in item.candidate_ids),
            candidates,
        )
        evidence_ids = [evidence_id for item in discrepancies for evidence_id in item.evidence_ids]
        evidence_ids.extend(
            evidence_id for candidate in packet_candidates for evidence_id in candidate.evidence_ids
        )
        packet_evidence = _ordered_records(evidence_ids, evidence)
        span_ids = [span_id for item in discrepancies for span_id in item.source_span_ids]
        span_ids.extend(item.observation.source_span.span_id for item in packet_evidence)
        packet_spans = _ordered_records(span_ids, spans)
        endpoint_ids = [candidate.source_node_id for candidate in packet_candidates]
        endpoint_ids.extend(
            candidate.target_node_id
            for candidate in packet_candidates
            if candidate.target_node_id is not None
        )
        for candidate in packet_candidates:
            try:
                target_alias = normalized_alias(
                    candidate.target_reference.source_item_id
                    or candidate.target_reference.raw_reference
                )
            except IdentityError:
                continue
            endpoint_ids.extend(
                item.node_id
                for item in audit.inventory
                if item.kind is candidate.target_reference.node_kind
                and normalized_alias(item.source_item_id or item.raw_reference) == target_alias
            )
        packet_inventory = _ordered_records(endpoint_ids, inventory)
        if not packet_inventory:
            raise ReviewValidationError("review packet has no canonical inventory endpoint")
        packets.append(
            ReviewerPromptPacket(
                item_inventory=packet_inventory,
                discrepancies=discrepancies,
                candidates=packet_candidates,
                evidence=packet_evidence,
                source_spans=packet_spans,
            )
        )
    return tuple(packets)


def build_review_decisions(
    *,
    packet: ReviewerPromptPacket,
    response: RoutingReviewerResponse,
    prompt_version: str,
    prompt_sha256: str,
    max_source_spans_per_decision: int = 8,
    existing_decisions: Sequence[ReviewDecision] = (),
) -> tuple[ReviewDecision, ...]:
    """Validate all citations before creating append-only fixed-prose decisions."""
    expected_discrepancies = tuple(item.discrepancy_id for item in packet.discrepancies)
    if response.reviewed_discrepancy_ids != expected_discrepancies:
        raise ReviewValidationError("review citations are invalid")
    candidates = {item.candidate_id: item for item in packet.candidates}
    discrepancies = {item.discrepancy_id: item for item in packet.discrepancies}
    evidence = {item.evidence_id: item for item in packet.evidence}
    spans = {item.span_id: item for item in packet.source_spans}
    inventory = {item.node_id: item for item in packet.item_inventory}
    inventory_ids = set(inventory)
    resolver = IdentityResolver(packet.item_inventory)
    response_digest = _model_sha256(response)
    decisions: list[ReviewDecision] = []
    latest_by_candidate: dict[str, str] = {}
    decision_candidates: dict[str, tuple[str, ...]] = {}
    superseded = {
        decision.supersedes_decision_id
        for decision in existing_decisions
        if decision.supersedes_decision_id is not None
    }
    for decision in existing_decisions:
        decision_candidates[decision.decision_id] = decision.candidate_ids
        if decision.decision_id in superseded:
            continue
        for candidate_id in decision.candidate_ids:
            latest_by_candidate[candidate_id] = decision.decision_id
    for output in response.decisions:
        if len(output.cited_span_ids) > max_source_spans_per_decision:
            raise ReviewValidationError("review citations are invalid")
        if any(identifier not in discrepancies for identifier in output.discrepancy_ids):
            raise ReviewValidationError("review citations are invalid")
        discrepancy_candidates = {
            candidate_id
            for discrepancy_id in output.discrepancy_ids
            for candidate_id in discrepancies[discrepancy_id].candidate_ids
        }
        if any(
            candidate_id not in candidates or candidate_id not in discrepancy_candidates
            for candidate_id in output.candidate_ids
        ):
            raise ReviewValidationError("review citations are invalid")
        candidate_evidence = {
            evidence_id
            for candidate_id in output.candidate_ids
            for evidence_id in candidates[candidate_id].evidence_ids
        }
        if any(
            evidence_id not in evidence or evidence_id not in candidate_evidence
            for evidence_id in output.evidence_ids
        ):
            raise ReviewValidationError("review citations are invalid")
        cited_evidence_spans = {
            evidence[evidence_id].observation.source_span.span_id
            for evidence_id in output.evidence_ids
        }
        if any(
            span_id not in spans or span_id not in cited_evidence_spans
            for span_id in output.cited_span_ids
        ):
            raise ReviewValidationError("review citations are invalid")
        discrepancy_spans = {
            span_id
            for discrepancy_id in output.discrepancy_ids
            for span_id in discrepancies[discrepancy_id].source_span_ids
        }
        if not set(output.cited_span_ids).issubset(discrepancy_spans):
            raise ReviewValidationError("review citations are invalid")
        replacement = output.replacement
        if replacement is not None and (
            replacement.source_node_id not in inventory_ids
            or replacement.target_node_id not in inventory_ids
            or not set(replacement.evidence_ids).issubset(output.evidence_ids)
            or not _replacement_target_matches(replacement, inventory, resolver)
        ):
            raise ReviewValidationError("review citations are invalid")
        predecessors = {
            latest_by_candidate[candidate_id]
            for candidate_id in output.candidate_ids
            if candidate_id in latest_by_candidate
        }
        if len(predecessors) > 1:
            raise ReviewValidationError("review citations are invalid")
        predecessor_id = next(iter(predecessors), None)
        if (
            predecessor_id is not None
            and decision_candidates[predecessor_id] != output.candidate_ids
        ):
            raise ReviewValidationError("review citations are invalid")
        payload = {
            "action": output.action.value,
            "candidate_ids": output.candidate_ids,
            "cited_span_ids": output.cited_span_ids,
            "discrepancy_ids": output.discrepancy_ids,
            "evidence_ids": output.evidence_ids,
            "prompt_sha256": prompt_sha256,
            "provider_response_sha256": response_digest,
            "supersedes_decision_id": predecessor_id,
            "replacement": (
                replacement.model_dump(mode="json") if replacement is not None else None
            ),
        }
        decision = ReviewDecision(
            decision_id=stable_identifier("review-decision", payload),
            discrepancy_ids=output.discrepancy_ids,
            candidate_ids=output.candidate_ids,
            evidence_ids=output.evidence_ids,
            cited_span_ids=output.cited_span_ids,
            action=output.action,
            replacement=replacement,
            rationale=_SAFE_REVIEW_RATIONALE,
            confidence=output.confidence,
            needs_human_review=output.needs_human_review,
            prompt_version=prompt_version,
            prompt_sha256=prompt_sha256,
            provider_response_sha256=response_digest,
            supersedes_decision_id=predecessor_id,
        )
        decisions.append(decision)
        decision_candidates[decision.decision_id] = decision.candidate_ids
        for candidate_id in decision.candidate_ids:
            latest_by_candidate[candidate_id] = decision.decision_id
    return tuple(decisions)


def _replacement_target_matches(
    replacement: ReplacementEdge,
    inventory: Mapping[str, InventoryItem],
    resolver: IdentityResolver,
) -> bool:
    source = inventory[replacement.source_node_id]
    try:
        resolution = resolver.resolve(
            replacement.target_reference,
            default_section_path=source.section_path,
        )
    except IdentityError:
        return False
    return resolution.status == "resolved" and resolution.node_id == replacement.target_node_id


def _coalesced_discrepancy_batches(
    discrepancies: Sequence[RoutingDiscrepancy],
    maximum: int,
) -> tuple[tuple[RoutingDiscrepancy, ...], ...]:
    remaining = list(discrepancies)
    components: list[tuple[RoutingDiscrepancy, ...]] = []
    while remaining:
        connected: list[RoutingDiscrepancy] = [remaining.pop(0)]
        candidate_ids = set(connected[0].candidate_ids)
        changed = True
        while changed:
            changed = False
            for item in tuple(remaining):
                item_candidates = set(item.candidate_ids)
                if candidate_ids.intersection(item_candidates):
                    remaining.remove(item)
                    connected.append(item)
                    candidate_ids.update(item_candidates)
                    changed = True
        if len(connected) > maximum:
            raise ReviewValidationError("overlapping discrepancies exceed the review packet limit")
        components.append(tuple(connected))

    batches: list[tuple[RoutingDiscrepancy, ...]] = []
    pending: list[RoutingDiscrepancy] = []
    for component in components:
        if pending and len(pending) + len(component) > maximum:
            batches.append(tuple(pending))
            pending = []
        pending.extend(component)
    if pending:
        batches.append(tuple(pending))
    return tuple(batches)


_Record = TypeVar("_Record")


def _ordered_records(
    identifiers: Iterable[str],
    records: Mapping[str, _Record],
) -> tuple[_Record, ...]:
    ordered = tuple(dict.fromkeys(identifiers))
    try:
        return tuple(records[identifier] for identifier in ordered)
    except KeyError:
        raise ReviewValidationError("review packet references are invalid") from None


def _model_sha256(model: RoutingReviewerResponse) -> str:
    payload = json.dumps(
        model.model_dump(mode="json"),
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "ReviewValidationError",
    "build_review_decisions",
    "build_reviewer_packets",
]
