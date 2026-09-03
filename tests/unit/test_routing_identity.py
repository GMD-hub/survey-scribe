"""Deterministic questionnaire identity and source evidence tests."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from survey_scribe.models.routing import InventoryItem, RoutingSourceBinding
from survey_scribe.models.svis import DataType, SurveySVIS, SurveyVariable
from survey_scribe.routing.contracts import (
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
from survey_scribe.routing.identity import (
    IdentityCollisionError,
    IdentityError,
    IdentityResolver,
    NodeIdentityInput,
    ReferenceResolution,
    SourceBindingError,
    SourceEvidenceError,
    assign_node_ids,
    build_evidence_records,
    create_source_binding,
    normalize_section_path,
    normalized_alias,
    resolve_extracted_condition,
    validate_source_binding,
    verify_source_quote,
)
from survey_scribe.routing.normalization import normalized_alias_value
from survey_scribe.sources.base import SourceBlock, SourceDocument, SourceProvenance


def _svis() -> SurveySVIS:
    return SurveySVIS(
        survey_id="TST_2024_SYNTH",
        country_code="TST",
        year=2024,
        survey_name="Synthetic survey",
        variables=[
            SurveyVariable(
                raw_name="q1",
                question_text="Question one",
                data_type=DataType.numeric,
                extraction_confidence=1.0,
            )
        ],
        source_file="questionnaire.txt",
        source_format="txt",
        extraction_date=date(2024, 6, 1),
    )


def _document(*texts: str, digest: str = "a" * 64) -> SourceDocument:
    provenance = SourceProvenance(source_name="questionnaire.txt", pages=(1,))
    return SourceDocument(
        source_name="questionnaire.txt",
        media_type="text/plain",
        blocks=tuple(
            SourceBlock(
                id=f"block-{index}",
                order=index,
                kind="text",
                text=text,
                provenance=provenance,
            )
            for index, text in enumerate(texts)
        ),
        snapshot_sha256=digest,
    )


def _identity(
    source_item_id: str | None,
    section_path: tuple[str, ...],
    ordinal: int,
    text: str,
    *,
    kind: NodeKind = NodeKind.question,
) -> NodeIdentityInput:
    return NodeIdentityInput(
        source_item_id=source_item_id,
        raw_reference=source_item_id or text,
        section_path=section_path,
        logical_ordinal=ordinal,
        normalized_source_text=text,
        kind=kind,
    )


def _inventory_item(
    node_id: str,
    source_item_id: str | None,
    section_path: tuple[str, ...],
    source_order: int,
    *,
    raw_reference: str | None = None,
) -> InventoryItem:
    return InventoryItem(
        node_id=node_id,
        source_item_id=source_item_id,
        raw_reference=raw_reference or source_item_id or "unprinted item",
        section_path=section_path,
        source_order=source_order,
        block_ids=(f"block-{source_order}",),
        kind=NodeKind.question,
        repeat_group_node_id=None,
        parent_node_id=None,
        linked_variable_indices=(),
    )


def _reference(
    value: str,
    section_path: tuple[str, ...],
    *,
    source_item_id: str | None = None,
    canonical_hint: str | None = None,
) -> ItemReference:
    return ItemReference(
        raw_reference=value,
        source_item_id=source_item_id,
        canonical_hint=canonical_hint,
        section_path=section_path,
        node_kind=NodeKind.question,
    )


def _span(
    *,
    span_id: str = "model-span-id",
    quote: str = "Q1. Continue to Q2.",
    block_id: str = "block-0",
) -> SourceSpan:
    return SourceSpan(
        span_id=span_id,
        block_id=block_id,
        source_name="questionnaire.txt",
        pages=(1,),
        sheet=None,
        row_start=None,
        row_end=None,
        source_quote=quote,
    )


def _transition(
    *, local_id: str = "model-local-id", span_id: str = "model-span-id"
) -> TransitionEvidence:
    return TransitionEvidence(
        evidence_type="transition",
        local_id=local_id,
        perspective=EvidencePerspective.outgoing,
        origin=EvidenceOrigin.forward_extraction,
        source=_reference("Q1", ("Main",), source_item_id="Q1"),
        target=_reference(
            "Q2",
            ("Main",),
            source_item_id="Q2",
            canonical_hint="model-final-target-id",
        ),
        transition_kind=TransitionKind.unconditional,
        condition=None,
        source_span=_span(span_id=span_id),
        native_expression=None,
        explicitly_stated=True,
        confidence=1.0,
        ambiguity_note=None,
    )


def test_printed_and_fallback_node_ids_are_stable_scoped_and_model_independent() -> None:
    seeds = (
        _identity("Q12", ("Household roster",), 1, "Question text"),
        _identity(None, ("Household roster",), 2, "Question without an ID"),
    )

    first = assign_node_ids(seeds, survey_id="TST_2024_SYNTH", source_version_digest="a" * 64)
    second = assign_node_ids(seeds, survey_id="TST_2024_SYNTH", source_version_digest="a" * 64)
    changed = assign_node_ids(seeds, survey_id="TST_2024_SYNTH", source_version_digest="b" * 64)

    assert first == second
    assert first[0] == "question:household-roster:q12"
    assert first[0] == changed[0]
    assert first[1].startswith("question:fallback:")
    assert first[1] != changed[1]


def test_fallback_identity_detects_digest_collisions() -> None:
    seeds = (
        _identity(None, ("Main",), 1, "First"),
        _identity(None, ("Main",), 2, "Second"),
    )

    with pytest.raises(IdentityCollisionError, match="fallback"):
        assign_node_ids(
            seeds,
            survey_id="TST_2024_SYNTH",
            source_version_digest="a" * 64,
            digest_factory=lambda _payload: "0" * 64,
        )


def test_identity_inputs_fail_closed_for_invalid_normalization_and_digests() -> None:
    fallback = (_identity(None, ("Main",), 1, "Question"),)
    with pytest.raises(IdentityError, match="survey identity"):
        assign_node_ids(fallback, survey_id=" ", source_version_digest="a" * 64)
    with pytest.raises(SourceBindingError, match="snapshot digest"):
        assign_node_ids(fallback, survey_id="SURVEY", source_version_digest="invalid")
    with pytest.raises(IdentityError, match="digest factory"):
        assign_node_ids(
            fallback,
            survey_id="SURVEY",
            source_version_digest="a" * 64,
            digest_factory=lambda _payload: "invalid",
        )
    with pytest.raises(IdentityError, match="section path"):
        normalize_section_path(("!!!",))
    with pytest.raises(IdentityError, match="item reference"):
        normalized_alias("...")


def test_duplicate_printed_identity_collision_is_detected_after_disambiguation() -> None:
    seeds = (
        _identity("Q1", ("Main",), 1, "First"),
        _identity("Question 1", ("Main",), 1, "Second"),
    )

    with pytest.raises(IdentityCollisionError, match="canonical"):
        assign_node_ids(seeds, survey_id="SURVEY", source_version_digest="a" * 64)


@pytest.mark.parametrize(
    "values",
    [
        {"status": "resolved", "node_id": "q1", "candidate_node_ids": ("q1", "q1")},
        {"status": "resolved", "node_id": None, "candidate_node_ids": ()},
        {"status": "unresolved", "node_id": "q1", "candidate_node_ids": ()},
        {"status": "ambiguous", "node_id": None, "candidate_node_ids": ("q1",)},
        {"status": "unresolved", "node_id": None, "candidate_node_ids": ("q1",)},
    ],
)
def test_reference_resolution_rejects_inconsistent_shapes(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ReferenceResolution.model_validate(values)


def test_exact_alias_resolution_is_section_scoped_and_bounded() -> None:
    items = (
        _inventory_item("question:agriculture:q1", "Q1", ("Agriculture",), 0),
        _inventory_item("question:employment:q1", "Q1", ("Employment",), 1),
        _inventory_item(
            "question:employment:pregunta-12",
            "Pregunta 12",
            ("Employment",),
            2,
        ),
    )
    resolver = IdentityResolver(items)

    aliases = ["Q1", "1", "Question 1", "Column Q1"]
    assert {resolver.resolve(_reference(alias, ("Agriculture",))).node_id for alias in aliases} == {
        "question:agriculture:q1"
    }
    assert (
        resolver.resolve(_reference("Q1", (), canonical_hint="model-choice")).status == "ambiguous"
    )
    assert resolver.resolve(_reference("Pregunta 12", ("Employment",))).status == "resolved"
    assert resolver.resolve(_reference("12", ("Employment",))).status == "unresolved"
    assert (
        resolver.resolve(
            _reference("Q1", ()),
            default_section_path=("Agriculture",),
        ).node_id
        == "question:agriculture:q1"
    )


def test_identity_resolver_rejects_duplicate_canonical_nodes() -> None:
    item = _inventory_item("question:main:q1", "Q1", ("Main",), 0)
    with pytest.raises(IdentityError, match="unique"):
        IdentityResolver((item, item.model_copy(update={"source_order": 1})))


def test_duplicate_aliases_in_one_namespace_return_ordered_candidates() -> None:
    items = (
        _inventory_item("question:main:q1:duplicate-1", "Q1", ("Main",), 0),
        _inventory_item("question:main:q1:duplicate-2", "Question 1", ("Main",), 1),
    )
    resolution = IdentityResolver(items).resolve(_reference("1", ("Main",)))

    assert resolution.status == "ambiguous"
    assert resolution.node_id is None
    assert resolution.candidate_node_ids == tuple(item.node_id for item in items)


def test_extracted_condition_resolves_only_unambiguous_question_references() -> None:
    items = (
        _inventory_item("question:main:q1", "Q1", ("Main",), 0),
        _inventory_item("question:main:q2", "Q2", ("Main",), 1),
    )
    resolver = IdentityResolver(items)
    extracted = ExtractedRoutingCondition(
        operator=ConditionOperator.all,
        item_reference=None,
        value=None,
        values=None,
        children=(
            ExtractedRoutingCondition(
                operator=ConditionOperator.equals,
                item_reference=_reference("Question 1", ("Main",)),
                value=1,
                values=None,
                children=None,
                raw_text="Q1 = 1",
            ),
            ExtractedRoutingCondition(
                operator=ConditionOperator.answered,
                item_reference=_reference("2", ("Main",)),
                value=None,
                values=None,
                children=None,
                raw_text="Q2 answered",
            ),
        ),
        raw_text="Q1 = 1 and Q2 answered",
    )

    result = resolve_extracted_condition(extracted, resolver)

    assert result.condition is not None
    assert result.condition.children is not None
    assert [child.question_node_id for child in result.condition.children] == [
        "question:main:q1",
        "question:main:q2",
    ]
    assert result.references[0].status == "resolved"

    ambiguous_resolver = IdentityResolver(
        items + (_inventory_item("question:main:q1:duplicate", "Question 1", ("Main",), 2),)
    )
    unresolved = resolve_extracted_condition(extracted, ambiguous_resolver)
    assert unresolved.condition is None
    assert unresolved.references[0].status == "ambiguous"


def test_source_binding_uses_and_validates_only_the_normalized_snapshot() -> None:
    document = _document("Q1. Question one")
    binding = create_source_binding(document, _svis())

    assert binding == RoutingSourceBinding(
        survey_id="TST_2024_SYNTH",
        source_name="questionnaire.txt",
        media_type="text/plain",
        snapshot_sha256="a" * 64,
        source_conversion_schema_version="1.0",
    )
    validate_source_binding(binding, document, _svis())

    changed_document = document.model_copy(update={"snapshot_sha256": "b" * 64})
    with pytest.raises(SourceBindingError, match="does not match"):
        validate_source_binding(binding, changed_document, _svis())
    with pytest.raises(SourceBindingError, match="validated snapshot digest"):
        create_source_binding(document.model_copy(update={"snapshot_sha256": None}), _svis())
    with pytest.raises(SourceBindingError, match="source name"):
        create_source_binding(document, _svis().model_copy(update={"source_file": "other.txt"}))
    with pytest.raises(SourceBindingError, match="source format"):
        create_source_binding(document, _svis().model_copy(update={"source_format": "pdf"}))
    with pytest.raises(SourceBindingError, match="schema version"):
        create_source_binding(document, _svis(), source_conversion_schema_version=" ")
    with pytest.raises(SourceBindingError, match="survey identity"):
        create_source_binding(document, _svis().model_copy(update={"survey_id": " "}))
    with pytest.raises(SourceBindingError, match="snapshot digest"):
        create_source_binding(document.model_copy(update={"snapshot_sha256": "invalid"}), _svis())

    mime_svis = _svis().model_copy(update={"source_format": "text/plain"})
    assert create_source_binding(document, mime_svis).media_type == "text/plain"


def test_shared_alias_normalization_preserves_distinct_unicode_identities() -> None:
    assert normalized_alias_value("É") == normalized_alias("É") == "é"
    assert normalized_alias_value("Ñ") == normalized_alias("Ñ") == "ñ"
    assert normalized_alias("É") != normalized_alias("Ñ")


def test_source_quote_verification_normalizes_only_bounded_whitespace() -> None:
    document = _document("Q1.  Continue\n\tto Q2.")

    verify_source_quote(_span(quote="Q1. Continue to Q2."), document)

    with pytest.raises(SourceEvidenceError, match="quote does not match"):
        verify_source_quote(_span(quote="q1. Continue to Q2."), document)
    with pytest.raises(SourceEvidenceError, match="source block"):
        verify_source_quote(_span(block_id="missing"), document)
    with pytest.raises(SourceEvidenceError, match="source name"):
        verify_source_quote(_span().model_copy(update={"source_name": "other.txt"}), document)
    with pytest.raises(SourceEvidenceError, match="provenance"):
        verify_source_quote(_span().model_copy(update={"pages": (2,)}), document)
    with pytest.raises(ValidationError):
        _span(quote="x" * 2001)


def test_evidence_ids_and_span_ids_are_deterministic_and_ignore_model_id_suggestions() -> None:
    document = _document("Q1. Continue to Q2.")
    first = build_evidence_records((_transition(),), document)
    second = build_evidence_records(
        (_transition(local_id="different-local-id", span_id="different-span-id"),),
        document,
    )

    assert first.source_spans == second.source_spans
    assert first.records[0].evidence_id == second.records[0].evidence_id
    assert first.source_spans[0].span_id.startswith("span:")
    assert first.records[0].evidence_id.startswith("evidence:")
    assert "model-span-id" not in first.source_spans[0].span_id
    assert "model-final-target-id" not in first.records[0].evidence_id


def test_evidence_builder_deduplicates_semantic_duplicates_and_detects_collisions() -> None:
    document = _document("Q1. Continue to Q2.")
    deduplicated = build_evidence_records(
        (_transition(local_id="one"), _transition(local_id="two")),
        document,
    )
    assert len(deduplicated.records) == 1

    different = _transition().model_copy(update={"confidence": 0.9})
    with pytest.raises(IdentityCollisionError, match="evidence"):
        build_evidence_records(
            (_transition(), different),
            document,
            digest_factory=lambda _payload: "0" * 64,
        )


def test_evidence_builder_detects_source_span_digest_collisions() -> None:
    document = _document("Q1. Continue to Q2.", "Q2. Continue to Q3.")
    second_span = _span(
        span_id="second",
        quote="Q2. Continue to Q3.",
        block_id="block-1",
    )
    second = _transition(local_id="second").model_copy(update={"source_span": second_span})

    with pytest.raises(IdentityCollisionError, match="source span"):
        build_evidence_records(
            (_transition(), second),
            document,
            digest_factory=lambda _payload: "0" * 64,
        )
