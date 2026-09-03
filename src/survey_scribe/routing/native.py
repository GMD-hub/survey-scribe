"""Typed native-routing boundary and deterministic graph preparation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictInt, model_validator

from survey_scribe.models.routing import (
    Containment,
    InventoryItem,
    RepeatKind,
    RepeatSpec,
    RoutingNode,
    TerminalKind,
)
from survey_scribe.models.svis import SurveySVIS
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
    NonEmptyStr,
    SourceSpan,
    StrictRoutingModel,
    TransitionEvidence,
    TransitionKind,
)
from survey_scribe.routing.identity import (
    IdentityResolver,
    VerifiedEvidence,
    build_evidence_records,
    resolve_extracted_condition,
)
from survey_scribe.routing.inventory import (
    InventoryBuildResult,
    InventoryItemExtraction,
    build_inventory,
)
from survey_scribe.sources.base import SourceDocument

NonNegativeInt = Annotated[StrictInt, Field(ge=0)]


class NativeSourceExpression(StrictRoutingModel):
    """Exact native syntax and its source-reference projection before identity resolution."""

    language: NonEmptyStr
    version: NonEmptyStr
    exact_expression: NonEmptyStr
    references: tuple[ItemReference, ...]
    projection: ExtractedRoutingCondition

    @model_validator(mode="after")
    def validate_references(self) -> NativeSourceExpression:
        if len(set(self.references)) != len(self.references):
            raise ValueError("native source expression references must be unique")
        return self


class NativeRoutingItem(StrictRoutingModel):
    """One native logical item; repeated records remain one logical template."""

    local_id: NonEmptyStr
    source_item_id: NonEmptyStr | None
    raw_reference: NonEmptyStr
    label: NonEmptyStr
    section_path: tuple[NonEmptyStr, ...]
    source_order: NonNegativeInt
    block_ids: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    kind: NodeKind
    parent_local_id: NonEmptyStr | None
    repeat_group_local_id: NonEmptyStr | None
    is_entry: StrictBool
    linked_variable_names: tuple[NonEmptyStr, ...]
    source_text: NonEmptyStr
    terminal_kind: TerminalKind | None
    repeat_kind: RepeatKind | None

    @model_validator(mode="after")
    def validate_item_shape(self) -> NativeRoutingItem:
        if len(set(self.block_ids)) != len(self.block_ids):
            raise ValueError("native item block identifiers must be unique")
        if len(set(self.linked_variable_names)) != len(self.linked_variable_names):
            raise ValueError("native item variable names must be unique")
        if (self.kind is NodeKind.terminal) != (self.terminal_kind is not None):
            raise ValueError("native terminal kind is required only for terminal items")
        if (self.kind is NodeKind.repeat_group) != (self.repeat_kind is not None):
            raise ValueError("native repeat kind is required only for repeat-group items")
        if self.linked_variable_names and self.kind is not NodeKind.question:
            raise ValueError("only native question items can link to variables")
        return self


class NativeTransition(StrictRoutingModel):
    """One source-ordered native flow fact."""

    local_id: NonEmptyStr
    source_local_id: NonEmptyStr
    target_local_id: NonEmptyStr
    transition_kind: TransitionKind
    expression: NativeSourceExpression | None
    source_span: SourceSpan
    explicitly_stated: StrictBool = True
    priority: NonNegativeInt | None = None

    @model_validator(mode="after")
    def validate_transition_shape(self) -> NativeTransition:
        if (self.transition_kind is TransitionKind.conditional) != (self.expression is not None):
            raise ValueError("only conditional native transitions have source expressions")
        if self.priority is not None and self.transition_kind not in {
            TransitionKind.conditional,
            TransitionKind.default,
        }:
            raise ValueError("native priority is valid only for conditional or default flow")
        return self


class NativeActivation(StrictRoutingModel):
    """One native applicability expression kept separate from transitions."""

    local_id: NonEmptyStr
    item_local_id: NonEmptyStr
    expression: NativeSourceExpression
    source_span: SourceSpan


class NativeSourceRecord(StrictRoutingModel):
    """One immutable source row retained without formula evaluation."""

    collection: Literal["survey", "choices", "settings", "external_choices"]
    source_order: NonNegativeInt
    values: tuple[tuple[NonEmptyStr, str], ...]

    @model_validator(mode="after")
    def validate_record_keys(self) -> NativeSourceRecord:
        keys = tuple(key for key, _value in self.values)
        if len(set(keys)) != len(keys):
            raise ValueError("native source record keys must be unique")
        return self


class NativeRoutingDiagnostic(StrictRoutingModel):
    """Safe native-adapter diagnostic without source prose."""

    code: NonEmptyStr
    severity: Literal["warning", "error"] = "warning"


class NativeRoutingSemantics(StrictRoutingModel):
    """Complete typed native item, flow, applicability, and preserved-row payload."""

    schema_version: Literal["1.0"]
    adapter: NonEmptyStr
    complete: StrictBool
    items: tuple[NativeRoutingItem, ...]
    transitions: tuple[NativeTransition, ...]
    activations: tuple[NativeActivation, ...]
    records: tuple[NativeSourceRecord, ...]
    diagnostics: tuple[NativeRoutingDiagnostic, ...]

    @model_validator(mode="after")
    def validate_native_references(self) -> NativeRoutingSemantics:
        item_ids = tuple(item.local_id for item in self.items)
        if len(set(item_ids)) != len(item_ids):
            raise ValueError("native item local identifiers must be unique")
        local_ids = set(item_ids)
        fact_ids = tuple(item.local_id for item in self.transitions) + tuple(
            item.local_id for item in self.activations
        )
        if len(set(fact_ids)) != len(fact_ids):
            raise ValueError("native fact local identifiers must be unique")
        if any(
            transition.source_local_id not in local_ids
            or transition.target_local_id not in local_ids
            for transition in self.transitions
        ):
            raise ValueError("native transition endpoints must identify native items")
        if any(activation.item_local_id not in local_ids for activation in self.activations):
            raise ValueError("native activation items must identify native items")
        return self


@dataclass(frozen=True, slots=True)
class PreparedNativeRouting:
    """Canonical inventory, empty-index nodes, and verified native evidence."""

    inventory: InventoryBuildResult
    nodes: tuple[RoutingNode, ...]
    entry_node_ids: tuple[str, ...]
    evidence: VerifiedEvidence
    source_priorities: Mapping[str, int]


def prepare_native_routing(
    semantics: NativeRoutingSemantics,
    document: SourceDocument,
    svis: SurveySVIS,
) -> PreparedNativeRouting:
    """Resolve native logical facts against one deterministic canonical inventory."""
    variables_by_name: dict[str, list[int]] = {}
    for index, variable in enumerate(svis.variables):
        variables_by_name.setdefault(variable.raw_name, []).append(index)
    extracted = tuple(
        InventoryItemExtraction(
            local_id=item.local_id,
            source_item_id=item.source_item_id,
            raw_reference=item.raw_reference,
            section_path=item.section_path,
            source_order=item.source_order,
            block_ids=item.block_ids,
            kind=item.kind,
            parent_local_id=item.parent_local_id,
            repeat_group_local_id=item.repeat_group_local_id,
            is_entry=item.is_entry,
            linked_variable_indices=tuple(
                index
                for name in item.linked_variable_names
                for index in variables_by_name.get(name, ())
            ),
            source_text=item.source_text,
            suggested_node_id=None,
        )
        for item in semantics.items
    )
    inventory = build_inventory(document, svis, extracted)
    native_by_local = {item.local_id: item for item in semantics.items}
    canonical_by_local = {
        source.local_id: canonical
        for source, canonical in zip(
            sorted(semantics.items, key=lambda item: item.source_order),
            inventory.items,
            strict=True,
        )
    }
    nodes = _build_nodes(inventory, native_by_local, canonical_by_local, svis)
    resolver = IdentityResolver(inventory.items)
    observations = []
    priorities: dict[str, int] = {}
    for transition in semantics.transitions:
        source_item = native_by_local[transition.source_local_id]
        target_item = native_by_local[transition.target_local_id]
        expression = _native_expression(transition.expression, resolver, source_item.section_path)
        observation = TransitionEvidence(
            evidence_type="transition",
            local_id=transition.local_id,
            perspective=EvidencePerspective.outgoing,
            origin=EvidenceOrigin.native_parser,
            source=_item_reference(source_item),
            target=_item_reference(target_item),
            transition_kind=transition.transition_kind,
            condition=(
                transition.expression.projection if transition.expression is not None else None
            ),
            source_span=transition.source_span,
            native_expression=expression or _always_expression(transition.source_span.source_quote),
            explicitly_stated=transition.explicitly_stated,
            confidence=1.0,
            ambiguity_note=None,
        )
        observations.append(observation)
    for activation in semantics.activations:
        item = native_by_local[activation.item_local_id]
        observations.append(
            ActivationEvidence(
                evidence_type="activation",
                local_id=activation.local_id,
                origin=EvidenceOrigin.native_parser,
                item=_item_reference(item),
                condition=activation.expression.projection,
                source_span=activation.source_span,
                native_expression=_native_expression(
                    activation.expression,
                    resolver,
                    item.section_path,
                ),
                explicitly_stated=True,
                confidence=1.0,
                ambiguity_note=None,
            )
        )
    evidence = build_evidence_records(observations, document)
    evidence_by_local = {
        record.observation.local_id: record.evidence_id for record in evidence.records
    }
    for transition in semantics.transitions:
        if transition.priority is not None:
            priorities[evidence_by_local[transition.local_id]] = transition.priority
    return PreparedNativeRouting(
        inventory=inventory,
        nodes=nodes,
        entry_node_ids=tuple(
            canonical_by_local[item.local_id].node_id
            for item in semantics.items
            if item.kind is NodeKind.entry
        ),
        evidence=evidence,
        source_priorities=priorities,
    )


def _build_nodes(
    inventory: InventoryBuildResult,
    native_by_local: Mapping[str, NativeRoutingItem],
    canonical_by_local: Mapping[str, InventoryItem],
    svis: SurveySVIS,
) -> tuple[RoutingNode, ...]:
    native_by_node = {
        canonical_by_local[local_id].node_id: item for local_id, item in native_by_local.items()
    }
    children: dict[str, list[str]] = {item.node_id: [] for item in inventory.items}
    for item in inventory.items:
        if item.parent_node_id is not None:
            children[item.parent_node_id].append(item.node_id)
    entries = dict(inventory.group_entries)
    variables = tuple(svis.variables)
    nodes: list[RoutingNode] = []
    for canonical in inventory.items:
        native = native_by_node[canonical.node_id]
        linked = tuple(variables[index] for index in canonical.linked_variable_indices)
        raw_name = linked[0].raw_name if linked and canonical.kind is NodeKind.question else None
        repeat_spec = (
            RepeatSpec(
                repeat_kind=native.repeat_kind,
                iterator_label=native.label,
                collection_source=None,
                continuation_condition=None,
                maximum_iterations=None,
            )
            if native.repeat_kind is not None
            else None
        )
        nodes.append(
            RoutingNode(
                node_id=canonical.node_id,
                kind=canonical.kind,
                source_item_id=canonical.source_item_id,
                raw_name=raw_name,
                label=native.label,
                terminal_kind=native.terminal_kind,
                activation_condition=None,
                repeat_spec=repeat_spec,
                containment=Containment(
                    parent_node_id=canonical.parent_node_id,
                    child_node_ids=tuple(children[canonical.node_id]),
                    entry_child_node_id=entries.get(canonical.node_id),
                ),
                next_node_ids=(),
                previous_node_ids=(),
                outgoing_edge_ids=(),
                incoming_edge_ids=(),
            )
        )
    return tuple(nodes)


def _native_expression(
    expression: NativeSourceExpression | None,
    resolver: IdentityResolver,
    default_section_path: tuple[str, ...],
) -> NativeExpression | None:
    if expression is None:
        return None
    resolution = resolve_extracted_condition(
        expression.projection,
        resolver,
        default_section_path=default_section_path,
    )
    canonical = resolution.condition
    if canonical is None:
        canonical = CanonicalRoutingCondition(
            operator=ConditionOperator.opaque,
            question_node_id=None,
            value=None,
            values=None,
            children=None,
            raw_text=expression.exact_expression,
        )
    return NativeExpression(
        language=expression.language,
        version=expression.version,
        exact_expression=expression.exact_expression,
        parsed_references=expression.references,
        canonical_projection=canonical,
    )


def _always_expression(raw_text: str) -> NativeExpression:
    return NativeExpression(
        language="native-order",
        version="1.0",
        exact_expression=raw_text,
        parsed_references=(),
        canonical_projection=CanonicalRoutingCondition(
            operator=ConditionOperator.always,
            question_node_id=None,
            value=None,
            values=None,
            children=None,
            raw_text=raw_text,
        ),
    )


def _item_reference(item: NativeRoutingItem) -> ItemReference:
    return ItemReference(
        raw_reference=item.raw_reference,
        source_item_id=item.source_item_id,
        canonical_hint=None,
        section_path=item.section_path,
        node_kind=item.kind,
    )


__all__ = [
    "NativeActivation",
    "NativeRoutingDiagnostic",
    "NativeRoutingItem",
    "NativeRoutingSemantics",
    "NativeSourceExpression",
    "NativeSourceRecord",
    "NativeTransition",
    "PreparedNativeRouting",
    "prepare_native_routing",
]
