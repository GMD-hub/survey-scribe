"""Strict provider-facing contracts for questionnaire routing extraction."""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Annotated, Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    model_validator,
)

NonEmptyStr = Annotated[StrictStr, Field(min_length=1)]
FiniteFloat = Annotated[StrictFloat, Field(allow_inf_nan=False)]
Confidence = Annotated[
    StrictFloat,
    Field(ge=0.0, le=1.0, allow_inf_nan=False),
]
PositiveInt = Annotated[StrictInt, Field(ge=1)]
RoutingScalar: TypeAlias = StrictStr | StrictInt | FiniteFloat | StrictBool
ItemReferenceKey: TypeAlias = tuple[tuple[str, ...], str, "NodeKind"]

MAX_CONDITION_DEPTH = 6
MAX_CONDITION_NODES = 100
MAX_SOURCE_QUOTE_CHARS = 2_000


class StrictRoutingModel(BaseModel):
    """Immutable base for every routing boundary model."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class NodeKind(str, Enum):
    """Logical role of a canonical questionnaire node."""

    entry = "entry"
    question = "question"
    section = "section"
    repeat_group = "repeat_group"
    terminal = "terminal"


class ConditionOperator(str, Enum):
    """Supported routing-condition operations."""

    always = "always"
    equals = "equals"
    not_equals = "not_equals"
    in_set = "in_set"
    not_in_set = "not_in_set"
    greater_than = "greater_than"
    greater_than_or_equal = "greater_than_or_equal"
    less_than = "less_than"
    less_than_or_equal = "less_than_or_equal"
    between = "between"
    answered = "answered"
    not_answered = "not_answered"
    selected = "selected"
    not_selected = "not_selected"
    all = "all"
    any = "any"
    not_ = "not"
    opaque = "opaque"


class EvidencePerspective(str, Enum):
    """Direction from which a transition was independently examined."""

    outgoing = "outgoing"
    incoming = "incoming"


class EvidenceOrigin(str, Enum):
    """Producer of one source-grounded observation."""

    forward_extraction = "forward_extraction"
    incoming_extraction = "incoming_extraction"
    native_parser = "native_parser"


class TransitionKind(str, Enum):
    """Flow semantics available to extraction and canonical edges."""

    conditional = "conditional"
    default = "default"
    unconditional = "unconditional"
    sequential = "sequential"


class RoutingPassKind(str, Enum):
    """Independent extraction pass represented by one batch."""

    forward = "forward"
    incoming_activation = "incoming_activation"


class SourceSpan(StrictRoutingModel):
    """Bounded quote and physical provenance in one normalized source block."""

    span_id: NonEmptyStr
    block_id: NonEmptyStr
    source_name: NonEmptyStr
    pages: tuple[PositiveInt, ...]
    sheet: NonEmptyStr | None
    row_start: PositiveInt | None
    row_end: PositiveInt | None
    source_quote: Annotated[StrictStr, Field(min_length=1, max_length=MAX_SOURCE_QUOTE_CHARS)]

    @model_validator(mode="after")
    def validate_provenance(self) -> SourceSpan:
        if tuple(sorted(set(self.pages))) != self.pages:
            raise ValueError("source span pages must be unique and ordered")
        if (self.row_start is None) != (self.row_end is None):
            raise ValueError("source span row bounds must be provided together")
        if (
            self.row_start is not None
            and self.row_end is not None
            and self.row_end < self.row_start
        ):
            raise ValueError("source span row_end must not precede row_start")
        if self.sheet is None and self.row_start is not None:
            raise ValueError("source span row bounds require a sheet")
        return self


class ItemReference(StrictRoutingModel):
    """Preserved printed or unresolved questionnaire item reference."""

    raw_reference: NonEmptyStr
    source_item_id: NonEmptyStr | None
    canonical_hint: NonEmptyStr | None
    section_path: tuple[NonEmptyStr, ...]
    node_kind: NodeKind

    @property
    def binding_key(self) -> ItemReferenceKey:
        """Return an exact hashable key for caller-supplied reference bindings."""
        identity = self.source_item_id or self.raw_reference
        return self.section_path, identity, self.node_kind


_SCALAR_OPERATORS = frozenset(
    {
        ConditionOperator.equals,
        ConditionOperator.not_equals,
        ConditionOperator.greater_than,
        ConditionOperator.greater_than_or_equal,
        ConditionOperator.less_than,
        ConditionOperator.less_than_or_equal,
        ConditionOperator.selected,
        ConditionOperator.not_selected,
    }
)
_SET_OPERATORS = frozenset({ConditionOperator.in_set, ConditionOperator.not_in_set})
_QUESTION_ONLY_OPERATORS = frozenset({ConditionOperator.answered, ConditionOperator.not_answered})
_BOOLEAN_OPERATORS = frozenset({ConditionOperator.all, ConditionOperator.any})


def _validate_condition_shape(
    *,
    operator: ConditionOperator,
    question: object,
    value: RoutingScalar | None,
    values: tuple[RoutingScalar, ...] | None,
    children: tuple[object, ...] | None,
    raw_text: str,
) -> None:
    has_question = question is not None
    has_value = value is not None
    has_values = values is not None
    has_children = children is not None

    valid = False
    if operator is ConditionOperator.always:
        valid = not (has_question or has_value or has_values or has_children)
    elif operator is ConditionOperator.opaque:
        valid = not (has_question or has_value or has_values or has_children) and bool(
            raw_text.strip()
        )
    elif operator in _SCALAR_OPERATORS:
        valid = has_question and has_value and not has_values and not has_children
    elif operator in _SET_OPERATORS:
        valid = (
            has_question
            and not has_value
            and values is not None
            and bool(values)
            and not has_children
        )
    elif operator is ConditionOperator.between:
        valid = (
            has_question
            and not has_value
            and values is not None
            and len(values) == 2
            and not has_children
        )
    elif operator in _QUESTION_ONLY_OPERATORS:
        valid = has_question and not has_value and not has_values and not has_children
    elif operator in _BOOLEAN_OPERATORS:
        valid = (
            not has_question
            and not has_value
            and not has_values
            and children is not None
            and len(children) >= 2
        )
    elif operator is ConditionOperator.not_:
        valid = (
            not has_question
            and not has_value
            and not has_values
            and children is not None
            and len(children) == 1
        )
    if not valid:
        raise ValueError("condition fields do not match the selected operator")


def _condition_metrics(root: object) -> tuple[int, int]:
    max_depth = 0
    node_count = 0
    stack = [(root, 1)]
    while stack:
        node, depth = stack.pop()
        node_count += 1
        max_depth = max(max_depth, depth)
        children = getattr(node, "children", None)
        if children:
            stack.extend((child, depth + 1) for child in children)
    return max_depth, node_count


def _validate_condition_limits(root: object) -> None:
    depth, node_count = _condition_metrics(root)
    if depth > MAX_CONDITION_DEPTH:
        raise ValueError("condition AST exceeds the maximum depth")
    if node_count > MAX_CONDITION_NODES:
        raise ValueError("condition AST exceeds the maximum nodes")


class ExtractedRoutingCondition(StrictRoutingModel):
    """Condition that preserves an unresolved source item reference."""

    operator: ConditionOperator
    item_reference: ItemReference | None
    value: RoutingScalar | None
    values: tuple[RoutingScalar, ...] | None
    children: tuple[ExtractedRoutingCondition, ...] | None
    raw_text: StrictStr

    @model_validator(mode="after")
    def validate_shape_and_limits(self) -> ExtractedRoutingCondition:
        _validate_condition_shape(
            operator=self.operator,
            question=self.item_reference,
            value=self.value,
            values=self.values,
            children=self.children,
            raw_text=self.raw_text,
        )
        _validate_condition_limits(self)
        return self

    @property
    def ast_depth(self) -> int:
        """Return the validated root-to-leaf depth."""
        return _condition_metrics(self)[0]

    @property
    def ast_node_count(self) -> int:
        """Return the validated number of nodes."""
        return _condition_metrics(self)[1]


class CanonicalRoutingCondition(StrictRoutingModel):
    """Condition whose controlling questions are canonical graph nodes."""

    operator: ConditionOperator
    question_node_id: NonEmptyStr | None
    value: RoutingScalar | None
    values: tuple[RoutingScalar, ...] | None
    children: tuple[CanonicalRoutingCondition, ...] | None
    raw_text: StrictStr

    @model_validator(mode="after")
    def validate_shape_and_limits(self) -> CanonicalRoutingCondition:
        _validate_condition_shape(
            operator=self.operator,
            question=self.question_node_id,
            value=self.value,
            values=self.values,
            children=self.children,
            raw_text=self.raw_text,
        )
        _validate_condition_limits(self)
        return self

    @property
    def ast_depth(self) -> int:
        """Return the validated root-to-leaf depth."""
        return _condition_metrics(self)[0]

    @property
    def ast_node_count(self) -> int:
        """Return the validated number of nodes."""
        return _condition_metrics(self)[1]


def project_extracted_condition(
    condition: ExtractedRoutingCondition,
    resolved_references: Mapping[ItemReferenceKey, str],
) -> CanonicalRoutingCondition:
    """Project through caller-supplied exact bindings without resolving identities."""
    question_node_id: str | None = None
    if condition.item_reference is not None:
        question_node_id = resolved_references.get(condition.item_reference.binding_key)
        if not question_node_id:
            raise ValueError("condition requires one supplied resolved reference")
    children = (
        tuple(
            project_extracted_condition(child, resolved_references) for child in condition.children
        )
        if condition.children is not None
        else None
    )
    return CanonicalRoutingCondition(
        operator=condition.operator,
        question_node_id=question_node_id,
        value=condition.value,
        values=condition.values,
        children=children,
        raw_text=condition.raw_text,
    )


class NativeExpression(StrictRoutingModel):
    """Exact native syntax plus its bounded canonical projection."""

    language: NonEmptyStr
    version: NonEmptyStr
    exact_expression: NonEmptyStr
    parsed_references: tuple[ItemReference, ...]
    canonical_projection: CanonicalRoutingCondition

    @model_validator(mode="after")
    def validate_unique_references(self) -> NativeExpression:
        if len(set(self.parsed_references)) != len(self.parsed_references):
            raise ValueError("native parsed references must be unique")
        return self


class TransitionEvidence(StrictRoutingModel):
    """One provider-facing observation of movement through the questionnaire."""

    evidence_type: Literal["transition"]
    local_id: NonEmptyStr
    perspective: EvidencePerspective
    origin: EvidenceOrigin
    source: ItemReference
    target: ItemReference
    transition_kind: TransitionKind
    condition: ExtractedRoutingCondition | None
    source_span: SourceSpan
    native_expression: NativeExpression | None
    explicitly_stated: StrictBool
    confidence: Confidence
    ambiguity_note: StrictStr | None

    @model_validator(mode="after")
    def validate_transition_shape(self) -> TransitionEvidence:
        if (self.transition_kind is TransitionKind.conditional) != (self.condition is not None):
            raise ValueError("only conditional transition evidence has a condition")
        _validate_native_origin(self.origin, self.native_expression)
        if self.origin is EvidenceOrigin.forward_extraction:
            if self.perspective is not EvidencePerspective.outgoing:
                raise ValueError("forward evidence must use the outgoing perspective")
        elif self.origin is EvidenceOrigin.incoming_extraction:
            if self.perspective is not EvidencePerspective.incoming:
                raise ValueError("incoming evidence must use the incoming perspective")
        elif self.perspective is not EvidencePerspective.outgoing:
            raise ValueError("native evidence must use the outgoing perspective")
        return self


class ActivationEvidence(StrictRoutingModel):
    """One provider-facing observation of item or group applicability."""

    evidence_type: Literal["activation"]
    local_id: NonEmptyStr
    origin: EvidenceOrigin
    item: ItemReference
    condition: ExtractedRoutingCondition
    source_span: SourceSpan
    native_expression: NativeExpression | None
    explicitly_stated: StrictBool
    confidence: Confidence
    ambiguity_note: StrictStr | None

    @model_validator(mode="after")
    def validate_activation_origin(self) -> ActivationEvidence:
        _validate_native_origin(self.origin, self.native_expression)
        return self


def _validate_native_origin(
    origin: EvidenceOrigin,
    native_expression: NativeExpression | None,
) -> None:
    if (origin is EvidenceOrigin.native_parser) != (native_expression is not None):
        raise ValueError("native evidence origin and native expression must occur together")


EvidenceObservation: TypeAlias = Annotated[
    TransitionEvidence | ActivationEvidence,
    Field(discriminator="evidence_type"),
]


class RoutingEvidenceBatch(StrictRoutingModel):
    """Complete strict response for one independent provider extraction pass."""

    chunk_id: NonEmptyStr
    pass_kind: RoutingPassKind
    examined_item_ids: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    evidence: tuple[EvidenceObservation, ...]
    unresolved_references: tuple[ItemReference, ...]
    notes: tuple[StrictStr, ...]

    @model_validator(mode="after")
    def validate_batch(self) -> RoutingEvidenceBatch:
        if len(set(self.examined_item_ids)) != len(self.examined_item_ids):
            raise ValueError("examined item identifiers must be unique")
        local_ids = tuple(item.local_id for item in self.evidence)
        if len(set(local_ids)) != len(local_ids):
            raise ValueError("evidence local identifiers must be unique")
        if self.pass_kind is RoutingPassKind.forward:
            if any(isinstance(item, ActivationEvidence) for item in self.evidence):
                raise ValueError("forward extraction cannot contain activation evidence")
            if any(item.origin is not EvidenceOrigin.forward_extraction for item in self.evidence):
                raise ValueError("forward extraction requires forward evidence origin")
        elif any(item.origin is not EvidenceOrigin.incoming_extraction for item in self.evidence):
            raise ValueError("incoming extraction requires incoming evidence origin")
        return self


__all__ = [
    "ActivationEvidence",
    "CanonicalRoutingCondition",
    "ConditionOperator",
    "EvidenceObservation",
    "EvidenceOrigin",
    "EvidencePerspective",
    "ExtractedRoutingCondition",
    "ItemReference",
    "NativeExpression",
    "NodeKind",
    "RoutingEvidenceBatch",
    "RoutingPassKind",
    "RoutingScalar",
    "SourceSpan",
    "StrictRoutingModel",
    "TransitionEvidence",
    "TransitionKind",
    "project_extracted_condition",
]
