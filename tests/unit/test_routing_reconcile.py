"""Deterministic evidence reconciliation into one canonical routing multigraph."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

import pytest

from survey_scribe.models.routing import (
    CandidateStatus,
    Containment,
    EdgeKind,
    EvidenceRecord,
    InventoryItem,
    ReplacementEdge,
    ReviewAction,
    ReviewDecision,
    RoutingNode,
    RoutingSourceBinding,
    TerminalKind,
)
from survey_scribe.routing.config import RoutingConfig
from survey_scribe.routing.contracts import (
    ActivationEvidence,
    CanonicalRoutingCondition,
    ConditionOperator,
    EvidenceOrigin,
    EvidencePerspective,
    ExtractedRoutingCondition,
    ItemReference,
    NativeExpression,
    NodeKind,
    RoutingScalar,
    SourceSpan,
    TransitionEvidence,
    TransitionKind,
)
from survey_scribe.routing.identity import VerifiedEvidence
from survey_scribe.routing.reconcile import (
    ReconciliationError,
    append_review_decisions,
    reconcile_routing_graph,
)
from survey_scribe.routing.review import build_reviewer_packets


def _reference(
    item_id: str,
    *,
    section: tuple[str, ...] = ("Main",),
    kind: NodeKind = NodeKind.question,
    source_item_id: str | None = None,
    ambiguity_hint: str | None = None,
) -> ItemReference:
    return ItemReference(
        raw_reference=item_id,
        source_item_id=source_item_id,
        canonical_hint=ambiguity_hint,
        section_path=section,
        node_kind=kind,
    )


def _condition(
    item_id: str = "Q1",
    *,
    value: int = 1,
    operator: ConditionOperator = ConditionOperator.equals,
) -> ExtractedRoutingCondition:
    if operator is ConditionOperator.opaque:
        return ExtractedRoutingCondition(
            operator=operator,
            item_reference=None,
            value=None,
            values=None,
            children=None,
            raw_text="unsupported expression",
        )
    return ExtractedRoutingCondition(
        operator=operator,
        item_reference=_reference(item_id),
        value=value,
        values=None,
        children=None,
        raw_text=f"{item_id} = {value}",
    )


def _canonical_condition(
    node_id: str = "question:main:q1",
    *,
    value: int = 1,
) -> CanonicalRoutingCondition:
    return CanonicalRoutingCondition(
        operator=ConditionOperator.equals,
        question_node_id=node_id,
        value=value,
        values=None,
        children=None,
        raw_text=f"Q1 = {value}",
    )


def _span(evidence_id: str) -> SourceSpan:
    return SourceSpan(
        span_id=f"span:{evidence_id}",
        block_id=f"block:{evidence_id}",
        source_name="questionnaire.txt",
        pages=(1,),
        sheet=None,
        row_start=None,
        row_end=None,
        source_quote=f"Verified routing instruction {evidence_id}.",
    )


def _transition(
    evidence_id: str,
    source: str,
    target: str,
    *,
    kind: TransitionKind = TransitionKind.unconditional,
    condition: ExtractedRoutingCondition | None = None,
    origin: EvidenceOrigin = EvidenceOrigin.forward_extraction,
    explicitly_stated: bool = True,
    ambiguity_note: str | None = None,
    target_kind: NodeKind = NodeKind.question,
    native_condition: CanonicalRoutingCondition | None = None,
) -> EvidenceRecord:
    native = None
    if origin is EvidenceOrigin.native_parser:
        native = NativeExpression(
            language="xpath",
            version="1.0",
            exact_expression="${q1} = 1",
            parsed_references=(_reference("Q1"),),
            canonical_projection=native_condition or _canonical_condition(),
        )
    observation = TransitionEvidence(
        evidence_type="transition",
        local_id=f"local:{evidence_id}",
        perspective=(
            EvidencePerspective.incoming
            if origin is EvidenceOrigin.incoming_extraction
            else EvidencePerspective.outgoing
        ),
        origin=origin,
        source=_reference(source),
        target=_reference(target, kind=target_kind),
        transition_kind=kind,
        condition=condition,
        source_span=_span(evidence_id),
        native_expression=native,
        explicitly_stated=explicitly_stated,
        confidence=0.9,
        ambiguity_note=ambiguity_note,
    )
    return EvidenceRecord(evidence_id=evidence_id, observation=observation)


def _activation(
    evidence_id: str,
    item_id: str,
    condition: ExtractedRoutingCondition,
) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id,
        observation=ActivationEvidence(
            evidence_type="activation",
            local_id=f"local:{evidence_id}",
            origin=EvidenceOrigin.incoming_extraction,
            item=_reference(item_id),
            condition=condition,
            source_span=_span(evidence_id),
            native_expression=None,
            explicitly_stated=True,
            confidence=0.8,
            ambiguity_note=None,
        ),
    )


def _inventory_item(
    node_id: str,
    source_item_id: str,
    order: int,
    *,
    kind: NodeKind = NodeKind.question,
) -> InventoryItem:
    return InventoryItem(
        node_id=node_id,
        source_item_id=source_item_id,
        raw_reference=source_item_id,
        section_path=("Main",),
        source_order=order,
        block_ids=(f"inventory-block:{order}",),
        kind=kind,
        repeat_group_node_id=None,
        parent_node_id=None,
        linked_variable_indices=(),
    )


def _node(item: InventoryItem) -> RoutingNode:
    return RoutingNode(
        node_id=item.node_id,
        kind=item.kind,
        source_item_id=item.source_item_id,
        raw_name=(
            item.source_item_id.casefold()
            if item.kind is NodeKind.question and item.source_item_id is not None
            else None
        ),
        label=item.raw_reference,
        terminal_kind=(TerminalKind.survey_complete if item.kind is NodeKind.terminal else None),
        activation_condition=None,
        repeat_spec=None,
        containment=Containment(
            parent_node_id=None,
            child_node_ids=(),
            entry_child_node_id=None,
        ),
        next_node_ids=(),
        previous_node_ids=(),
        outgoing_edge_ids=(),
        incoming_edge_ids=(),
    )


def _inventory() -> tuple[InventoryItem, ...]:
    return (
        _inventory_item("entry:start", "START", 0, kind=NodeKind.entry),
        _inventory_item("question:main:q1", "Q1", 1),
        _inventory_item("question:main:q2", "Q2", 2),
        _inventory_item("question:main:q3", "Q3", 3),
        _inventory_item("question:main:q4", "Q4", 4),
        _inventory_item("terminal:complete", "END", 5, kind=NodeKind.terminal),
    )


def _binding() -> RoutingSourceBinding:
    return RoutingSourceBinding(
        survey_id="TST_2024_SYNTH",
        source_name="questionnaire.txt",
        media_type="text/plain",
        snapshot_sha256="a" * 64,
        source_conversion_schema_version="1.0",
    )


def _verified(records: Iterable[EvidenceRecord]) -> VerifiedEvidence:
    materialized = tuple(records)
    return VerifiedEvidence(
        source_spans=tuple(record.observation.source_span for record in materialized),
        records=materialized,
    )


def _reconcile(
    records: Iterable[EvidenceRecord],
    *,
    inventory: tuple[InventoryItem, ...] | None = None,
    priorities: Mapping[str, int] | None = None,
    known_category_codes: Mapping[str, tuple[RoutingScalar, ...]] | None = None,
):
    items = inventory or _inventory()
    return reconcile_routing_graph(
        nodes=tuple(_node(item) for item in items),
        entry_node_ids=("entry:start",),
        inventory=items,
        source_binding=_binding(),
        verified_evidence=_verified(records),
        source_priorities=priorities,
        known_category_codes=known_category_codes,
    )


def _decision(
    graph,
    action: ReviewAction,
    *,
    decision_id: str,
    supersedes: str | None = None,
    replacement: ReplacementEdge | None = None,
    needs_human_review: bool = False,
) -> ReviewDecision:
    candidate = graph.routing_audit.candidate_edges[0]
    discrepancy = graph.routing_audit.discrepancies[0]
    return ReviewDecision(
        decision_id=decision_id,
        discrepancy_ids=(discrepancy.discrepancy_id,),
        candidate_ids=(candidate.candidate_id,),
        evidence_ids=candidate.evidence_ids,
        cited_span_ids=discrepancy.source_span_ids,
        action=action,
        replacement=replacement,
        rationale="The bounded cited evidence supports this decision.",
        confidence=0.95,
        needs_human_review=needs_human_review,
        prompt_version="1.0.0",
        prompt_sha256="b" * 64,
        provider_response_sha256="c" * 64,
        supersedes_decision_id=supersedes,
    )


def test_matching_forward_incoming_and_native_evidence_merge_without_a_loop_kind() -> None:
    records = (
        _transition(
            "evidence:forward",
            "Q1",
            "Q2",
            kind=TransitionKind.conditional,
            condition=_condition("Q1"),
        ),
        _transition(
            "evidence:incoming",
            "Question 1",
            "2",
            kind=TransitionKind.conditional,
            condition=_condition("Question 1"),
            origin=EvidenceOrigin.incoming_extraction,
        ),
        _transition(
            "evidence:native",
            "1",
            "Question 2",
            kind=TransitionKind.conditional,
            condition=_condition("1"),
            origin=EvidenceOrigin.native_parser,
        ),
    )

    graph = _reconcile(records, priorities={record.evidence_id: 1 for record in records})

    assert len(graph.edges) == 1
    edge = graph.edges[0]
    assert edge.edge_id.startswith("edge:")
    assert edge.source_node_id == "question:main:q1"
    assert edge.target_node_id == "question:main:q2"
    assert edge.kind is EdgeKind.conditional
    assert edge.priority == 1
    assert edge.evidence_ids == tuple(record.evidence_id for record in records)
    assert graph.routing_audit.evidence == records
    assert graph.routing_audit.candidate_edges == ()
    assert graph.loops == ()
    assert all(edge.kind.value != "loop" for edge in graph.edges)


def test_forward_evidence_accepts_parallel_edges_and_derives_accepted_only_adjacency() -> None:
    records = (
        _transition(
            "evidence:one",
            "Q1",
            "Q2",
            kind=TransitionKind.conditional,
            condition=_condition(value=1),
        ),
        _transition(
            "evidence:two",
            "Q1",
            "Q2",
            kind=TransitionKind.conditional,
            condition=_condition(value=2),
        ),
        _transition("evidence:end", "Q2", "END", target_kind=NodeKind.terminal),
    )

    graph = _reconcile(
        records,
        priorities={"evidence:one": 1, "evidence:two": 2},
    )
    rerun = _reconcile(
        records,
        priorities={"evidence:one": 1, "evidence:two": 2},
    )

    assert graph.edges == rerun.edges
    assert len(graph.edges) == 3
    q1 = next(node for node in graph.nodes if node.node_id == "question:main:q1")
    q2 = next(node for node in graph.nodes if node.node_id == "question:main:q2")
    assert q1.next_node_ids == ("question:main:q2",)
    assert q1.outgoing_edge_ids == tuple(edge.edge_id for edge in graph.edges[:2])
    assert q2.incoming_edge_ids == q1.outgoing_edge_ids
    assert q2.next_node_ids == ("terminal:complete",)


def test_reconciliation_uses_linked_category_codes_for_end_to_end_branch_coverage() -> None:
    first_branch = _transition(
        "evidence:category-one",
        "Q1",
        "Q2",
        kind=TransitionKind.conditional,
        condition=_condition(value=1),
    )
    second_branch = _transition(
        "evidence:category-two",
        "Q1",
        "Q3",
        kind=TransitionKind.conditional,
        condition=_condition(value=2),
    )
    known = {"question:main:q1": (1, 2)}

    missing = _reconcile((first_branch,), known_category_codes=known)
    complete = _reconcile(
        (first_branch, second_branch),
        known_category_codes=known,
    )

    assert "UNCOVERED_BRANCH" in {item.code for item in missing.diagnostics}
    assert "UNCOVERED_BRANCH" not in {item.code for item in complete.diagnostics}


def test_independently_verified_sibling_branches_are_not_cross_compared() -> None:
    records = (
        _transition(
            "evidence:forward-one",
            "Q1",
            "Q2",
            kind=TransitionKind.conditional,
            condition=_condition(value=1),
        ),
        _transition(
            "evidence:forward-two",
            "Q1",
            "Q3",
            kind=TransitionKind.conditional,
            condition=_condition(value=2),
        ),
        _transition(
            "evidence:incoming-one",
            "Q1",
            "Q2",
            kind=TransitionKind.conditional,
            condition=_condition(value=1),
            origin=EvidenceOrigin.incoming_extraction,
        ),
        _transition(
            "evidence:incoming-two",
            "Q1",
            "Q3",
            kind=TransitionKind.conditional,
            condition=_condition(value=2),
            origin=EvidenceOrigin.incoming_extraction,
        ),
    )
    priorities = {
        "evidence:forward-one": 1,
        "evidence:incoming-one": 1,
        "evidence:forward-two": 2,
        "evidence:incoming-two": 2,
    }

    graph = _reconcile(records, priorities=priorities)

    assert [edge.target_node_id for edge in graph.edges] == [
        "question:main:q2",
        "question:main:q3",
    ]
    assert [edge.evidence_ids for edge in graph.edges] == [
        ("evidence:forward-one", "evidence:incoming-one"),
        ("evidence:forward-two", "evidence:incoming-two"),
    ]
    assert graph.routing_audit.candidate_edges == ()
    assert "CONFLICTING_TARGET" not in {item.code for item in graph.diagnostics}


@pytest.mark.parametrize(
    ("incoming", "expected_code", "forward_is_accepted"),
    [
        (
            _transition(
                "evidence:incoming-target",
                "Q1",
                "Q3",
                origin=EvidenceOrigin.incoming_extraction,
            ),
            "CONFLICTING_TARGET",
            False,
        ),
        (
            _transition(
                "evidence:incoming-condition",
                "Q1",
                "Q2",
                kind=TransitionKind.conditional,
                condition=_condition(value=2),
                origin=EvidenceOrigin.incoming_extraction,
            ),
            "INCOMING_ONLY",
            True,
        ),
    ],
)
def test_incoming_disagreement_moves_forward_and_incoming_claims_to_audit(
    incoming: EvidenceRecord,
    expected_code: str,
    forward_is_accepted: bool,
) -> None:
    assert isinstance(incoming.observation, TransitionEvidence)
    forward = _transition(
        "evidence:forward",
        "Q1",
        "Q2",
        kind=(
            TransitionKind.conditional
            if incoming.observation.transition_kind is TransitionKind.conditional
            else TransitionKind.unconditional
        ),
        condition=(
            _condition(value=1)
            if incoming.observation.transition_kind is TransitionKind.conditional
            else None
        ),
    )

    graph = _reconcile((forward, incoming))

    assert bool(graph.edges) is forward_is_accepted
    expected_candidates = (
        {(incoming.evidence_id,)}
        if forward_is_accepted
        else {(forward.evidence_id,), (incoming.evidence_id,)}
    )
    assert {
        item.evidence_ids for item in graph.routing_audit.candidate_edges
    } == expected_candidates
    assert expected_code in {diagnostic.code for diagnostic in graph.diagnostics}
    assert graph.routing_audit.discrepancies[0].candidate_ids


def test_incoming_only_evidence_requires_review_but_is_not_lost() -> None:
    incoming = _transition(
        "evidence:incoming",
        "Q2",
        "Q3",
        origin=EvidenceOrigin.incoming_extraction,
    )

    graph = _reconcile((incoming,))

    assert graph.edges == ()
    assert graph.routing_audit.evidence == (incoming,)
    assert graph.routing_audit.candidate_edges[0].target_node_id == "question:main:q3"
    assert graph.routing_audit.discrepancies[0].kind.value == "incoming_mismatch"
    assert graph.diagnostics[0].code == "INCOMING_ONLY"


def test_inferred_sequential_edges_require_immediate_successor_and_no_explicit_bypass() -> None:
    records = (
        _transition(
            "evidence:skip",
            "Q1",
            "Q4",
            kind=TransitionKind.conditional,
            condition=_condition(),
        ),
        _transition(
            "evidence:fallthrough",
            "Q1",
            "Q2",
            kind=TransitionKind.sequential,
            explicitly_stated=False,
        ),
        _transition("evidence:bypass", "Q2", "Q4"),
        _transition(
            "evidence:bypassed-sequential",
            "Q2",
            "Q3",
            kind=TransitionKind.sequential,
            explicitly_stated=False,
        ),
        _transition(
            "evidence:inferred-cycle",
            "Q3",
            "Q2",
            kind=TransitionKind.sequential,
            explicitly_stated=False,
        ),
        _transition("evidence:return", "Q4", "Q2"),
    )

    graph = _reconcile(records)

    accepted_evidence = {evidence_id for edge in graph.edges for evidence_id in edge.evidence_ids}
    assert "evidence:skip" in accepted_evidence
    assert "evidence:fallthrough" in accepted_evidence
    assert "evidence:bypass" in accepted_evidence
    assert "evidence:return" in accepted_evidence
    assert "evidence:bypassed-sequential" not in accepted_evidence
    assert "evidence:inferred-cycle" not in accepted_evidence
    assert len(graph.loops) == 1
    assert graph.loops[0].kind.value == "correction_return"
    assert {diagnostic.code for diagnostic in graph.diagnostics} >= {
        "SEQUENTIAL_BYPASSED",
        "INFERRED_CYCLE",
    }


def test_one_default_is_accepted_and_conflicting_defaults_remain_candidates() -> None:
    records = (
        _transition(
            "evidence:branch",
            "Q1",
            "Q2",
            kind=TransitionKind.conditional,
            condition=_condition(),
        ),
        _transition("evidence:default", "Q1", "Q3", kind=TransitionKind.default),
        _transition("evidence:default-a", "Q2", "Q3", kind=TransitionKind.default),
        _transition(
            "evidence:default-b",
            "Q2",
            "END",
            kind=TransitionKind.default,
            target_kind=NodeKind.terminal,
        ),
    )

    graph = _reconcile(
        records,
        priorities={
            "evidence:branch": 1,
            "evidence:default": 2,
            "evidence:default-a": 1,
            "evidence:default-b": 2,
        },
    )

    defaults = [edge for edge in graph.edges if edge.kind is EdgeKind.default]
    assert [(edge.source_node_id, edge.target_node_id) for edge in defaults] == [
        ("question:main:q1", "question:main:q3")
    ]
    assert {
        evidence_id
        for candidate in graph.routing_audit.candidate_edges
        for evidence_id in candidate.evidence_ids
    } == {"evidence:default-a", "evidence:default-b"}
    assert graph.routing_audit.discrepancies[0].kind.value == "multiple_defaults"
    assert "MULTIPLE_DEFAULTS" in {item.code for item in graph.diagnostics}


def test_reviewer_packet_includes_complete_identity_collision_closure() -> None:
    inventory = (
        _inventory_item("entry:start", "START", 0, kind=NodeKind.entry),
        _inventory_item("question:main:q0", "Q0", 1),
        _inventory_item("question:main:q1-a", "Q1", 2),
        _inventory_item("question:main:q1-b", "Q1", 3),
        _inventory_item("terminal:complete", "END", 4, kind=NodeKind.terminal),
    )
    graph = _reconcile(
        (_transition("evidence:ambiguous", "Q0", "Q1"),),
        inventory=inventory,
    )

    packets = build_reviewer_packets(graph, RoutingConfig())

    assert len(packets) == 1
    assert {item.node_id for item in packets[0].item_inventory if item.source_item_id == "Q1"} == {
        "question:main:q1-a",
        "question:main:q1-b",
    }


def test_ambiguous_fuzzy_unresolved_opaque_and_condition_references_stay_in_audit() -> None:
    base = _inventory()
    duplicate = _inventory_item("question:main:q2:duplicate", "Question 2", 6)
    inventory = base + (duplicate,)
    records = (
        _transition("evidence:ambiguous", "Q1", "2"),
        _transition("evidence:unresolved", "Q1", "missing"),
        _transition(
            "evidence:fuzzy",
            "Q1",
            "Q3",
            ambiguity_note="This target was selected by semantic similarity.",
        ),
        _transition(
            "evidence:condition",
            "Q1",
            "Q3",
            kind=TransitionKind.conditional,
            condition=_condition("missing"),
        ),
        _transition(
            "evidence:opaque",
            "Q1",
            "Q4",
            kind=TransitionKind.conditional,
            condition=_condition(operator=ConditionOperator.opaque),
        ),
    )

    graph = _reconcile(records, inventory=inventory)

    assert graph.edges == ()
    assert len(graph.routing_audit.candidate_edges) == len(records)
    assert {
        evidence_id
        for candidate in graph.routing_audit.candidate_edges
        for evidence_id in candidate.evidence_ids
    } == {record.evidence_id for record in records}
    assert {diagnostic.code for diagnostic in graph.diagnostics} >= {
        "AMBIGUOUS_TARGET",
        "UNRESOLVED_TARGET",
        "FUZZY_TARGET",
        "AMBIGUOUS_CONDITION_REFERENCE",
        "OPAQUE_CONDITION",
    }
    ambiguous = next(
        candidate
        for candidate in graph.routing_audit.candidate_edges
        if candidate.evidence_ids == ("evidence:ambiguous",)
    )
    unresolved = next(
        candidate
        for candidate in graph.routing_audit.candidate_edges
        if candidate.evidence_ids == ("evidence:unresolved",)
    )
    assert ambiguous.target_node_id is None
    assert unresolved.target_node_id is None


def test_activation_conditions_are_canonical_and_opaque_coverage_is_diagnostic_only() -> None:
    records = (
        _activation("evidence:activation", "Q2", _condition("Q1")),
        _activation(
            "evidence:opaque-activation",
            "Q3",
            _condition(operator=ConditionOperator.opaque),
        ),
    )

    graph = _reconcile(records)

    q2 = next(node for node in graph.nodes if node.node_id == "question:main:q2")
    assert q2.activation_condition is not None
    assert q2.activation_condition.question_node_id == "question:main:q1"
    assert graph.routing_audit.evidence == records
    assert graph.edges == ()
    assert "OPAQUE_ACTIVATION_CONDITION" in {item.code for item in graph.diagnostics}


def test_confirm_then_reject_is_append_only_and_updates_only_review_accepted_edges() -> None:
    incoming = _transition(
        "evidence:incoming",
        "Q1",
        "Q2",
        origin=EvidenceOrigin.incoming_extraction,
    )
    initial = _reconcile((incoming,))
    candidate = initial.routing_audit.candidate_edges[0]
    confirm = _decision(
        initial,
        ReviewAction.confirm_candidate,
        decision_id="decision:confirm",
    )

    confirmed = append_review_decisions(initial, (confirm,))

    assert confirmed.routing_audit.candidate_edges[0].candidate_id == candidate.candidate_id
    assert confirmed.routing_audit.candidate_edges[0].evidence_ids == candidate.evidence_ids
    assert confirmed.routing_audit.candidate_edges[0].status is CandidateStatus.accepted
    assert confirmed.routing_audit.evidence == initial.routing_audit.evidence
    assert confirmed.edges[0].review_decision_id == "decision:confirm"
    assert confirmed.edges[0].evidence_ids == candidate.evidence_ids
    assert confirmed.routing_audit.discrepancies[0].resolved_by_decision_id == "decision:confirm"

    reject = _decision(
        initial,
        ReviewAction.reject_candidate,
        decision_id="decision:reject",
        supersedes="decision:confirm",
    )
    rejected = append_review_decisions(confirmed, (reject,))

    assert rejected.edges == ()
    assert rejected.routing_audit.candidate_edges[0].candidate_id == candidate.candidate_id
    assert rejected.routing_audit.candidate_edges[0].evidence_ids == candidate.evidence_ids
    assert rejected.routing_audit.candidate_edges[0].status is CandidateStatus.rejected
    assert rejected.routing_audit.evidence == initial.routing_audit.evidence
    assert [item.decision_id for item in rejected.routing_audit.review_decisions] == [
        "decision:confirm",
        "decision:reject",
    ]
    assert rejected.routing_audit.discrepancies[0].resolved_by_decision_id == "decision:reject"


def test_replace_and_unresolved_reviews_preserve_original_candidate_history() -> None:
    unresolved_evidence = _transition(
        "evidence:unresolved",
        "Q1",
        "Q3",
        ambiguity_note="The printed target requires review.",
    )
    initial = _reconcile((unresolved_evidence,))
    replacement = ReplacementEdge(
        source_node_id="question:main:q1",
        target_node_id="question:main:q3",
        target_reference=_reference("Q3"),
        kind=EdgeKind.unconditional,
        condition=None,
        priority=None,
        evidence_ids=("evidence:unresolved",),
    )
    replace = _decision(
        initial,
        ReviewAction.replace_candidate,
        decision_id="decision:replace",
        replacement=replacement,
    )

    replaced = append_review_decisions(initial, (replace,))

    assert replaced.edges[0].target_node_id == "question:main:q3"
    assert replaced.edges[0].review_decision_id == "decision:replace"
    assert replaced.routing_audit.candidate_edges[0].target_node_id == "question:main:q3"
    assert replaced.routing_audit.candidate_edges[0].status is CandidateStatus.rejected

    unresolved = _decision(
        initial,
        ReviewAction.unresolved,
        decision_id="decision:unresolved",
        needs_human_review=True,
    )
    needs_human = append_review_decisions(initial, (unresolved,))

    assert needs_human.edges == ()
    assert needs_human.routing_audit.discrepancies[0].resolved_by_decision_id is None
    assert needs_human.routing_audit.candidate_edges[0].status is CandidateStatus.needs_human_review
    assert "UNRESOLVED_REVIEW" in {item.code for item in needs_human.diagnostics}


def test_reconciliation_rejects_unverified_namespaces_and_invented_priorities() -> None:
    record = _transition("evidence:one", "Q1", "Q2")
    invalid_span = VerifiedEvidence(source_spans=(), records=(record,))
    items = _inventory()
    arguments = {
        "nodes": tuple(_node(item) for item in items),
        "entry_node_ids": ("entry:start",),
        "inventory": items,
        "source_binding": _binding(),
    }

    with pytest.raises(ReconciliationError, match="source span"):
        reconcile_routing_graph(**arguments, verified_evidence=invalid_span)
    with pytest.raises(ReconciliationError, match="unknown evidence"):
        reconcile_routing_graph(
            **arguments,
            verified_evidence=_verified((record,)),
            source_priorities={"missing": 1},
        )
    with pytest.raises(ReconciliationError, match="nonnegative integer"):
        reconcile_routing_graph(
            **arguments,
            verified_evidence=_verified((record,)),
            source_priorities={"evidence:one": True},
        )
    with pytest.raises(ReconciliationError, match="conditional or default"):
        reconcile_routing_graph(
            **arguments,
            verified_evidence=_verified((record,)),
            source_priorities={"evidence:one": 1},
        )


def test_review_decisions_require_candidate_bounded_evidence_and_citations() -> None:
    initial = _reconcile(
        (
            _transition(
                "evidence:incoming",
                "Q1",
                "Q2",
                origin=EvidenceOrigin.incoming_extraction,
            ),
        )
    )
    decision = _decision(
        initial,
        ReviewAction.confirm_candidate,
        decision_id="decision:invalid",
    )

    with pytest.raises(ReconciliationError, match="cited spans"):
        append_review_decisions(
            initial,
            (decision.model_copy(update={"cited_span_ids": ("span:missing",)}),),
        )
    with pytest.raises(ReconciliationError, match="candidate evidence"):
        append_review_decisions(
            initial,
            (decision.model_copy(update={"evidence_ids": ("evidence:missing",)}),),
        )


def test_reconciliation_input_guards_fail_before_graph_facts_are_created() -> None:
    record = _transition("evidence:one", "Q1", "Q2")
    items = _inventory()
    valid_nodes = tuple(_node(item) for item in items)
    valid_evidence = _verified((record,))
    common = {
        "entry_node_ids": ("entry:start",),
        "source_binding": _binding(),
        "source_priorities": None,
    }

    with pytest.raises(ReconciliationError, match="inventory item"):
        reconcile_routing_graph(
            **common,
            nodes=valid_nodes[:-1],
            inventory=items,
            verified_evidence=valid_evidence,
        )
    with pytest.raises(ReconciliationError, match="inventory node identifiers"):
        reconcile_routing_graph(
            **common,
            nodes=valid_nodes,
            inventory=items + (items[0],),
            verified_evidence=valid_evidence,
        )
    with pytest.raises(ReconciliationError, match="canonical node identifiers"):
        reconcile_routing_graph(
            **common,
            nodes=valid_nodes + (valid_nodes[0],),
            inventory=items,
            verified_evidence=valid_evidence,
        )
    with pytest.raises(ReconciliationError, match="source span identifiers"):
        reconcile_routing_graph(
            **common,
            nodes=valid_nodes,
            inventory=items,
            verified_evidence=VerifiedEvidence(
                source_spans=valid_evidence.source_spans * 2,
                records=valid_evidence.records,
            ),
        )
    with pytest.raises(ReconciliationError, match="evidence identifiers"):
        reconcile_routing_graph(
            **common,
            nodes=valid_nodes,
            inventory=items,
            verified_evidence=VerifiedEvidence(
                source_spans=valid_evidence.source_spans,
                records=valid_evidence.records * 2,
            ),
        )
    with pytest.raises(ReconciliationError, match="structural invariant"):
        reconcile_routing_graph(
            **{**common, "entry_node_ids": ("question:main:q1",)},
            nodes=valid_nodes,
            inventory=items,
            verified_evidence=valid_evidence,
        )


def test_unresolved_sources_and_non_source_defined_priorities_are_rejected() -> None:
    unresolved_source = _transition("evidence:source", "missing", "Q2")
    inferred_conditional = _transition(
        "evidence:inferred",
        "Q1",
        "Q2",
        kind=TransitionKind.conditional,
        condition=_condition(),
        explicitly_stated=False,
    )

    with pytest.raises(ReconciliationError, match="transition source"):
        _reconcile((unresolved_source,))
    with pytest.raises(ReconciliationError, match="explicitly ordered"):
        _reconcile((inferred_conditional,), priorities={"evidence:inferred": 1})


def test_native_projection_and_source_priority_conflicts_require_review() -> None:
    opaque_native = _transition(
        "evidence:native-opaque",
        "Q1",
        "Q2",
        kind=TransitionKind.conditional,
        condition=_condition(),
        origin=EvidenceOrigin.native_parser,
        native_condition=CanonicalRoutingCondition(
            operator=ConditionOperator.opaque,
            question_node_id=None,
            value=None,
            values=None,
            children=None,
            raw_text="unsupported native expression",
        ),
    )
    mismatched_native = _transition(
        "evidence:native-mismatch",
        "Q2",
        "Q3",
        kind=TransitionKind.conditional,
        condition=_condition("Q2", value=1),
        origin=EvidenceOrigin.native_parser,
        native_condition=_canonical_condition("question:main:q2", value=2),
    )
    duplicate_one = _transition(
        "evidence:priority-one",
        "Q3",
        "Q4",
        kind=TransitionKind.conditional,
        condition=_condition("Q3"),
    )
    duplicate_two = duplicate_one.model_copy(
        update={
            "evidence_id": "evidence:priority-two",
            "observation": duplicate_one.observation.model_copy(
                update={
                    "local_id": "local:evidence:priority-two",
                    "source_span": _span("evidence:priority-two"),
                }
            ),
        }
    )

    graph = _reconcile(
        (opaque_native, mismatched_native, duplicate_one, duplicate_two),
        priorities={"evidence:priority-one": 1, "evidence:priority-two": 2},
    )

    assert graph.edges == ()
    assert {item.code for item in graph.diagnostics} >= {
        "OPAQUE_CONDITION",
        "CONFLICTING_CONDITION",
        "CONFLICTING_PRIORITY",
    }
    priority_candidate = next(
        candidate
        for candidate in graph.routing_audit.candidate_edges
        if "evidence:priority-one" in candidate.evidence_ids
    )
    assert priority_candidate.priority is None
    assert priority_candidate.evidence_ids == (
        "evidence:priority-one",
        "evidence:priority-two",
    )


def test_equal_priorities_on_distinct_routes_and_nonsequential_inference_are_disputed() -> None:
    records = (
        _transition(
            "evidence:branch-one",
            "Q1",
            "Q2",
            kind=TransitionKind.conditional,
            condition=_condition(value=1),
        ),
        _transition(
            "evidence:branch-two",
            "Q1",
            "Q3",
            kind=TransitionKind.conditional,
            condition=_condition(value=2),
        ),
        _transition(
            "evidence:nonsequential",
            "Q2",
            "Q3",
            explicitly_stated=False,
        ),
    )

    graph = _reconcile(
        records,
        priorities={"evidence:branch-one": 1, "evidence:branch-two": 1},
    )

    assert graph.edges == ()
    assert {item.code for item in graph.diagnostics} >= {
        "CONFLICTING_PRIORITY",
        "SEQUENTIAL_UNCLEAR",
    }


def test_unresolved_and_nonadjacent_sequential_inferences_are_not_accepted() -> None:
    records = (
        _transition(
            "evidence:unknown-sequential",
            "Q1",
            "missing",
            kind=TransitionKind.sequential,
            explicitly_stated=False,
        ),
        _transition(
            "evidence:nonadjacent-sequential",
            "Q2",
            "Q4",
            kind=TransitionKind.sequential,
            explicitly_stated=False,
        ),
        _transition(
            "evidence:explicit-sequential",
            "Q3",
            "Q4",
            kind=TransitionKind.sequential,
        ),
    )

    graph = _reconcile(records)

    assert [edge.evidence_ids for edge in graph.edges] == [("evidence:explicit-sequential",)]
    assert {item.code for item in graph.diagnostics} >= {
        "UNRESOLVED_TARGET",
        "SEQUENTIAL_UNCLEAR",
    }


def test_activation_reference_conflict_and_existing_condition_paths_are_auditable() -> None:
    base = _inventory()
    duplicate = _inventory_item("question:main:q2:duplicate", "Question 2", 6)
    items = base + (duplicate,)
    ambiguous = _activation("evidence:ambiguous-activation", "2", _condition())
    unresolved = _activation("evidence:missing-activation", "missing", _condition())
    punctuation = _activation("evidence:punctuation-activation", "...", _condition())
    fuzzy = _activation("evidence:fuzzy-activation", "Q3", _condition()).model_copy(
        update={
            "observation": _activation(
                "evidence:fuzzy-activation",
                "Q3",
                _condition(),
            ).observation.model_copy(update={"ambiguity_note": "semantic match"})
        }
    )
    unresolved_condition = _activation(
        "evidence:condition-activation",
        "Q4",
        _condition("..."),
    )
    conflict_one = _activation("evidence:conflict-one", "Q3", _condition(value=1))
    conflict_two = _activation("evidence:conflict-two", "Q3", _condition(value=2))

    nodes = tuple(_node(item) for item in items)
    q3_index = next(index for index, node in enumerate(nodes) if node.node_id == "question:main:q3")
    nodes = (
        nodes[:q3_index]
        + (
            nodes[q3_index].model_copy(
                update={"activation_condition": _canonical_condition(value=3)}
            ),
        )
        + nodes[q3_index + 1 :]
    )
    graph = reconcile_routing_graph(
        nodes=nodes,
        entry_node_ids=("entry:start",),
        inventory=items,
        source_binding=_binding(),
        verified_evidence=_verified(
            (
                ambiguous,
                unresolved,
                punctuation,
                fuzzy,
                unresolved_condition,
                conflict_one,
                conflict_two,
            )
        ),
    )

    assert {item.code for item in graph.diagnostics} >= {
        "AMBIGUOUS_ACTIVATION_REFERENCE",
        "UNRESOLVED_ACTIVATION_REFERENCE",
        "FUZZY_ACTIVATION_REFERENCE",
        "ACTIVATION_CONFLICT",
    }


def test_direct_review_reconciliation_empty_append_and_duplicate_decisions() -> None:
    incoming = _transition(
        "evidence:incoming-direct",
        "Q1",
        "Q2",
        origin=EvidenceOrigin.incoming_extraction,
    )
    initial = _reconcile((incoming,))
    decision = _decision(
        initial,
        ReviewAction.confirm_candidate,
        decision_id="decision:direct",
    )
    items = _inventory()

    direct = reconcile_routing_graph(
        nodes=tuple(_node(item) for item in items),
        entry_node_ids=("entry:start",),
        inventory=items,
        source_binding=_binding(),
        verified_evidence=_verified((incoming,)),
        review_decisions=(decision,),
    )

    assert direct.edges[0].review_decision_id == "decision:direct"
    assert append_review_decisions(direct, ()) is direct
    with pytest.raises(ReconciliationError, match="append-only and unique"):
        append_review_decisions(direct, (decision,))


def test_review_rejects_unknown_namespaces_bad_supersession_and_unconfirmable_candidates() -> None:
    initial = _reconcile((_transition("evidence:unknown", "Q1", "missing"),))
    confirm = _decision(
        initial,
        ReviewAction.confirm_candidate,
        decision_id="decision:confirm-unknown",
    )

    with pytest.raises(ReconciliationError, match="existing candidates"):
        append_review_decisions(
            initial,
            (confirm.model_copy(update={"candidate_ids": ("candidate:missing",)}),),
        )
    with pytest.raises(ReconciliationError, match="existing discrepancies"):
        append_review_decisions(
            initial,
            (confirm.model_copy(update={"discrepancy_ids": ("discrepancy:missing",)}),),
        )
    with pytest.raises(ReconciliationError, match="require replacement"):
        append_review_decisions(initial, (confirm,))

    bad_supersession = confirm.model_copy(
        update={
            "action": ReviewAction.reject_candidate,
            "decision_id": "decision:bad-supersession",
            "supersedes_decision_id": "decision:missing",
        }
    )
    with pytest.raises(ReconciliationError, match="append-only audit"):
        append_review_decisions(initial, (bad_supersession,))


def test_review_rejects_opaque_confirmation_and_invalid_replacements() -> None:
    opaque = _reconcile(
        (
            _transition(
                "evidence:opaque-review",
                "Q1",
                "Q2",
                kind=TransitionKind.conditional,
                condition=_condition(operator=ConditionOperator.opaque),
            ),
        )
    )
    confirm_opaque = _decision(
        opaque,
        ReviewAction.confirm_candidate,
        decision_id="decision:confirm-opaque",
    )
    with pytest.raises(ReconciliationError, match="opaque condition"):
        append_review_decisions(opaque, (confirm_opaque,))

    unresolved = _reconcile((_transition("evidence:replace", "Q1", "missing"),))
    invalid_endpoint = ReplacementEdge(
        source_node_id="question:main:q1",
        target_node_id="question:missing",
        target_reference=_reference("missing"),
        kind=EdgeKind.unconditional,
        condition=None,
        priority=None,
        evidence_ids=("evidence:replace",),
    )
    replace_endpoint = _decision(
        unresolved,
        ReviewAction.replace_candidate,
        decision_id="decision:replace-endpoint",
        replacement=invalid_endpoint,
    )
    with pytest.raises(ReconciliationError, match="canonical graph nodes"):
        append_review_decisions(unresolved, (replace_endpoint,))

    invalid_condition = invalid_endpoint.model_copy(
        update={
            "target_node_id": "question:main:q2",
            "target_reference": _reference("Q2"),
            "kind": EdgeKind.conditional,
            "condition": _condition("missing"),
        }
    )
    replace_condition = _decision(
        unresolved,
        ReviewAction.replace_candidate,
        decision_id="decision:replace-condition",
        replacement=invalid_condition,
    )
    with pytest.raises(ReconciliationError, match="condition must resolve"):
        append_review_decisions(unresolved, (replace_condition,))


def test_review_cannot_accept_two_defaults_or_uncited_replacement_evidence() -> None:
    defaults = _reconcile(
        (
            _transition("evidence:default-one", "Q1", "Q2", kind=TransitionKind.default),
            _transition("evidence:default-two", "Q1", "Q3", kind=TransitionKind.default),
        )
    )
    candidates = defaults.routing_audit.candidate_edges
    discrepancy = defaults.routing_audit.discrepancies[0]
    accept_both = ReviewDecision(
        decision_id="decision:both-defaults",
        discrepancy_ids=(discrepancy.discrepancy_id,),
        candidate_ids=tuple(candidate.candidate_id for candidate in candidates),
        evidence_ids=tuple(
            evidence_id for candidate in candidates for evidence_id in candidate.evidence_ids
        ),
        cited_span_ids=discrepancy.source_span_ids,
        action=ReviewAction.confirm_candidate,
        replacement=None,
        rationale="The cited evidence was reviewed.",
        confidence=0.9,
        needs_human_review=False,
        prompt_version="1.0.0",
        prompt_sha256="b" * 64,
        provider_response_sha256="c" * 64,
        supersedes_decision_id=None,
    )
    with pytest.raises(ReconciliationError, match="conflicting default"):
        append_review_decisions(defaults, (accept_both,))

    replacement = ReplacementEdge(
        source_node_id="question:main:q1",
        target_node_id="question:main:q2",
        target_reference=_reference("Q2"),
        kind=EdgeKind.default,
        condition=None,
        priority=None,
        evidence_ids=("evidence:default-two",),
    )
    uncited = ReviewDecision(
        decision_id="decision:uncited-replacement",
        discrepancy_ids=(discrepancy.discrepancy_id,),
        candidate_ids=(candidates[0].candidate_id,),
        evidence_ids=candidates[0].evidence_ids,
        cited_span_ids=(
            next(
                record.observation.source_span.span_id
                for record in defaults.routing_audit.evidence
                if record.evidence_id == candidates[0].evidence_ids[0]
            ),
        ),
        action=ReviewAction.replace_candidate,
        replacement=replacement,
        rationale="The cited evidence was reviewed.",
        confidence=0.9,
        needs_human_review=False,
        prompt_version="1.0.0",
        prompt_sha256="b" * 64,
        provider_response_sha256="c" * 64,
        supersedes_decision_id=None,
    )
    with pytest.raises(ReconciliationError, match="replacement evidence"):
        append_review_decisions(defaults, (uncited,))
