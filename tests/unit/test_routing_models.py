"""Strict contracts for routed SVIS evidence, audit, and canonical graphs."""

from __future__ import annotations

import json
from datetime import date
from math import inf, nan
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from survey_scribe.errors import ArtifactWriteError
from survey_scribe.models.routing import (
    CandidateEdge,
    CandidateStatus,
    Containment,
    DiagnosticSeverity,
    DiscrepancyKind,
    EdgeKind,
    EvidenceRecord,
    InventoryItem,
    LoopDefinition,
    LoopKind,
    QuestionnaireRoutingGraph,
    RepeatKind,
    RepeatSpec,
    ReplacementEdge,
    ReviewAction,
    ReviewDecision,
    RoutedAnswerCategory,
    RoutedNumericRange,
    RoutedSurveySVIS,
    RoutedSurveyVariable,
    RoutingAudit,
    RoutingDiagnostic,
    RoutingDiscrepancy,
    RoutingEdge,
    RoutingNode,
    RoutingSourceBinding,
    TerminalKind,
    canonical_routing_schema_json,
)
from survey_scribe.models.svis import (
    AnswerCategory,
    DataType,
    NumericRange,
    StudyType,
    SurveySVIS,
    SurveyVariable,
    UnitLevel,
)
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
    RoutingEvidenceBatch,
    RoutingPassKind,
    SourceSpan,
    TransitionEvidence,
    TransitionKind,
    project_extracted_condition,
)
from survey_scribe.serialization.routing import RoutedSurveySVISArtifactSerializer


def _reference(item_id: str = "Q1", *, kind: NodeKind = NodeKind.question) -> ItemReference:
    return ItemReference(
        raw_reference=item_id,
        source_item_id=item_id,
        canonical_hint=None,
        section_path=("main",),
        node_kind=kind,
    )


def _span(span_id: str = "span:q1") -> SourceSpan:
    return SourceSpan(
        span_id=span_id,
        block_id="block:0",
        source_name="questionnaire.txt",
        pages=(1,),
        sheet=None,
        row_start=None,
        row_end=None,
        source_quote="Q1. Continue to END.",
    )


def _extracted_condition(
    operator: ConditionOperator = ConditionOperator.equals,
    *,
    value: str | int | float | bool = 1,
) -> ExtractedRoutingCondition:
    return ExtractedRoutingCondition(
        operator=operator,
        item_reference=_reference(),
        value=value,
        values=None,
        children=None,
        raw_text="Q1 = 1",
    )


def _canonical_condition(
    operator: ConditionOperator = ConditionOperator.equals,
    *,
    value: str | int | float | bool = 1,
) -> CanonicalRoutingCondition:
    return CanonicalRoutingCondition(
        operator=operator,
        question_node_id="question:q1",
        value=value,
        values=None,
        children=None,
        raw_text="Q1 = 1",
    )


def _transition(local_id: str = "local:1") -> TransitionEvidence:
    return TransitionEvidence(
        evidence_type="transition",
        local_id=local_id,
        perspective=EvidencePerspective.outgoing,
        origin=EvidenceOrigin.forward_extraction,
        source=_reference("Q1"),
        target=_reference("END", kind=NodeKind.terminal),
        transition_kind=TransitionKind.conditional,
        condition=_extracted_condition(),
        source_span=_span(),
        native_expression=None,
        explicitly_stated=True,
        confidence=1.0,
        ambiguity_note=None,
    )


def _evidence_record(evidence_id: str = "evidence:1") -> EvidenceRecord:
    return EvidenceRecord(evidence_id=evidence_id, observation=_transition())


def _route_evidence(
    evidence_id: str,
    *,
    source: str,
    source_kind: NodeKind,
    target: str,
    target_kind: NodeKind,
    kind: TransitionKind,
    condition: ExtractedRoutingCondition | None,
) -> EvidenceRecord:
    observation = _transition(f"local:{evidence_id}").model_copy(
        update={
            "source": _reference(source, kind=source_kind),
            "target": _reference(target, kind=target_kind),
            "transition_kind": kind,
            "condition": condition,
        }
    )
    return EvidenceRecord(evidence_id=evidence_id, observation=observation)


def _source_binding() -> RoutingSourceBinding:
    return RoutingSourceBinding(
        survey_id="TST_2024_SYNTH",
        source_name="questionnaire.txt",
        media_type="text/plain",
        snapshot_sha256="a" * 64,
        source_conversion_schema_version="1.0",
    )


def _inventory_item(
    node_id: str = "question:q1",
    *,
    linked_variable_indices: tuple[int, ...] = (0,),
) -> InventoryItem:
    return InventoryItem(
        node_id=node_id,
        source_item_id="Q1",
        raw_reference="Q1",
        section_path=("main",),
        source_order=0,
        block_ids=("block:0",),
        kind=NodeKind.question,
        repeat_group_node_id=None,
        parent_node_id=None,
        linked_variable_indices=linked_variable_indices,
    )


def _route_inventory_item(
    node_id: str,
    *,
    raw_reference: str,
    kind: NodeKind,
    source_order: int,
    parent_node_id: str | None = None,
    repeat_group_node_id: str | None = None,
    linked_variable_indices: tuple[int, ...] = (),
) -> InventoryItem:
    return InventoryItem(
        node_id=node_id,
        source_item_id=(raw_reference if kind is NodeKind.question else None),
        raw_reference=raw_reference,
        section_path=("main",),
        source_order=source_order,
        block_ids=("block:0",),
        kind=kind,
        repeat_group_node_id=repeat_group_node_id,
        parent_node_id=parent_node_id,
        linked_variable_indices=linked_variable_indices,
    )


def _audit(**changes: object) -> RoutingAudit:
    values: dict[str, object] = {
        "source_binding": _source_binding(),
        "inventory": (),
        "source_spans": (_span(),),
        "evidence": (_evidence_record(),),
        "candidate_edges": (),
        "discrepancies": (),
        "review_decisions": (),
    }
    values.update(changes)
    return RoutingAudit(**values)  # type: ignore[arg-type]


def _node(
    node_id: str,
    kind: NodeKind,
    *,
    next_node_ids: tuple[str, ...] = (),
    previous_node_ids: tuple[str, ...] = (),
    outgoing_edge_ids: tuple[str, ...] = (),
    incoming_edge_ids: tuple[str, ...] = (),
    parent_node_id: str | None = None,
    child_node_ids: tuple[str, ...] = (),
    entry_child_node_id: str | None = None,
    repeat_spec: RepeatSpec | None = None,
) -> RoutingNode:
    return RoutingNode(
        node_id=node_id,
        kind=kind,
        source_item_id="Q1" if kind is NodeKind.question else None,
        raw_name="q1" if kind is NodeKind.question else None,
        label=node_id,
        terminal_kind=(TerminalKind.survey_complete if kind is NodeKind.terminal else None),
        activation_condition=None,
        repeat_spec=repeat_spec,
        containment=Containment(
            parent_node_id=parent_node_id,
            child_node_ids=child_node_ids,
            entry_child_node_id=entry_child_node_id,
        ),
        next_node_ids=next_node_ids,
        previous_node_ids=previous_node_ids,
        outgoing_edge_ids=outgoing_edge_ids,
        incoming_edge_ids=incoming_edge_ids,
    )


def _valid_graph() -> QuestionnaireRoutingGraph:
    entry_edge = RoutingEdge(
        edge_id="edge:entry",
        source_node_id="entry:start",
        target_node_id="question:q1",
        kind=EdgeKind.unconditional,
        condition=None,
        priority=None,
        evidence_ids=("evidence:entry",),
        confidence=1.0,
        review_decision_id=None,
    )
    terminal_edge = RoutingEdge(
        edge_id="edge:end",
        source_node_id="question:q1",
        target_node_id="terminal:complete",
        kind=EdgeKind.conditional,
        condition=_canonical_condition(),
        priority=1,
        evidence_ids=("evidence:1",),
        confidence=1.0,
        review_decision_id=None,
    )
    return QuestionnaireRoutingGraph(
        schema_version="1.0",
        entry_node_ids=("entry:start",),
        nodes=(
            _node(
                "entry:start",
                NodeKind.entry,
                next_node_ids=("question:q1",),
                outgoing_edge_ids=("edge:entry",),
            ),
            _node(
                "question:q1",
                NodeKind.question,
                next_node_ids=("terminal:complete",),
                previous_node_ids=("entry:start",),
                outgoing_edge_ids=("edge:end",),
                incoming_edge_ids=("edge:entry",),
            ),
            _node(
                "terminal:complete",
                NodeKind.terminal,
                previous_node_ids=("question:q1",),
                incoming_edge_ids=("edge:end",),
            ),
        ),
        edges=(entry_edge, terminal_edge),
        loops=(),
        diagnostics=(),
        routing_audit=_audit(
            inventory=(
                _route_inventory_item(
                    "entry:start", raw_reference="START", kind=NodeKind.entry, source_order=0
                ),
                _route_inventory_item(
                    "question:q1",
                    raw_reference="Q1",
                    kind=NodeKind.question,
                    source_order=1,
                    linked_variable_indices=(0,),
                ),
                _route_inventory_item(
                    "terminal:complete",
                    raw_reference="END",
                    kind=NodeKind.terminal,
                    source_order=2,
                ),
            ),
            evidence=(
                _route_evidence(
                    "evidence:entry",
                    source="START",
                    source_kind=NodeKind.entry,
                    target="Q1",
                    target_kind=NodeKind.question,
                    kind=TransitionKind.unconditional,
                    condition=None,
                ),
                _evidence_record(),
            ),
        ),
    )


def _repeat_graph() -> QuestionnaireRoutingGraph:
    repeat_spec = RepeatSpec(
        repeat_kind=RepeatKind.household_member,
        iterator_label="household member",
        collection_source="roster",
        continuation_condition=_canonical_condition(),
        maximum_iterations=50,
    )
    edges = (
        RoutingEdge(
            edge_id="edge:entry",
            source_node_id="entry:start",
            target_node_id="repeat:roster",
            kind=EdgeKind.unconditional,
            condition=None,
            priority=None,
            evidence_ids=("evidence:repeat-entry",),
            confidence=1.0,
            review_decision_id=None,
        ),
        RoutingEdge(
            edge_id="edge:group-entry",
            source_node_id="repeat:roster",
            target_node_id="question:q1",
            kind=EdgeKind.unconditional,
            condition=None,
            priority=None,
            evidence_ids=("evidence:group-entry",),
            confidence=1.0,
            review_decision_id=None,
        ),
        RoutingEdge(
            edge_id="edge:return",
            source_node_id="question:q1",
            target_node_id="question:q1",
            kind=EdgeKind.conditional,
            condition=_canonical_condition(),
            priority=1,
            evidence_ids=("evidence:return",),
            confidence=1.0,
            review_decision_id=None,
        ),
        RoutingEdge(
            edge_id="edge:exit",
            source_node_id="question:q1",
            target_node_id="terminal:complete",
            kind=EdgeKind.default,
            condition=None,
            priority=2,
            evidence_ids=("evidence:exit",),
            confidence=1.0,
            review_decision_id=None,
        ),
    )
    loop = LoopDefinition(
        loop_id="loop:roster",
        kind=LoopKind.repeat_group,
        repeat_group_node_id="repeat:roster",
        member_node_ids=("repeat:roster", "question:q1"),
        entry_edge_ids=("edge:entry",),
        member_edge_ids=("edge:group-entry",),
        return_edge_ids=("edge:return",),
        exit_edge_ids=("edge:exit",),
        source_supported=True,
        evidence_ids=("evidence:return",),
    )
    return QuestionnaireRoutingGraph(
        schema_version="1.0",
        entry_node_ids=("entry:start",),
        nodes=(
            _node(
                "entry:start",
                NodeKind.entry,
                next_node_ids=("repeat:roster",),
                outgoing_edge_ids=("edge:entry",),
            ),
            RoutingNode(
                node_id="repeat:roster",
                kind=NodeKind.repeat_group,
                source_item_id=None,
                raw_name=None,
                label="Roster",
                terminal_kind=None,
                activation_condition=_canonical_condition(),
                repeat_spec=repeat_spec,
                containment=Containment(
                    parent_node_id=None,
                    child_node_ids=("question:q1",),
                    entry_child_node_id="question:q1",
                ),
                next_node_ids=("question:q1",),
                previous_node_ids=("entry:start",),
                outgoing_edge_ids=("edge:group-entry",),
                incoming_edge_ids=("edge:entry",),
            ),
            _node(
                "question:q1",
                NodeKind.question,
                next_node_ids=("question:q1", "terminal:complete"),
                previous_node_ids=("repeat:roster", "question:q1"),
                outgoing_edge_ids=("edge:return", "edge:exit"),
                incoming_edge_ids=("edge:group-entry", "edge:return"),
                parent_node_id="repeat:roster",
            ),
            _node(
                "terminal:complete",
                NodeKind.terminal,
                previous_node_ids=("question:q1",),
                incoming_edge_ids=("edge:exit",),
            ),
        ),
        edges=edges,
        loops=(loop,),
        diagnostics=(
            RoutingDiagnostic(
                diagnostic_id="diagnostic:loop",
                code="LOOP_RECORDED",
                severity=DiagnosticSeverity.info,
                message="A declared repeat loop is recorded.",
                node_ids=("repeat:roster",),
                edge_ids=("edge:return",),
                evidence_ids=("evidence:return",),
                candidate_ids=(),
            ),
        ),
        routing_audit=_audit(
            inventory=(
                _route_inventory_item(
                    "entry:start", raw_reference="START", kind=NodeKind.entry, source_order=0
                ),
                _route_inventory_item(
                    "repeat:roster",
                    raw_reference="ROSTER",
                    kind=NodeKind.repeat_group,
                    source_order=1,
                ),
                _route_inventory_item(
                    "question:q1",
                    raw_reference="Q1",
                    kind=NodeKind.question,
                    source_order=2,
                    parent_node_id="repeat:roster",
                    repeat_group_node_id="repeat:roster",
                    linked_variable_indices=(0,),
                ),
                _route_inventory_item(
                    "terminal:complete",
                    raw_reference="END",
                    kind=NodeKind.terminal,
                    source_order=3,
                ),
            ),
            evidence=(
                _route_evidence(
                    "evidence:repeat-entry",
                    source="START",
                    source_kind=NodeKind.entry,
                    target="ROSTER",
                    target_kind=NodeKind.repeat_group,
                    kind=TransitionKind.unconditional,
                    condition=None,
                ),
                _route_evidence(
                    "evidence:group-entry",
                    source="ROSTER",
                    source_kind=NodeKind.repeat_group,
                    target="Q1",
                    target_kind=NodeKind.question,
                    kind=TransitionKind.unconditional,
                    condition=None,
                ),
                _route_evidence(
                    "evidence:return",
                    source="Q1",
                    source_kind=NodeKind.question,
                    target="Q1",
                    target_kind=NodeKind.question,
                    kind=TransitionKind.conditional,
                    condition=_extracted_condition(),
                ),
                _route_evidence(
                    "evidence:exit",
                    source="Q1",
                    source_kind=NodeKind.question,
                    target="END",
                    target_kind=NodeKind.terminal,
                    kind=TransitionKind.default,
                    condition=None,
                ),
            ),
        ),
    )


def _graph_data() -> dict[str, Any]:
    return _valid_graph().model_dump(mode="json")


def _condition_values(
    operator: ConditionOperator,
    *,
    canonical: bool = False,
) -> dict[str, object]:
    question_field = "question_node_id" if canonical else "item_reference"
    question: object = "question:q1" if canonical else _reference()
    values: dict[str, object] = {
        "operator": operator,
        question_field: None,
        "value": None,
        "values": None,
        "children": None,
        "raw_text": operator.value,
    }
    scalar = {
        ConditionOperator.equals,
        ConditionOperator.not_equals,
        ConditionOperator.greater_than,
        ConditionOperator.greater_than_or_equal,
        ConditionOperator.less_than,
        ConditionOperator.less_than_or_equal,
        ConditionOperator.selected,
        ConditionOperator.not_selected,
    }
    if operator in scalar:
        values[question_field] = question
        values["value"] = 1
    elif operator in {ConditionOperator.in_set, ConditionOperator.not_in_set}:
        values[question_field] = question
        values["values"] = (1, 2)
    elif operator is ConditionOperator.between:
        values[question_field] = question
        values["values"] = (1, 10)
    elif operator in {ConditionOperator.answered, ConditionOperator.not_answered}:
        values[question_field] = question
    elif operator in {ConditionOperator.all, ConditionOperator.any}:
        child = _canonical_condition() if canonical else _extracted_condition()
        values["children"] = (child, child)
    elif operator is ConditionOperator.not_:
        values["children"] = (_canonical_condition() if canonical else _extracted_condition(),)
    elif operator is ConditionOperator.opaque:
        values["raw_text"] = "unsupported native expression"
    return values


@pytest.mark.parametrize("operator", list(ConditionOperator))
@pytest.mark.parametrize("canonical", [False, True])
def test_every_condition_operator_accepts_only_its_valid_shape(
    operator: ConditionOperator,
    canonical: bool,
) -> None:
    model = CanonicalRoutingCondition if canonical else ExtractedRoutingCondition

    condition = model.model_validate(_condition_values(operator, canonical=canonical))

    assert condition.operator is operator


@pytest.mark.parametrize(
    "changes",
    [
        {"item_reference": None},
        {"values": (1,)},
        {"children": (_extracted_condition(),)},
        {"value": None},
        {"raw_text": "", "operator": ConditionOperator.opaque},
    ],
)
def test_condition_rejects_missing_extra_and_wrong_shape_fields(changes: dict[str, object]) -> None:
    values = _condition_values(ConditionOperator.equals)
    values.update(changes)

    with pytest.raises(ValidationError):
        ExtractedRoutingCondition.model_validate(values)


def test_condition_rejects_unknown_fields() -> None:
    values = _condition_values(ConditionOperator.always)
    values["question_id"] = "Q1"

    with pytest.raises(ValidationError) as error:
        ExtractedRoutingCondition.model_validate(values)

    assert error.value.errors()[0]["type"] == "extra_forbidden"


def test_scalar_union_preserves_boolean_integer_float_and_string_types() -> None:
    conditions = tuple(_extracted_condition(value=value) for value in (True, 1, 1.5, "1"))

    assert [type(condition.value) for condition in conditions] == [bool, int, float, str]


@pytest.mark.parametrize("value", [nan, inf, -inf])
def test_conditions_and_confidence_reject_nonfinite_floats(value: float) -> None:
    with pytest.raises(ValidationError):
        _extracted_condition(value=value)

    evidence = _transition().model_dump(mode="python")
    evidence["confidence"] = value
    with pytest.raises(ValidationError):
        TransitionEvidence.model_validate(evidence)


def test_condition_ast_enforces_depth_six() -> None:
    condition = _extracted_condition()
    for _ in range(5):
        condition = ExtractedRoutingCondition(
            operator=ConditionOperator.not_,
            item_reference=None,
            value=None,
            values=None,
            children=(condition,),
            raw_text="not",
        )
    assert condition.ast_depth == 6

    with pytest.raises(ValidationError, match="depth"):
        ExtractedRoutingCondition(
            operator=ConditionOperator.not_,
            item_reference=None,
            value=None,
            values=None,
            children=(condition,),
            raw_text="not",
        )


def test_condition_ast_enforces_one_hundred_nodes() -> None:
    leaves = tuple(
        ExtractedRoutingCondition(
            operator=ConditionOperator.always,
            item_reference=None,
            value=None,
            values=None,
            children=None,
            raw_text="always",
        )
        for _ in range(100)
    )
    condition = ExtractedRoutingCondition(
        operator=ConditionOperator.all,
        item_reference=None,
        value=None,
        values=None,
        children=leaves[:99],
        raw_text="all",
    )
    assert condition.ast_node_count == 100

    with pytest.raises(ValidationError, match="nodes"):
        ExtractedRoutingCondition(
            operator=ConditionOperator.all,
            item_reference=None,
            value=None,
            values=None,
            children=leaves,
            raw_text="all",
        )


def test_extracted_condition_projects_through_explicit_typed_bindings() -> None:
    extracted = ExtractedRoutingCondition(
        operator=ConditionOperator.all,
        item_reference=None,
        value=None,
        values=None,
        children=(
            _extracted_condition(),
            ExtractedRoutingCondition(
                operator=ConditionOperator.answered,
                item_reference=_reference("Q2"),
                value=None,
                values=None,
                children=None,
                raw_text="Q2 answered",
            ),
        ),
        raw_text="Q1 = 1 and Q2 answered",
    )

    canonical = project_extracted_condition(
        extracted,
        {
            _reference("Q1").binding_key: "question:q1",
            _reference("Q2").binding_key: "question:q2",
        },
    )

    assert canonical.children is not None
    assert [child.question_node_id for child in canonical.children] == [
        "question:q1",
        "question:q2",
    ]
    with pytest.raises(ValueError, match="resolved reference"):
        project_extracted_condition(
            extracted,
            {_reference("Q1").binding_key: "question:q1"},
        )


def test_source_span_has_bounded_complete_physical_provenance() -> None:
    assert _span().pages == (1,)
    values = _span().model_dump(mode="json")
    values["source_quote"] = "x" * 2001
    with pytest.raises(ValidationError):
        SourceSpan.model_validate(values)
    with pytest.raises(ValidationError):
        SourceSpan(
            span_id="span",
            block_id="block",
            source_name="source",
            pages=(2, 1),
            sheet=None,
            row_start=3,
            row_end=None,
            source_quote="quote",
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"pages": (1, 1)},
        {"pages": (True,)},
        {"sheet": "Sheet1", "row_start": 5, "row_end": 4},
        {"sheet": None, "row_start": 1, "row_end": 1},
    ],
)
def test_source_span_rejects_invalid_strict_provenance(changes: dict[str, object]) -> None:
    values = _span().model_dump(mode="json")
    values.update(changes)
    with pytest.raises(ValidationError):
        SourceSpan.model_validate(values)


def test_source_binding_is_strict_frozen_and_hides_rejected_input() -> None:
    values = _source_binding().model_dump(mode="json")
    values["snapshot_sha256"] = "SECRET-NOT-A-DIGEST"
    with pytest.raises(ValidationError) as error:
        RoutingSourceBinding.model_validate(values)
    assert "SECRET-NOT-A-DIGEST" not in str(error.value)
    with pytest.raises(ValidationError):
        _source_binding().survey_id = "changed"


def test_unresolved_item_reference_uses_raw_identity_in_binding_key() -> None:
    reference = ItemReference(
        raw_reference="next section",
        source_item_id=None,
        canonical_hint=None,
        section_path=("main",),
        node_kind=NodeKind.section,
    )
    assert reference.binding_key == (("main",), "next section", NodeKind.section)


def test_evidence_union_is_discriminated_and_pass_specific() -> None:
    transition = _transition().model_dump(mode="json")
    transition.update(perspective="incoming", origin="incoming_extraction")
    activation = {
        "evidence_type": "activation",
        "local_id": "local:activation",
        "origin": "incoming_extraction",
        "item": _reference().model_dump(mode="json"),
        "condition": _extracted_condition().model_dump(mode="json"),
        "source_span": _span().model_dump(mode="json"),
        "native_expression": None,
        "explicitly_stated": True,
        "confidence": 0.9,
        "ambiguity_note": None,
    }
    incoming_transition = TransitionEvidence.model_validate(transition)
    activation_evidence = ActivationEvidence.model_validate(activation)
    batch = RoutingEvidenceBatch(
        chunk_id="chunk:1",
        pass_kind=RoutingPassKind.incoming_activation,
        examined_item_ids=("Q1",),
        evidence=(incoming_transition, activation_evidence),
        unresolved_references=(),
        notes=(),
    )
    assert isinstance(batch.evidence[0], TransitionEvidence)
    assert isinstance(batch.evidence[1], ActivationEvidence)

    malformed = dict(activation)
    malformed["evidence_type"] = "transition"
    with pytest.raises(ValidationError):
        RoutingEvidenceBatch.model_validate(
            {
                "chunk_id": "chunk:1",
                "pass_kind": "incoming_activation",
                "examined_item_ids": ("Q1",),
                "evidence": (malformed,),
                "unresolved_references": (),
                "notes": (),
            }
        )
    with pytest.raises(ValidationError, match="forward"):
        RoutingEvidenceBatch.model_validate(
            {
                "chunk_id": "chunk:1",
                "pass_kind": "forward",
                "examined_item_ids": ("Q1",),
                "evidence": (activation,),
                "unresolved_references": (),
                "notes": (),
            }
        )


def test_native_expression_preserves_exact_and_opaque_projections() -> None:
    supported = NativeExpression(
        language="xpath",
        version="1.0",
        exact_expression="${q1} = 1",
        parsed_references=(_reference(),),
        canonical_projection=_canonical_condition(),
    )
    unsupported = NativeExpression(
        language="xpath",
        version="1.0",
        exact_expression="indexed-repeat(${q1}, ${i})",
        parsed_references=(_reference(),),
        canonical_projection=CanonicalRoutingCondition(
            operator=ConditionOperator.opaque,
            question_node_id=None,
            value=None,
            values=None,
            children=None,
            raw_text="indexed-repeat(${q1}, ${i})",
        ),
    )
    assert supported.canonical_projection.operator is ConditionOperator.equals
    assert unsupported.canonical_projection.operator is ConditionOperator.opaque

    evidence = _transition().model_dump(mode="python")
    evidence.update(origin="native_parser", native_expression=supported)
    assert TransitionEvidence.model_validate(evidence).native_expression == supported
    evidence.update(origin="forward_extraction")
    with pytest.raises(ValidationError, match="native"):
        TransitionEvidence.model_validate(evidence)


def test_native_and_perspective_contracts_reject_ambiguous_origins() -> None:
    native = NativeExpression(
        language="xpath",
        version="1.0",
        exact_expression="${q1} = 1",
        parsed_references=(_reference(),),
        canonical_projection=_canonical_condition(),
    )
    with pytest.raises(ValidationError, match="unique"):
        NativeExpression(
            language="xpath",
            version="1.0",
            exact_expression="${q1} = 1",
            parsed_references=(_reference(), _reference()),
            canonical_projection=_canonical_condition(),
        )
    values = _transition().model_dump(mode="python")
    values.update(origin=EvidenceOrigin.forward_extraction, perspective="incoming")
    with pytest.raises(ValidationError, match="forward evidence"):
        TransitionEvidence.model_validate(values)
    values.update(origin=EvidenceOrigin.incoming_extraction, perspective="outgoing")
    with pytest.raises(ValidationError, match="incoming evidence"):
        TransitionEvidence.model_validate(values)
    values.update(
        origin=EvidenceOrigin.native_parser,
        perspective="incoming",
        native_expression=native,
    )
    with pytest.raises(ValidationError, match="native evidence"):
        TransitionEvidence.model_validate(values)
    values.update(perspective="outgoing", native_expression=None)
    with pytest.raises(ValidationError, match="native evidence origin"):
        TransitionEvidence.model_validate(values)


def test_batch_rejects_duplicate_items_and_wrong_pass_origins() -> None:
    values = {
        "chunk_id": "chunk:1",
        "pass_kind": "forward",
        "examined_item_ids": ("Q1", "Q1"),
        "evidence": (),
        "unresolved_references": (),
        "notes": (),
    }
    with pytest.raises(ValidationError, match="examined"):
        RoutingEvidenceBatch.model_validate(values)

    activation = ActivationEvidence(
        evidence_type="activation",
        local_id="local:activation",
        origin=EvidenceOrigin.forward_extraction,
        item=_reference(),
        condition=_extracted_condition(),
        source_span=_span(),
        native_expression=None,
        explicitly_stated=True,
        confidence=1.0,
        ambiguity_note=None,
    )
    values.update(
        pass_kind="incoming_activation",
        examined_item_ids=("Q1",),
        evidence=(activation,),
    )
    with pytest.raises(ValidationError, match="incoming evidence origin"):
        RoutingEvidenceBatch.model_validate(values)


@pytest.mark.parametrize(
    ("kind", "condition"),
    [
        (TransitionKind.conditional, None),
        (TransitionKind.default, _extracted_condition()),
        (TransitionKind.unconditional, _extracted_condition()),
        (TransitionKind.sequential, _extracted_condition()),
    ],
)
def test_transition_evidence_enforces_exact_kind_shape(
    kind: TransitionKind,
    condition: ExtractedRoutingCondition | None,
) -> None:
    values = _transition().model_dump(mode="python")
    values.update(transition_kind=kind, condition=condition)
    with pytest.raises(ValidationError):
        TransitionEvidence.model_validate(values)


def test_batch_and_audit_reject_duplicate_identifiers() -> None:
    with pytest.raises(ValidationError, match="local identifiers"):
        RoutingEvidenceBatch(
            chunk_id="chunk:1",
            pass_kind=RoutingPassKind.forward,
            examined_item_ids=("Q1",),
            evidence=(_transition(), _transition()),
            unresolved_references=(),
            notes=(),
        )
    with pytest.raises(ValidationError, match="evidence identifiers"):
        _audit(evidence=(_evidence_record(), _evidence_record()))
    with pytest.raises(ValidationError, match="span identifiers"):
        _audit(source_spans=(_span(), _span()))


def test_candidate_can_preserve_an_unresolved_target_outside_accepted_graph() -> None:
    candidate = CandidateEdge(
        candidate_id="candidate:1",
        source_node_id="question:q1",
        target_node_id=None,
        target_reference=ItemReference(
            raw_reference="the next work question",
            source_item_id=None,
            canonical_hint=None,
            section_path=("work",),
            node_kind=NodeKind.question,
        ),
        kind=EdgeKind.conditional,
        condition=_extracted_condition(),
        priority=None,
        evidence_ids=("evidence:1",),
        confidence=0.6,
        status=CandidateStatus.needs_human_review,
    )
    audit = _audit(candidate_edges=(candidate,))

    assert audit.candidate_edges[0].target_node_id is None
    assert _valid_graph().edges == _valid_graph().edges


def _candidate(candidate_id: str = "candidate:1") -> CandidateEdge:
    return CandidateEdge(
        candidate_id=candidate_id,
        source_node_id="question:q1",
        target_node_id="terminal:complete",
        target_reference=_reference("END", kind=NodeKind.terminal),
        kind=EdgeKind.conditional,
        condition=_extracted_condition(),
        priority=1,
        evidence_ids=("evidence:1",),
        confidence=0.9,
        status=CandidateStatus.needs_agent_review,
    )


def _discrepancy() -> RoutingDiscrepancy:
    return RoutingDiscrepancy(
        discrepancy_id="discrepancy:1",
        kind=DiscrepancyKind.conflicting_target,
        candidate_ids=("candidate:1",),
        evidence_ids=("evidence:1",),
        source_span_ids=("span:q1",),
        summary="The extracted target needs bounded review.",
        needs_human_review=False,
        resolved_by_decision_id=None,
    )


def _decision(
    decision_id: str,
    *,
    supersedes: str | None = None,
    action: ReviewAction = ReviewAction.confirm_candidate,
) -> ReviewDecision:
    return ReviewDecision(
        decision_id=decision_id,
        discrepancy_ids=("discrepancy:1",),
        candidate_ids=("candidate:1",),
        evidence_ids=("evidence:1",),
        cited_span_ids=("span:q1",),
        action=action,
        replacement=None,
        rationale="The cited instruction confirms the candidate.",
        confidence=0.95,
        needs_human_review=False,
        prompt_version="1.0.0",
        prompt_sha256="b" * 64,
        provider_response_sha256="c" * 64,
        supersedes_decision_id=supersedes,
    )


def _replacement() -> ReplacementEdge:
    return ReplacementEdge(
        source_node_id="question:q1",
        target_node_id="terminal:complete",
        target_reference=_reference("END", kind=NodeKind.terminal),
        kind=EdgeKind.conditional,
        condition=_extracted_condition(),
        priority=1,
        evidence_ids=("evidence:1",),
    )


def test_review_decisions_are_append_only_and_link_supersession() -> None:
    discrepancy = _discrepancy().model_copy(update={"resolved_by_decision_id": "decision:2"})
    audit = _audit(
        candidate_edges=(_candidate(),),
        discrepancies=(discrepancy,),
        review_decisions=(
            _decision("decision:1"),
            _decision("decision:2", supersedes="decision:1"),
        ),
    )
    assert audit.review_decisions[-1].supersedes_decision_id == "decision:1"

    values = audit.model_dump(mode="json")
    values["review_decisions"][1]["supersedes_decision_id"] = None
    with pytest.raises(ValidationError, match="supersede"):
        RoutingAudit.model_validate(values)
    values = audit.model_dump(mode="json")
    values["review_decisions"][0]["supersedes_decision_id"] = "decision:2"
    with pytest.raises(ValidationError, match="earlier"):
        RoutingAudit.model_validate(values)


def test_replace_decision_requires_typed_replacement_and_other_actions_forbid_it() -> None:
    with pytest.raises(ValidationError, match="replacement"):
        _decision("decision:1", action=ReviewAction.replace_candidate)

    replacement = _candidate("replacement:1").model_dump(mode="python")
    replacement.pop("candidate_id")
    decision = _decision("decision:1").model_dump(mode="python")
    decision.update(action="confirm_candidate", replacement=replacement)
    with pytest.raises(ValidationError, match="replacement"):
        ReviewDecision.model_validate(decision)


def test_valid_replacement_decision_is_source_cited_and_graph_bounded() -> None:
    decision_values = _decision(
        "decision:replace",
        action=ReviewAction.confirm_candidate,
    ).model_dump(mode="json")
    decision_values.update(
        action="replace_candidate",
        replacement=_replacement().model_dump(mode="json"),
    )
    decision = ReviewDecision.model_validate(decision_values)
    discrepancy = _discrepancy().model_copy(update={"resolved_by_decision_id": "decision:replace"})
    base = _valid_graph()
    audit = base.routing_audit.model_copy(
        update={
            "candidate_edges": (_candidate(),),
            "discrepancies": (discrepancy,),
            "review_decisions": (decision,),
        }
    )
    values = base.model_dump(mode="json")
    values["routing_audit"] = audit.model_dump(mode="json")

    graph = QuestionnaireRoutingGraph.model_validate(values)

    assert graph.routing_audit.review_decisions[0].replacement == _replacement()


def test_accepted_edge_rejects_unrelated_existing_evidence() -> None:
    values = _graph_data()
    values["edges"][1]["evidence_ids"] = ["evidence:entry"]

    with pytest.raises(ValidationError, match="same canonical route"):
        QuestionnaireRoutingGraph.model_validate(values)


def test_reviewed_edge_rejects_unrelated_candidate_evidence() -> None:
    values = _graph_data()
    candidate = _candidate().model_copy(update={"evidence_ids": ("evidence:entry",)})
    discrepancy = _discrepancy().model_copy(
        update={
            "evidence_ids": ("evidence:entry",),
            "resolved_by_decision_id": "decision:confirm",
        }
    )
    decision = _decision("decision:confirm").model_copy(
        update={"evidence_ids": ("evidence:entry",)}
    )
    values["routing_audit"]["candidate_edges"] = [candidate.model_dump(mode="json")]
    values["routing_audit"]["discrepancies"] = [discrepancy.model_dump(mode="json")]
    values["routing_audit"]["review_decisions"] = [decision.model_dump(mode="json")]
    values["edges"][1].update(
        evidence_ids=["evidence:entry"],
        review_decision_id="decision:confirm",
    )

    with pytest.raises(ValidationError, match="reviewed candidate"):
        QuestionnaireRoutingGraph.model_validate(values)


def test_reviewed_replacement_reference_must_match_accepted_target() -> None:
    values = _graph_data()
    candidate = _candidate()
    discrepancy = _discrepancy().model_copy(update={"resolved_by_decision_id": "decision:replace"})
    replacement = _replacement().model_copy(update={"target_reference": _reference("Q1")})
    decision_values = _decision("decision:replace").model_dump(mode="json")
    decision_values.update(
        action=ReviewAction.replace_candidate,
        replacement=replacement.model_dump(mode="json"),
    )
    values["routing_audit"]["candidate_edges"] = [candidate.model_dump(mode="json")]
    values["routing_audit"]["discrepancies"] = [discrepancy.model_dump(mode="json")]
    values["routing_audit"]["review_decisions"] = [decision_values]
    values["edges"][1]["review_decision_id"] = "decision:replace"

    with pytest.raises(ValidationError, match="active review decision"):
        QuestionnaireRoutingGraph.model_validate(values)


def test_unresolved_decision_requires_human_review() -> None:
    values = _decision("decision:1").model_dump(mode="json")
    values.update(action="unresolved", needs_human_review=False)
    with pytest.raises(ValidationError, match="human review"):
        ReviewDecision.model_validate(values)


@pytest.mark.parametrize(
    "mutation",
    [
        "candidate_evidence",
        "discrepancy_candidate",
        "discrepancy_evidence",
        "discrepancy_span",
        "decision_discrepancy",
        "decision_candidate",
        "decision_evidence",
        "decision_span",
        "replacement_evidence",
        "resolution_decision",
    ],
)
def test_audit_rejects_dangling_references(mutation: str) -> None:
    decision_values = _decision("decision:1").model_dump(mode="json")
    discrepancy = _discrepancy().model_copy(update={"resolved_by_decision_id": "decision:1"})
    audit = _audit(
        candidate_edges=(_candidate(),),
        discrepancies=(discrepancy,),
        review_decisions=(ReviewDecision.model_validate(decision_values),),
    ).model_dump(mode="json")
    if mutation == "candidate_evidence":
        audit["candidate_edges"][0]["evidence_ids"] = ["missing"]
    elif mutation == "discrepancy_candidate":
        audit["discrepancies"][0]["candidate_ids"] = ["missing"]
    elif mutation == "discrepancy_evidence":
        audit["discrepancies"][0]["evidence_ids"] = ["missing"]
    elif mutation == "discrepancy_span":
        audit["discrepancies"][0]["source_span_ids"] = ["missing"]
    elif mutation == "decision_discrepancy":
        audit["review_decisions"][0]["discrepancy_ids"] = ["missing"]
    elif mutation == "decision_candidate":
        audit["review_decisions"][0]["candidate_ids"] = ["missing"]
    elif mutation == "decision_evidence":
        audit["review_decisions"][0]["evidence_ids"] = ["missing"]
    elif mutation == "decision_span":
        audit["review_decisions"][0]["cited_span_ids"] = ["missing"]
    elif mutation == "replacement_evidence":
        audit["review_decisions"][0].update(
            action="replace_candidate",
            replacement=_replacement().model_dump(mode="json"),
        )
        audit["review_decisions"][0]["replacement"]["evidence_ids"] = ["missing"]
    else:
        audit["discrepancies"][0]["resolved_by_decision_id"] = "missing"

    with pytest.raises(ValidationError):
        RoutingAudit.model_validate(audit)


def test_audit_enforces_inventory_identity_and_variable_cardinality() -> None:
    assert _audit(inventory=(_inventory_item(),)).inventory[0].node_id == "question:q1"

    with pytest.raises(ValidationError, match="inventory node identifiers"):
        _audit(inventory=(_inventory_item(), _inventory_item()))
    with pytest.raises(ValidationError, match="more than one inventory"):
        _audit(
            inventory=(
                _inventory_item(),
                _inventory_item("question:q2"),
            )
        )
    values = _inventory_item().model_dump(mode="json")
    values["parent_node_id"] = "question:q1"
    with pytest.raises(ValidationError, match="contain itself"):
        InventoryItem.model_validate(values)


def test_containment_and_node_models_reject_impossible_local_shapes() -> None:
    with pytest.raises(ValidationError, match="entry child"):
        Containment(
            parent_node_id=None,
            child_node_ids=("question:q1",),
            entry_child_node_id="question:q2",
        )
    values = _node("question:q1", NodeKind.question).model_dump(mode="json")
    values["terminal_kind"] = "survey_complete"
    with pytest.raises(ValidationError, match="terminal kind"):
        RoutingNode.model_validate(values)
    values = _node("question:q1", NodeKind.question).model_dump(mode="json")
    values["repeat_spec"] = {
        "repeat_kind": "other",
        "iterator_label": "item",
        "collection_source": None,
        "continuation_condition": None,
        "maximum_iterations": None,
    }
    with pytest.raises(ValidationError, match="repeat spec"):
        RoutingNode.model_validate(values)
    values = _node("entry:start", NodeKind.entry).model_dump(mode="json")
    values["activation_condition"] = _canonical_condition().model_dump(mode="json")
    with pytest.raises(ValidationError, match="activation"):
        RoutingNode.model_validate(values)
    values = _node("question:q1", NodeKind.question).model_dump(mode="json")
    values["next_node_ids"] = ["question:q1", "question:q1"]
    with pytest.raises(ValidationError, match="unique"):
        RoutingNode.model_validate(values)


@pytest.mark.parametrize("model_name", ["edge", "candidate", "replacement"])
def test_flow_records_reject_conditions_and_priority_on_wrong_kinds(model_name: str) -> None:
    if model_name == "edge":
        values = _valid_graph().edges[0].model_dump(mode="json")
        model = RoutingEdge
    elif model_name == "candidate":
        values = _candidate().model_dump(mode="json")
        model = CandidateEdge
    else:
        values = _replacement().model_dump(mode="json")
        model = ReplacementEdge
    values.update(kind="sequential", condition=None, priority=1)
    with pytest.raises(ValidationError, match="priority"):
        model.model_validate(values)
    values.update(kind="conditional", condition=None, priority=None)
    with pytest.raises(ValidationError, match="condition"):
        model.model_validate(values)


def test_repeat_containment_loop_and_diagnostic_can_form_a_valid_graph() -> None:
    graph = _repeat_graph()

    assert graph.nodes[1].containment.entry_child_node_id == "question:q1"
    assert graph.loops[0].kind is LoopKind.repeat_group
    assert graph.diagnostics[0].severity is DiagnosticSeverity.info


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_parent",
        "non_container",
        "entry_edge_kind",
        "loop_repeat_node",
        "loop_entry_role",
        "loop_return_role",
        "loop_exit_role",
    ],
)
def test_repeat_graph_rejects_invalid_containment_and_loop_roles(mutation: str) -> None:
    values = _repeat_graph().model_dump(mode="json")
    if mutation == "unknown_parent":
        values["nodes"][2]["containment"]["parent_node_id"] = "missing"
    elif mutation == "non_container":
        values["nodes"][1]["kind"] = "question"
        values["nodes"][1]["source_item_id"] = "Q0"
        values["nodes"][1]["raw_name"] = "q0"
        values["nodes"][1]["repeat_spec"] = None
        values["nodes"][1]["containment"]["entry_child_node_id"] = None
    elif mutation == "entry_edge_kind":
        values["edges"][1]["kind"] = "sequential"
    elif mutation == "loop_repeat_node":
        values["loops"][0]["repeat_group_node_id"] = "question:q1"
    elif mutation == "loop_entry_role":
        values["loops"][0]["entry_edge_ids"] = ["edge:group-entry"]
        values["loops"][0]["member_edge_ids"] = []
    elif mutation == "loop_return_role":
        values["loops"][0]["return_edge_ids"] = ["edge:exit"]
        values["loops"][0]["exit_edge_ids"] = []
    else:
        values["loops"][0]["member_edge_ids"] = []
        values["loops"][0]["exit_edge_ids"] = ["edge:group-entry"]

    with pytest.raises(ValidationError):
        QuestionnaireRoutingGraph.model_validate(values)


@pytest.mark.parametrize(
    "mutation",
    [
        "entry_kind",
        "accepted_evidence",
        "accepted_decision",
        "candidate_source",
        "candidate_target",
        "inventory_node",
        "diagnostic_edge",
        "diagnostic_evidence",
        "diagnostic_candidate",
    ],
)
def test_graph_rejects_dangling_audit_and_diagnostic_namespaces(mutation: str) -> None:
    values = _graph_data()
    if mutation == "entry_kind":
        values["entry_node_ids"] = ["question:q1"]
    elif mutation == "accepted_evidence":
        values["edges"][0]["evidence_ids"] = ["missing"]
    elif mutation == "accepted_decision":
        values["edges"][0]["review_decision_id"] = "missing"
    elif mutation in {"candidate_source", "candidate_target", "diagnostic_candidate"}:
        candidate = _candidate().model_dump(mode="json")
        if mutation == "candidate_source":
            candidate["source_node_id"] = "missing"
        elif mutation == "candidate_target":
            candidate["target_node_id"] = "missing"
        values["routing_audit"]["candidate_edges"] = [candidate]
        if mutation == "diagnostic_candidate":
            values["diagnostics"] = [
                RoutingDiagnostic(
                    diagnostic_id="diagnostic:1",
                    code="TEST",
                    severity=DiagnosticSeverity.warning,
                    message="A safe test diagnostic.",
                    node_ids=(),
                    edge_ids=(),
                    evidence_ids=(),
                    candidate_ids=("missing",),
                ).model_dump(mode="json")
            ]
    elif mutation == "inventory_node":
        values["routing_audit"]["inventory"] = [_inventory_item("missing").model_dump(mode="json")]
    else:
        diagnostic = RoutingDiagnostic(
            diagnostic_id="diagnostic:1",
            code="TEST",
            severity=DiagnosticSeverity.warning,
            message="A safe test diagnostic.",
            node_ids=(),
            edge_ids=("missing",) if mutation == "diagnostic_edge" else (),
            evidence_ids=("missing",) if mutation == "diagnostic_evidence" else (),
            candidate_ids=(),
        )
        values["diagnostics"] = [diagnostic.model_dump(mode="json")]

    with pytest.raises(ValidationError):
        QuestionnaireRoutingGraph.model_validate(values)


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate_node",
        "duplicate_edge",
        "dangling_edge",
        "terminal_outgoing",
        "adjacency_mismatch",
        "multiple_defaults",
        "unknown_entry",
        "condition_reference",
    ],
)
def test_graph_rejects_structural_corruption(mutation: str) -> None:
    values = _graph_data()
    if mutation == "duplicate_node":
        values["nodes"].append(values["nodes"][0])
    elif mutation == "duplicate_edge":
        values["edges"].append(values["edges"][0])
    elif mutation == "dangling_edge":
        values["edges"][1]["target_node_id"] = "missing"
    elif mutation == "terminal_outgoing":
        values["edges"][1]["source_node_id"] = "terminal:complete"
        values["nodes"][1]["outgoing_edge_ids"] = []
        values["nodes"][1]["next_node_ids"] = []
        values["nodes"][2]["incoming_edge_ids"] = ["edge:end"]
        values["nodes"][2]["previous_node_ids"] = ["terminal:complete"]
        values["nodes"][2]["outgoing_edge_ids"] = ["edge:end"]
        values["nodes"][2]["next_node_ids"] = ["terminal:complete"]
    elif mutation == "adjacency_mismatch":
        values["nodes"][1]["incoming_edge_ids"] = []
    elif mutation == "multiple_defaults":
        values["edges"][0]["kind"] = "default"
        values["edges"][1]["kind"] = "default"
        values["edges"][1]["condition"] = None
        values["edges"][1]["source_node_id"] = "entry:start"
        values["nodes"][0]["outgoing_edge_ids"] = ["edge:entry", "edge:end"]
        values["nodes"][0]["next_node_ids"] = ["question:q1", "terminal:complete"]
        values["nodes"][1]["outgoing_edge_ids"] = []
        values["nodes"][1]["next_node_ids"] = []
        values["nodes"][2]["previous_node_ids"] = ["entry:start"]
    elif mutation == "unknown_entry":
        values["entry_node_ids"] = ["missing"]
    else:
        values["edges"][1]["condition"]["question_node_id"] = "entry:start"

    with pytest.raises(ValidationError):
        QuestionnaireRoutingGraph.model_validate(values)


def test_containment_is_acyclic_and_children_are_derived_in_node_order() -> None:
    values = _graph_data()
    values["nodes"][0]["containment"].update(
        parent_node_id="question:q1", child_node_ids=["question:q1"]
    )
    values["nodes"][1]["containment"].update(
        parent_node_id="entry:start", child_node_ids=["entry:start"]
    )
    with pytest.raises(ValidationError, match="acyclic"):
        QuestionnaireRoutingGraph.model_validate(values)

    values = _graph_data()
    values["nodes"][0]["containment"]["child_node_ids"] = ["question:q1"]
    with pytest.raises(ValidationError, match="derived in node"):
        QuestionnaireRoutingGraph.model_validate(values)


def test_section_and_repeat_nodes_require_valid_entry_children_and_edges() -> None:
    values = _graph_data()
    values["nodes"][1].update(
        kind="section",
        source_item_id=None,
        raw_name=None,
    )
    with pytest.raises(ValidationError, match="entry child"):
        QuestionnaireRoutingGraph.model_validate(values)

    with pytest.raises(ValidationError, match="repeat spec"):
        _node("repeat:roster", NodeKind.repeat_group)


def test_loop_and_diagnostic_references_must_be_canonical() -> None:
    loop = LoopDefinition(
        loop_id="loop:1",
        kind=LoopKind.correction_return,
        repeat_group_node_id=None,
        member_node_ids=("question:q1",),
        entry_edge_ids=("edge:entry",),
        member_edge_ids=(),
        return_edge_ids=("edge:end",),
        exit_edge_ids=(),
        source_supported=True,
        evidence_ids=("evidence:1",),
    )
    diagnostic = RoutingDiagnostic(
        diagnostic_id="diagnostic:1",
        code="UNRESOLVED_TEST",
        severity=DiagnosticSeverity.warning,
        message="A fixed safe diagnostic.",
        node_ids=("missing",),
        edge_ids=(),
        evidence_ids=(),
        candidate_ids=(),
    )
    values = _graph_data()
    values["loops"] = [loop.model_dump(mode="json")]
    with pytest.raises(ValidationError, match="loop"):
        QuestionnaireRoutingGraph.model_validate(values)
    values = _graph_data()
    values["diagnostics"] = [diagnostic.model_dump(mode="json")]
    with pytest.raises(ValidationError, match="diagnostic"):
        QuestionnaireRoutingGraph.model_validate(values)


def test_final_models_are_deeply_immutable_and_detach_mutable_inputs() -> None:
    source_spans = [_span()]
    audit = RoutingAudit.model_validate(
        {
            "source_binding": _source_binding(),
            "inventory": [],
            "source_spans": source_spans,
            "evidence": [_evidence_record()],
            "candidate_edges": [],
            "discrepancies": [],
            "review_decisions": [],
        }
    )
    source_spans.clear()
    assert len(audit.source_spans) == 1
    assert isinstance(audit.source_spans, tuple)
    with pytest.raises(ValidationError):
        audit.source_binding = _source_binding()
    with pytest.raises(ValidationError):
        audit.source_spans[0].source_quote = "changed"


def _routed_svis() -> RoutedSurveySVIS:
    variable = RoutedSurveyVariable.model_validate(
        {
            "raw_name": "q_age",
            "label": "Age",
            "question_text": "How old are you?",
            "data_type": DataType.numeric,
            "categories": (AnswerCategory(code=1, label="One"),),
            "numeric_range": NumericRange(min_value=0, max_value=120, notes=None),
            "universe": "All people",
            "skip_condition_raw": None,
            "module": "Roster",
            "unit_of_analysis": UnitLevel.individual,
            "source_page": 0,
            "extraction_confidence": 1.0,
            "needs_review": False,
            "notes": None,
            "routing_node_id": "question:q1",
        }
    )
    return RoutedSurveySVIS(
        survey_id="TST_2024_SYNTH",
        country_code="TST",
        year=2024,
        survey_name="Synthetic Survey",
        study_type=StudyType.other,
        data_collection_mode="paper",
        language="English",
        variables=(variable,),
        source_file="questionnaire.txt",
        source_format="txt",
        extraction_date=date(2024, 6, 1),
        extraction_notes=None,
        routing_schema_version="1.0",
        routing_graph=_valid_graph(),
    )


def test_routed_projection_reconstructs_exact_ordered_v1_types() -> None:
    routed = _routed_svis()

    legacy = routed.to_survey_svis()

    assert type(legacy) is SurveySVIS
    assert routed.variables[0].categories is not None
    assert type(routed.variables[0].categories[0]) is RoutedAnswerCategory
    assert type(routed.variables[0].numeric_range) is RoutedNumericRange
    assert type(legacy.variables[0]) is SurveyVariable
    assert legacy.variables[0].categories is not None
    assert type(legacy.variables[0].categories[0]) is AnswerCategory
    assert type(legacy.variables[0].numeric_range) is NumericRange
    assert list(legacy.model_dump()) == list(SurveySVIS.model_fields)
    assert list(legacy.variables[0].model_dump()) == list(SurveyVariable.model_fields)
    assert "routing_node_id" not in legacy.variables[0].model_dump()
    assert "routing_graph" not in legacy.model_dump()
    assert (
        legacy.model_dump_json()
        == SurveySVIS.model_validate_json(legacy.model_dump_json()).model_dump_json()
    )
    with pytest.raises(ValidationError):
        routed.variables[0].categories[0].label = "Changed"


def test_nullable_unlinked_variable_projects_without_mutable_nested_values() -> None:
    values = _routed_svis().model_dump(mode="json")
    values["variables"][0].update(
        categories=None,
        numeric_range=None,
        routing_node_id=None,
    )
    question_inventory = next(
        item
        for item in values["routing_graph"]["routing_audit"]["inventory"]
        if item["node_id"] == "question:q1"
    )
    question_inventory["linked_variable_indices"] = []
    routed = RoutedSurveySVIS.model_validate(values)

    legacy = routed.to_survey_svis()

    assert routed.variables[0].routing_node_id is None
    assert legacy.variables[0].categories is None
    assert legacy.variables[0].numeric_range is None


def test_routed_model_rejects_source_binding_and_variable_link_mismatch() -> None:
    values = _routed_svis().model_dump(mode="json")
    values["routing_graph"]["routing_audit"]["source_binding"]["survey_id"] = "OTHER"
    with pytest.raises(ValidationError, match="source binding"):
        RoutedSurveySVIS.model_validate(values)

    values = _routed_svis().model_dump(mode="json")
    values["variables"][0]["routing_node_id"] = "entry:start"
    with pytest.raises(ValidationError, match="question nodes"):
        RoutedSurveySVIS.model_validate(values)


def test_routed_variable_link_must_equal_its_inventory_index_mapping() -> None:
    present_mapping = _routed_svis().model_dump(mode="json")
    present_mapping["variables"][0]["routing_node_id"] = None
    with pytest.raises(ValidationError, match="match inventory"):
        RoutedSurveySVIS.model_validate(present_mapping)

    missing_mapping = _routed_svis().model_dump(mode="json")
    question_inventory = next(
        item
        for item in missing_mapping["routing_graph"]["routing_audit"]["inventory"]
        if item["node_id"] == "question:q1"
    )
    question_inventory["linked_variable_indices"] = []
    with pytest.raises(ValidationError, match="match inventory"):
        RoutedSurveySVIS.model_validate(missing_mapping)

    wrong_question = _routed_svis().model_dump(mode="json")
    second_node = _node("question:q2", NodeKind.question).model_dump(mode="json")
    second_node.update(source_item_id="Q2", raw_name="q2")
    wrong_question["routing_graph"]["nodes"].append(second_node)
    first_inventory = next(
        item
        for item in wrong_question["routing_graph"]["routing_audit"]["inventory"]
        if item["node_id"] == "question:q1"
    )
    first_inventory["linked_variable_indices"] = []
    wrong_question["routing_graph"]["routing_audit"]["inventory"].append(
        _route_inventory_item(
            "question:q2",
            raw_reference="Q2",
            kind=NodeKind.question,
            source_order=3,
            linked_variable_indices=(0,),
        ).model_dump(mode="json")
    )
    with pytest.raises(ValidationError, match="match inventory"):
        RoutedSurveySVIS.model_validate(wrong_question)

    out_of_range = _routed_svis().model_dump(mode="json")
    out_of_range["routing_graph"]["routing_audit"]["inventory"][1]["linked_variable_indices"] = [1]
    with pytest.raises(ValidationError, match="outside"):
        RoutedSurveySVIS.model_validate(out_of_range)


def test_routed_variable_rejects_non_collection_categories() -> None:
    values = _routed_svis().variables[0].model_dump(mode="json")
    values["categories"] = "not-a-category-list"
    with pytest.raises(ValidationError):
        RoutedSurveyVariable.model_validate(values)


def test_routed_model_preserves_legacy_field_definitions_and_order() -> None:
    assert list(SurveyVariable.model_fields) == [
        "raw_name",
        "label",
        "question_text",
        "data_type",
        "categories",
        "numeric_range",
        "universe",
        "skip_condition_raw",
        "module",
        "unit_of_analysis",
        "source_page",
        "extraction_confidence",
        "needs_review",
        "notes",
    ]
    assert list(RoutedSurveyVariable.model_fields)[-1] == "routing_node_id"
    assert list(RoutedSurveySVIS.model_fields)[-2:] == [
        "routing_schema_version",
        "routing_graph",
    ]


def test_routed_and_graph_versions_are_equal_and_fixed_at_one() -> None:
    values = _routed_svis().model_dump(mode="json")
    values["routing_schema_version"] = "2.0"
    with pytest.raises(ValidationError):
        RoutedSurveySVIS.model_validate(values)
    values = _routed_svis().model_dump(mode="json")
    values["routing_graph"]["schema_version"] = "2.0"
    with pytest.raises(ValidationError):
        RoutedSurveySVIS.model_validate(values)


def test_routed_serializer_rejects_edge_with_unrelated_existing_evidence() -> None:
    routed = _routed_svis()
    edges = list(routed.routing_graph.edges)
    edges[1] = edges[1].model_copy(update={"evidence_ids": ("evidence:entry",)})
    invalid_graph = routed.routing_graph.model_copy(update={"edges": tuple(edges)})
    invalid = routed.model_copy(update={"routing_graph": invalid_graph})

    with pytest.raises(ArtifactWriteError, match="Routed artifact validation failed"):
        RoutedSurveySVISArtifactSerializer().build_plan(invalid, survey_id=invalid.survey_id)


def test_json_round_trip_preserves_graph_and_discriminated_evidence() -> None:
    graph = _valid_graph()

    restored = QuestionnaireRoutingGraph.model_validate_json(graph.model_dump_json())

    assert restored == graph
    assert isinstance(restored.routing_audit.evidence[0].observation, TransitionEvidence)


def test_canonical_json_schema_export_matches_deterministic_fixture(
    repository_root: Path,
) -> None:
    fixture = (
        repository_root / "tests/fixtures/routing/schema/questionnaire-routing-graph-v1.0.json"
    )
    exported = canonical_routing_schema_json()

    assert exported == canonical_routing_schema_json()
    assert exported == fixture.read_text(encoding="utf-8")
    assert json.loads(exported) == QuestionnaireRoutingGraph.model_json_schema()
