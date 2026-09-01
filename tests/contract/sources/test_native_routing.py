"""Additive source conversion and synthetic native-routing contracts."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from survey_scribe.models.routing import RepeatKind, TerminalKind
from survey_scribe.models.svis import DataType, SurveySVIS, SurveyVariable
from survey_scribe.routing.contracts import (
    ConditionOperator,
    ExtractedRoutingCondition,
    ItemReference,
    NodeKind,
    SourceSpan,
    TransitionKind,
)
from survey_scribe.routing.native import (
    NativeActivation,
    NativeRoutingItem,
    NativeRoutingSemantics,
    NativeSourceExpression,
    NativeSourceRecord,
    NativeTransition,
    prepare_native_routing,
)
from survey_scribe.sources.base import (
    ResolvedSource,
    SourceBlock,
    SourceBundle,
    SourceDocument,
    SourceLimits,
    SourceProvenance,
)
from survey_scribe.sources.registry import SourceConversionResult, SourceRegistry


def _svis(source_name: str) -> SurveySVIS:
    return SurveySVIS(
        survey_id="TST_2026_NATIVE",
        country_code="TST",
        year=2026,
        survey_name="Synthetic native survey",
        variables=[
            SurveyVariable(
                raw_name="age",
                question_text="How old are you?",
                data_type=DataType.numeric,
                extraction_confidence=1.0,
            )
        ],
        source_file=source_name,
        source_format="application/x-synthetic-native",
        extraction_date=date(2026, 9, 1),
    )


class SyntheticNativeAdapter:
    """Native-capable adapter used to prove the additive registry contract."""

    def __init__(self) -> None:
        self.convert_calls = 0
        self.native_calls = 0

    def convert(self, source: ResolvedSource, *, limits: SourceLimits) -> SourceDocument:
        del limits
        self.convert_calls += 1
        provenance = SourceProvenance(source_name=source.primary.name)
        return SourceDocument(
            source_name=source.primary.name,
            media_type="application/x-synthetic-native",
            blocks=(
                SourceBlock(
                    id="block-000001",
                    order=0,
                    kind="text",
                    text="Q1 age",
                    provenance=provenance,
                ),
            ),
        )

    def convert_native(
        self,
        source: ResolvedSource,
        document: SourceDocument,
        *,
        limits: SourceLimits,
    ) -> NativeRoutingSemantics:
        del source, limits
        self.native_calls += 1
        return NativeRoutingSemantics(
            schema_version="1.0",
            adapter="synthetic-native/v1",
            complete=True,
            items=(
                NativeRoutingItem(
                    local_id="q1",
                    source_item_id="Q1",
                    raw_reference="Q1",
                    label="Age",
                    section_path=(),
                    source_order=0,
                    block_ids=(document.blocks[0].id,),
                    kind=NodeKind.question,
                    parent_local_id=None,
                    repeat_group_local_id=None,
                    is_entry=False,
                    linked_variable_names=("age",),
                    source_text="Q1 age",
                    terminal_kind=None,
                    repeat_kind=None,
                ),
            ),
            transitions=(),
            activations=(),
            records=(),
            diagnostics=(),
        )


def test_convert_remains_document_only_and_additive_result_contains_binding_and_native(
    tmp_path: Path,
) -> None:
    source = tmp_path / "questionnaire.native"
    source.write_text("Q1 age", encoding="utf-8")
    adapter = SyntheticNativeAdapter()
    registry = SourceRegistry({".native": adapter})

    legacy = registry.convert(source)

    assert type(legacy) is SourceDocument
    assert legacy.source_name == source.name
    assert adapter.convert_calls == 1
    assert adapter.native_calls == 0

    converted = registry.convert_with_native(source, _svis(source.name))

    assert type(converted) is SourceConversionResult
    assert type(converted.document) is SourceDocument
    assert converted.source_binding.survey_id == "TST_2026_NATIVE"
    assert converted.source_binding.source_name == source.name
    assert converted.source_binding.media_type == "application/x-synthetic-native"
    assert converted.source_binding.snapshot_sha256 == converted.document.snapshot_sha256
    assert converted.source_binding.source_conversion_schema_version == "1.0"
    assert converted.native is not None
    assert converted.native.adapter == "synthetic-native/v1"
    assert adapter.convert_calls == 2
    assert adapter.native_calls == 1


def test_non_native_adapter_returns_the_same_document_and_no_native_semantics(
    tmp_path: Path,
) -> None:
    source = tmp_path / "questionnaire.native"
    source.write_text("Q1 age", encoding="utf-8")
    native_adapter = SyntheticNativeAdapter()

    class DocumentOnlyAdapter:
        def convert(self, source: ResolvedSource, *, limits: SourceLimits) -> SourceDocument:
            return native_adapter.convert(source, limits=limits)

    registry = SourceRegistry({".native": DocumentOnlyAdapter()})
    converted = registry.convert_with_native(source, _svis(source.name))

    assert converted.native is None
    assert converted.document.snapshot_sha256 == converted.source_binding.snapshot_sha256


def test_routed_source_binding_frames_ordered_primary_and_companion_digests(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "questionnaire.native"
    first = tmp_path / "first.csv"
    renamed = tmp_path / "renamed.csv"
    second = tmp_path / "second.csv"
    primary.write_text("Q1 age", encoding="utf-8")
    first.write_text("first", encoding="utf-8")
    renamed.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")
    registry = SourceRegistry({".native": SyntheticNativeAdapter()})

    def digest(*companions: Path) -> str:
        converted = registry.convert_with_native(
            SourceBundle(
                root=tmp_path,
                primary=Path(primary.name),
                companions=tuple(Path(item.name) for item in companions),
            ),
            _svis(primary.name),
        )
        assert converted.document.snapshot_sha256 == converted.source_binding.snapshot_sha256
        return converted.source_binding.snapshot_sha256

    no_companion = digest()
    first_only = digest(first)
    renamed_only = digest(renamed)
    both = digest(first, second)
    reordered = digest(second, first)
    first.write_text("first changed", encoding="utf-8")
    mutated = digest(first, second)

    assert len({no_companion, first_only, renamed_only, both, reordered, mutated}) == 6


def _reference(name: str = "Q1") -> ItemReference:
    return ItemReference(
        raw_reference=name,
        source_item_id=name,
        canonical_hint=None,
        section_path=(),
        node_kind=NodeKind.question,
    )


def _expression(name: str = "Q1") -> NativeSourceExpression:
    reference = _reference(name)
    return NativeSourceExpression(
        language="synthetic",
        version="1.0",
        exact_expression=f"${{{name}}} = 1",
        references=(reference,),
        projection=ExtractedRoutingCondition(
            operator=ConditionOperator.equals,
            item_reference=reference,
            value=1,
            values=None,
            children=None,
            raw_text=f"${{{name}}} = 1",
        ),
    )


def _span() -> SourceSpan:
    return SourceSpan(
        span_id="temporary",
        block_id="block-000001",
        source_name="questionnaire.native",
        pages=(),
        sheet=None,
        row_start=None,
        row_end=None,
        source_quote="Q1 age",
    )


def _item_payload(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "local_id": "q1",
        "source_item_id": "Q1",
        "raw_reference": "Q1",
        "label": "Age",
        "section_path": (),
        "source_order": 0,
        "block_ids": ("block-000001",),
        "kind": NodeKind.question,
        "parent_local_id": None,
        "repeat_group_local_id": None,
        "is_entry": False,
        "linked_variable_names": ("age",),
        "source_text": "Q1 age",
        "terminal_kind": None,
        "repeat_kind": None,
    }
    payload.update(changes)
    return payload


@pytest.mark.parametrize(
    "changes",
    (
        {"block_ids": ("block-000001", "block-000001")},
        {"linked_variable_names": ("age", "age")},
        {"terminal_kind": TerminalKind.survey_complete},
        {"kind": NodeKind.terminal, "terminal_kind": None},
        {"repeat_kind": RepeatKind.other},
        {"kind": NodeKind.repeat_group, "repeat_kind": None, "linked_variable_names": ()},
        {"kind": NodeKind.section},
    ),
)
def test_native_item_rejects_inconsistent_shapes(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        NativeRoutingItem.model_validate(_item_payload(**changes))


def test_native_expression_transition_record_and_semantics_invariants() -> None:
    expression = _expression()
    with pytest.raises(ValidationError, match="references must be unique"):
        NativeSourceExpression.model_validate(
            expression.model_dump(mode="python") | {"references": (expression.references[0],) * 2}
        )
    with pytest.raises(ValidationError, match="only conditional"):
        NativeTransition(
            local_id="transition",
            source_local_id="q1",
            target_local_id="q2",
            transition_kind=TransitionKind.sequential,
            expression=expression,
            source_span=_span(),
        )
    with pytest.raises(ValidationError, match="priority"):
        NativeTransition(
            local_id="transition",
            source_local_id="q1",
            target_local_id="q2",
            transition_kind=TransitionKind.sequential,
            expression=None,
            source_span=_span(),
            priority=1,
        )
    with pytest.raises(ValidationError, match="keys must be unique"):
        NativeSourceRecord(
            collection="survey",
            source_order=0,
            values=(("name", "q1"), ("name", "q2")),
        )

    q1 = NativeRoutingItem.model_validate(_item_payload())
    q2 = NativeRoutingItem.model_validate(
        _item_payload(
            local_id="q2",
            source_item_id="Q2",
            raw_reference="Q2",
            source_order=1,
            linked_variable_names=(),
        )
    )
    transition = NativeTransition(
        local_id="fact",
        source_local_id="q1",
        target_local_id="q2",
        transition_kind=TransitionKind.conditional,
        expression=expression,
        source_span=_span(),
    )
    activation = NativeActivation(
        local_id="activation",
        item_local_id="q1",
        expression=expression,
        source_span=_span(),
    )
    base = {
        "schema_version": "1.0",
        "adapter": "synthetic/v1",
        "complete": True,
        "items": (q1, q2),
        "transitions": (transition,),
        "activations": (activation,),
        "records": (),
        "diagnostics": (),
    }
    for changes in (
        {"items": (q1, q1)},
        {"activations": (activation.model_copy(update={"local_id": "fact"}),)},
        {"transitions": (transition.model_copy(update={"target_local_id": "missing"}),)},
        {"activations": (activation.model_copy(update={"item_local_id": "missing"}),)},
    ):
        with pytest.raises(ValidationError):
            NativeRoutingSemantics.model_validate(base | changes)


def test_prepare_native_routing_keeps_priority_and_unresolved_projection_opaque(
    tmp_path: Path,
) -> None:
    source = tmp_path / "questionnaire.native"
    source.write_text("Q1 age", encoding="utf-8")
    adapter = SyntheticNativeAdapter()
    converted = SourceRegistry({".native": adapter}).convert_with_native(
        source,
        _svis(source.name),
    )
    assert converted.native is not None
    q1 = converted.native.items[0]
    terminal = NativeRoutingItem.model_validate(
        _item_payload(
            local_id="terminal",
            source_item_id=None,
            raw_reference="complete",
            label="Complete",
            source_order=1,
            kind=NodeKind.terminal,
            linked_variable_names=(),
            terminal_kind=TerminalKind.survey_complete,
        )
    )
    unresolved = _expression("UNKNOWN")
    transition = NativeTransition(
        local_id="conditional",
        source_local_id=q1.local_id,
        target_local_id=terminal.local_id,
        transition_kind=TransitionKind.conditional,
        expression=unresolved,
        source_span=_span(),
        priority=2,
    )
    semantics = NativeRoutingSemantics(
        schema_version="1.0",
        adapter="synthetic/v1",
        complete=True,
        items=(q1, terminal),
        transitions=(transition,),
        activations=(),
        records=(),
        diagnostics=(),
    )

    prepared = prepare_native_routing(semantics, converted.document, _svis(source.name))

    record = prepared.evidence.records[0]
    assert record.observation.native_expression is not None
    assert (
        record.observation.native_expression.canonical_projection.operator
        is ConditionOperator.opaque
    )
    assert prepared.source_priorities == {record.evidence_id: 2}


def test_additive_registry_rejects_unsupported_suffix(tmp_path: Path) -> None:
    path = tmp_path / "questionnaire.unknown"
    path.write_text("Q1", encoding="utf-8")
    with pytest.raises(Exception, match="Unsupported source format"):
        SourceRegistry({}).convert_with_native(path, _svis(path.name))
