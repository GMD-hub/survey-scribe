"""Immutable public models for routed questionnaire SVIS artifacts."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping, Set
from enum import Enum
from typing import Annotated, Literal, TypeAlias, TypeVar

from pydantic import (
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from survey_scribe.models.svis import (
    AnswerCategory,
    NumericRange,
    SurveySVIS,
    SurveyVariable,
)
from survey_scribe.routing.contracts import (
    CanonicalRoutingCondition,
    Confidence,
    EvidenceObservation,
    ExtractedRoutingCondition,
    FiniteFloat,
    ItemReference,
    NodeKind,
    NonEmptyStr,
    PositiveInt,
    SourceSpan,
    StrictRoutingModel,
    TransitionEvidence,
    project_extracted_condition,
)
from survey_scribe.routing.normalization import (
    normalize_section_path_value,
    normalized_alias_value,
)

NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
Sha256 = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
RoutingSchemaVersion: TypeAlias = Literal["1.0"]


class TerminalKind(str, Enum):
    """Meaning of a terminal flow state."""

    survey_complete = "survey_complete"
    screened_out = "screened_out"
    interview_terminated = "interview_terminated"
    unknown_terminal = "unknown_terminal"


class EdgeKind(str, Enum):
    """Accepted questionnaire flow semantics."""

    conditional = "conditional"
    default = "default"
    unconditional = "unconditional"
    sequential = "sequential"


class CandidateStatus(str, Enum):
    """Current audit state of a non-authoritative edge candidate."""

    proposed = "proposed"
    needs_agent_review = "needs_agent_review"
    needs_human_review = "needs_human_review"
    accepted = "accepted"
    rejected = "rejected"


class RepeatKind(str, Enum):
    """Logical template represented by a repeat group."""

    household_member = "household_member"
    consumption_item = "consumption_item"
    visit = "visit"
    plot = "plot"
    enterprise = "enterprise"
    until_condition = "until_condition"
    other = "other"


class LoopKind(str, Enum):
    """Supported topological or declared loop classification."""

    repeat_group = "repeat_group"
    correction_return = "correction_return"
    repeat_until = "repeat_until"
    other = "other"


class DiagnosticSeverity(str, Enum):
    """Stable routing diagnostic severity."""

    info = "info"
    warning = "warning"
    error = "error"


class DiscrepancyKind(str, Enum):
    """Bounded discrepancy categories available to review."""

    conflicting_target = "conflicting_target"
    conflicting_condition = "conflicting_condition"
    ambiguous_target = "ambiguous_target"
    unresolved_target = "unresolved_target"
    multiple_defaults = "multiple_defaults"
    incoming_mismatch = "incoming_mismatch"
    opaque_condition = "opaque_condition"
    unsupported_cycle = "unsupported_cycle"
    activation_routing_conflict = "activation_routing_conflict"
    other = "other"


class ReviewAction(str, Enum):
    """Append-only reviewer action."""

    confirm_candidate = "confirm_candidate"
    replace_candidate = "replace_candidate"
    reject_candidate = "reject_candidate"
    unresolved = "unresolved"


class RoutingSourceBinding(StrictRoutingModel):
    """Identity of the validated private source snapshot used for routing."""

    survey_id: NonEmptyStr
    source_name: NonEmptyStr
    media_type: NonEmptyStr
    snapshot_sha256: Sha256
    source_conversion_schema_version: NonEmptyStr


class InventoryItem(StrictRoutingModel):
    """One complete logical questionnaire item before reconciliation."""

    node_id: NonEmptyStr
    source_item_id: NonEmptyStr | None
    raw_reference: NonEmptyStr
    section_path: tuple[NonEmptyStr, ...]
    source_order: NonNegativeInt
    block_ids: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    kind: NodeKind
    repeat_group_node_id: NonEmptyStr | None
    parent_node_id: NonEmptyStr | None
    linked_variable_indices: tuple[NonNegativeInt, ...]

    @model_validator(mode="after")
    def validate_inventory_item(self) -> InventoryItem:
        _require_unique(self.block_ids, "inventory block identifiers")
        _require_unique(self.linked_variable_indices, "linked variable indices")
        if self.repeat_group_node_id == self.node_id or self.parent_node_id == self.node_id:
            raise ValueError("inventory item cannot contain itself")
        return self


class RepeatSpec(StrictRoutingModel):
    """Logical repeat template without runtime unrolling."""

    repeat_kind: RepeatKind
    iterator_label: NonEmptyStr
    collection_source: NonEmptyStr | None
    continuation_condition: CanonicalRoutingCondition | None
    maximum_iterations: PositiveInt | None


class Containment(StrictRoutingModel):
    """Parent relation plus derived stable children and explicit group entry."""

    parent_node_id: NonEmptyStr | None
    child_node_ids: tuple[NonEmptyStr, ...]
    entry_child_node_id: NonEmptyStr | None

    @model_validator(mode="after")
    def validate_containment(self) -> Containment:
        _require_unique(self.child_node_ids, "containment child identifiers")
        if (
            self.entry_child_node_id is not None
            and self.entry_child_node_id not in self.child_node_ids
        ):
            raise ValueError("containment entry child must be one of the derived children")
        return self


class RoutingNode(StrictRoutingModel):
    """One canonical logical node with accepted-edge adjacency projections."""

    node_id: NonEmptyStr
    kind: NodeKind
    source_item_id: NonEmptyStr | None
    raw_name: NonEmptyStr | None
    label: NonEmptyStr
    terminal_kind: TerminalKind | None
    activation_condition: CanonicalRoutingCondition | None
    repeat_spec: RepeatSpec | None
    containment: Containment
    next_node_ids: tuple[NonEmptyStr, ...]
    previous_node_ids: tuple[NonEmptyStr, ...]
    outgoing_edge_ids: tuple[NonEmptyStr, ...]
    incoming_edge_ids: tuple[NonEmptyStr, ...]

    @model_validator(mode="after")
    def validate_node_shape(self) -> RoutingNode:
        for values, label in (
            (self.next_node_ids, "next node identifiers"),
            (self.previous_node_ids, "previous node identifiers"),
            (self.outgoing_edge_ids, "outgoing edge identifiers"),
            (self.incoming_edge_ids, "incoming edge identifiers"),
        ):
            _require_unique(values, label)
        if (self.kind is NodeKind.terminal) != (self.terminal_kind is not None):
            raise ValueError("terminal kind is required only for terminal nodes")
        if self.kind is NodeKind.repeat_group:
            if self.repeat_spec is None:
                raise ValueError("repeat group node requires a repeat spec")
        elif self.repeat_spec is not None:
            raise ValueError("repeat spec is valid only for repeat group nodes")
        if self.kind in {NodeKind.section, NodeKind.repeat_group}:
            if self.containment.entry_child_node_id is None:
                raise ValueError("section and repeat group nodes require an entry child")
        elif self.containment.entry_child_node_id is not None:
            raise ValueError("entry child is valid only for section and repeat group nodes")
        if (
            self.kind in {NodeKind.entry, NodeKind.terminal}
            and self.activation_condition is not None
        ):
            raise ValueError("entry and terminal nodes cannot have activation conditions")
        return self


class RoutingEdge(StrictRoutingModel):
    """One authoritative accepted edge in the canonical multigraph."""

    edge_id: NonEmptyStr
    source_node_id: NonEmptyStr
    target_node_id: NonEmptyStr
    kind: EdgeKind
    condition: CanonicalRoutingCondition | None
    priority: NonNegativeInt | None
    evidence_ids: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    confidence: Confidence
    review_decision_id: NonEmptyStr | None

    @model_validator(mode="after")
    def validate_edge_shape(self) -> RoutingEdge:
        _validate_flow_shape(self.kind, self.condition, self.priority)
        _require_unique(self.evidence_ids, "accepted edge evidence identifiers")
        return self


class EvidenceRecord(StrictRoutingModel):
    """Python-assigned stable identifier around one immutable observation."""

    evidence_id: NonEmptyStr
    observation: EvidenceObservation


class CandidateEdge(StrictRoutingModel):
    """Non-authoritative edge candidate that can preserve an unresolved target."""

    candidate_id: NonEmptyStr
    source_node_id: NonEmptyStr
    target_node_id: NonEmptyStr | None
    target_reference: ItemReference
    kind: EdgeKind
    condition: ExtractedRoutingCondition | None
    priority: NonNegativeInt | None
    evidence_ids: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    confidence: Confidence
    status: CandidateStatus

    @model_validator(mode="after")
    def validate_candidate_shape(self) -> CandidateEdge:
        _validate_flow_shape(self.kind, self.condition, self.priority)
        _require_unique(self.evidence_ids, "candidate evidence identifiers")
        return self


class ReplacementEdge(StrictRoutingModel):
    """Typed reviewer replacement content before canonical edge assignment."""

    source_node_id: NonEmptyStr
    target_node_id: NonEmptyStr
    target_reference: ItemReference
    kind: EdgeKind
    condition: ExtractedRoutingCondition | None
    priority: NonNegativeInt | None
    evidence_ids: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_replacement_shape(self) -> ReplacementEdge:
        _validate_flow_shape(self.kind, self.condition, self.priority)
        _require_unique(self.evidence_ids, "replacement evidence identifiers")
        return self


class RoutingDiscrepancy(StrictRoutingModel):
    """Bounded discrepancy packet retained in the primary routed artifact."""

    discrepancy_id: NonEmptyStr
    kind: DiscrepancyKind
    candidate_ids: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    evidence_ids: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    source_span_ids: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    summary: NonEmptyStr
    needs_human_review: StrictBool
    resolved_by_decision_id: NonEmptyStr | None

    @model_validator(mode="after")
    def validate_unique_references(self) -> RoutingDiscrepancy:
        _require_unique(self.candidate_ids, "discrepancy candidate identifiers")
        _require_unique(self.evidence_ids, "discrepancy evidence identifiers")
        _require_unique(self.source_span_ids, "discrepancy span identifiers")
        return self


class ReviewDecision(StrictRoutingModel):
    """One append-only source-cited reviewer decision."""

    decision_id: NonEmptyStr
    discrepancy_ids: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    candidate_ids: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    evidence_ids: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    cited_span_ids: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    action: ReviewAction
    replacement: ReplacementEdge | None
    rationale: NonEmptyStr
    confidence: Confidence
    needs_human_review: StrictBool
    prompt_version: NonEmptyStr
    prompt_sha256: Sha256
    provider_response_sha256: Sha256
    supersedes_decision_id: NonEmptyStr | None

    @model_validator(mode="after")
    def validate_decision_shape(self) -> ReviewDecision:
        for values, label in (
            (self.discrepancy_ids, "decision discrepancy identifiers"),
            (self.candidate_ids, "decision candidate identifiers"),
            (self.evidence_ids, "decision evidence identifiers"),
            (self.cited_span_ids, "decision cited span identifiers"),
        ):
            _require_unique(values, label)
        if (self.action is ReviewAction.replace_candidate) != (self.replacement is not None):
            raise ValueError("only replace_candidate decisions require replacement content")
        if self.action is ReviewAction.unresolved and not self.needs_human_review:
            raise ValueError("unresolved decisions require human review")
        return self


class RoutingAudit(StrictRoutingModel):
    """Evidence-first append-only audit layer outside the accepted graph facts."""

    source_binding: RoutingSourceBinding
    inventory: tuple[InventoryItem, ...]
    source_spans: tuple[SourceSpan, ...]
    evidence: tuple[EvidenceRecord, ...]
    candidate_edges: tuple[CandidateEdge, ...]
    discrepancies: tuple[RoutingDiscrepancy, ...]
    review_decisions: tuple[ReviewDecision, ...]

    @model_validator(mode="after")
    def validate_audit_references(self) -> RoutingAudit:
        inventory = _unique_index(
            self.inventory,
            lambda item: item.node_id,
            "inventory node identifiers",
        )
        spans = _unique_index(
            self.source_spans,
            lambda span: span.span_id,
            "span identifiers",
        )
        evidence = _unique_index(
            self.evidence,
            lambda record: record.evidence_id,
            "evidence identifiers",
        )
        candidates = _unique_index(
            self.candidate_edges,
            lambda candidate: candidate.candidate_id,
            "candidate identifiers",
        )
        discrepancies = _unique_index(
            self.discrepancies,
            lambda discrepancy: discrepancy.discrepancy_id,
            "discrepancy identifiers",
        )
        decisions = _unique_index(
            self.review_decisions,
            lambda decision: decision.decision_id,
            "review decision identifiers",
        )

        linked_indices: set[int] = set()
        for item in inventory.values():
            overlap = linked_indices.intersection(item.linked_variable_indices)
            if overlap:
                raise ValueError("a variable index cannot link to more than one inventory item")
            linked_indices.update(item.linked_variable_indices)

        for record in evidence.values():
            span = spans.get(record.observation.source_span.span_id)
            if span is None or span != record.observation.source_span:
                raise ValueError("evidence must cite one matching audit source span")

        for candidate in candidates.values():
            _require_members(candidate.evidence_ids, evidence, "candidate evidence")
        for discrepancy in discrepancies.values():
            _require_members(discrepancy.candidate_ids, candidates, "discrepancy candidate")
            _require_members(discrepancy.evidence_ids, evidence, "discrepancy evidence")
            _require_members(discrepancy.source_span_ids, spans, "discrepancy source span")

        latest_by_candidate: dict[str, str] = {}
        superseded: set[str] = set()
        earlier: dict[str, ReviewDecision] = {}
        for decision in self.review_decisions:
            _require_members(decision.discrepancy_ids, discrepancies, "decision discrepancy")
            _require_members(decision.candidate_ids, candidates, "decision candidate")
            _require_members(decision.evidence_ids, evidence, "decision evidence")
            _require_members(decision.cited_span_ids, spans, "decision cited span")
            candidate_evidence = {
                evidence_id
                for candidate_id in decision.candidate_ids
                for evidence_id in candidates[candidate_id].evidence_ids
            }
            if not set(decision.evidence_ids).issubset(candidate_evidence):
                raise ValueError("decision evidence must belong to its reviewed candidates")
            evidence_spans = {
                evidence[evidence_id].observation.source_span.span_id
                for evidence_id in decision.evidence_ids
            }
            if not set(decision.cited_span_ids).issubset(evidence_spans):
                raise ValueError("decision spans must belong to its cited evidence")
            if decision.replacement is not None:
                _require_members(
                    decision.replacement.evidence_ids,
                    evidence,
                    "replacement evidence",
                )
            expected_predecessors = {
                latest_by_candidate[candidate_id]
                for candidate_id in decision.candidate_ids
                if candidate_id in latest_by_candidate
            }
            predecessor_id = decision.supersedes_decision_id
            if predecessor_id is not None:
                predecessor = earlier.get(predecessor_id)
                if predecessor is None:
                    raise ValueError("superseded review decision must occur earlier")
                if predecessor_id in superseded:
                    raise ValueError("a review decision can have only one superseding decision")
                if predecessor.candidate_ids != decision.candidate_ids:
                    raise ValueError("superseding review decisions must cover the same candidates")
                superseded.add(predecessor_id)
            if expected_predecessors and expected_predecessors != {predecessor_id}:
                raise ValueError("later review decisions must supersede the latest decision")
            earlier[decision.decision_id] = decision
            for candidate_id in decision.candidate_ids:
                latest_by_candidate[candidate_id] = decision.decision_id

        for discrepancy in discrepancies.values():
            decision_id = discrepancy.resolved_by_decision_id
            if decision_id is None:
                continue
            decision = decisions.get(decision_id)
            if decision is None or discrepancy.discrepancy_id not in decision.discrepancy_ids:
                raise ValueError("discrepancy resolution must reference a matching decision")
        return self


class LoopDefinition(StrictRoutingModel):
    """Bounded metadata for one declared or source-supported loop region."""

    loop_id: NonEmptyStr
    kind: LoopKind
    repeat_group_node_id: NonEmptyStr | None
    member_node_ids: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    entry_edge_ids: tuple[NonEmptyStr, ...]
    member_edge_ids: tuple[NonEmptyStr, ...]
    return_edge_ids: tuple[NonEmptyStr, ...]
    exit_edge_ids: tuple[NonEmptyStr, ...]
    source_supported: Literal[True]
    evidence_ids: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_loop_shape(self) -> LoopDefinition:
        for values, label in (
            (self.member_node_ids, "loop member node identifiers"),
            (self.entry_edge_ids, "loop entry edge identifiers"),
            (self.member_edge_ids, "loop member edge identifiers"),
            (self.return_edge_ids, "loop return edge identifiers"),
            (self.exit_edge_ids, "loop exit edge identifiers"),
            (self.evidence_ids, "loop evidence identifiers"),
        ):
            _require_unique(values, label)
        edge_roles = (
            self.entry_edge_ids,
            self.member_edge_ids,
            self.return_edge_ids,
            self.exit_edge_ids,
        )
        flattened = tuple(edge_id for role in edge_roles for edge_id in role)
        _require_unique(flattened, "loop edge-role identifiers")
        declared_repeat = self.kind in {LoopKind.repeat_group, LoopKind.repeat_until}
        if declared_repeat != (self.repeat_group_node_id is not None):
            raise ValueError("declared repeat loops require one repeat group node")
        if not declared_repeat and not self.return_edge_ids:
            raise ValueError("SCC loop regions require at least one return edge")
        return self


class RoutingDiagnostic(StrictRoutingModel):
    """Stable safe graph diagnostic without source-derived prose fields."""

    diagnostic_id: NonEmptyStr
    code: NonEmptyStr
    severity: DiagnosticSeverity
    message: NonEmptyStr
    node_ids: tuple[NonEmptyStr, ...]
    edge_ids: tuple[NonEmptyStr, ...]
    evidence_ids: tuple[NonEmptyStr, ...]
    candidate_ids: tuple[NonEmptyStr, ...]

    @model_validator(mode="after")
    def validate_unique_references(self) -> RoutingDiagnostic:
        for values, label in (
            (self.node_ids, "diagnostic node identifiers"),
            (self.edge_ids, "diagnostic edge identifiers"),
            (self.evidence_ids, "diagnostic evidence identifiers"),
            (self.candidate_ids, "diagnostic candidate identifiers"),
        ):
            _require_unique(values, label)
        return self


class QuestionnaireRoutingGraph(StrictRoutingModel):
    """Canonical directed multigraph plus its separate append-only audit."""

    schema_version: RoutingSchemaVersion
    entry_node_ids: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    nodes: Annotated[tuple[RoutingNode, ...], Field(min_length=1)]
    edges: tuple[RoutingEdge, ...]
    loops: tuple[LoopDefinition, ...]
    diagnostics: tuple[RoutingDiagnostic, ...]
    routing_audit: RoutingAudit

    @model_validator(mode="after")
    def validate_graph(self) -> QuestionnaireRoutingGraph:
        nodes = _unique_index(self.nodes, lambda node: node.node_id, "node identifiers")
        edges = _unique_index(self.edges, lambda edge: edge.edge_id, "edge identifiers")
        loops = _unique_index(self.loops, lambda loop: loop.loop_id, "loop identifiers")
        diagnostics = _unique_index(
            self.diagnostics,
            lambda diagnostic: diagnostic.diagnostic_id,
            "diagnostic identifiers",
        )
        _require_unique(self.entry_node_ids, "entry node identifiers")
        _require_members(self.entry_node_ids, nodes, "entry node")
        if any(nodes[node_id].kind is not NodeKind.entry for node_id in self.entry_node_ids):
            raise ValueError("graph entry identifiers must reference entry nodes")

        evidence = {item.evidence_id: item for item in self.routing_audit.evidence}
        decisions = {item.decision_id: item for item in self.routing_audit.review_decisions}
        candidates = {item.candidate_id: item for item in self.routing_audit.candidate_edges}
        inventory = {item.node_id: item for item in self.routing_audit.inventory}
        superseded_decisions = {
            decision.supersedes_decision_id
            for decision in decisions.values()
            if decision.supersedes_decision_id is not None
        }

        outgoing: dict[str, list[RoutingEdge]] = {node_id: [] for node_id in nodes}
        incoming: dict[str, list[RoutingEdge]] = {node_id: [] for node_id in nodes}
        defaults: dict[str, int] = {node_id: 0 for node_id in nodes}
        for edge in self.edges:
            if edge.source_node_id not in nodes or edge.target_node_id not in nodes:
                raise ValueError("accepted edge endpoints must reference canonical nodes")
            _require_members(edge.evidence_ids, evidence, "accepted edge evidence")
            if edge.review_decision_id is not None and edge.review_decision_id not in decisions:
                raise ValueError("accepted edge review decision must exist in the audit")
            _validate_edge_support(
                edge,
                evidence=evidence,
                decisions=decisions,
                candidates=candidates,
                inventory=inventory,
                superseded_decisions=superseded_decisions,
            )
            outgoing[edge.source_node_id].append(edge)
            incoming[edge.target_node_id].append(edge)
            if edge.kind is EdgeKind.default:
                defaults[edge.source_node_id] += 1
        if any(count > 1 for count in defaults.values()):
            raise ValueError("each source node can have at most one default edge")

        for candidate in candidates.values():
            if candidate.source_node_id not in nodes:
                raise ValueError("candidate source endpoint must reference a canonical node")
            if candidate.target_node_id is not None and candidate.target_node_id not in nodes:
                raise ValueError("resolved candidate target must reference a canonical node")
        for decision in decisions.values():
            replacement = decision.replacement
            if replacement is not None and (
                replacement.source_node_id not in nodes or replacement.target_node_id not in nodes
            ):
                raise ValueError("replacement edge endpoints must reference canonical nodes")

        self._validate_adjacency(nodes, outgoing, incoming)
        self._validate_containment(nodes, edges)
        self._validate_condition_references(nodes)
        self._validate_loops(nodes, edges, loops, evidence)

        for diagnostic in diagnostics.values():
            if (
                any(node_id not in nodes for node_id in diagnostic.node_ids)
                or any(edge_id not in edges for edge_id in diagnostic.edge_ids)
                or any(evidence_id not in evidence for evidence_id in diagnostic.evidence_ids)
                or any(candidate_id not in candidates for candidate_id in diagnostic.candidate_ids)
            ):
                raise ValueError("diagnostic references must exist in their canonical namespace")
        for item in self.routing_audit.inventory:
            if item.node_id not in nodes:
                raise ValueError("inventory item must reference a canonical node")
        return self

    def _validate_adjacency(
        self,
        nodes: dict[str, RoutingNode],
        outgoing: dict[str, list[RoutingEdge]],
        incoming: dict[str, list[RoutingEdge]],
    ) -> None:
        for node in self.nodes:
            expected_outgoing = tuple(edge.edge_id for edge in outgoing[node.node_id])
            expected_incoming = tuple(edge.edge_id for edge in incoming[node.node_id])
            expected_next = _ordered_unique(edge.target_node_id for edge in outgoing[node.node_id])
            expected_previous = _ordered_unique(
                edge.source_node_id for edge in incoming[node.node_id]
            )
            if (
                node.outgoing_edge_ids != expected_outgoing
                or node.incoming_edge_ids != expected_incoming
                or node.next_node_ids != expected_next
                or node.previous_node_ids != expected_previous
            ):
                raise ValueError("node adjacency must be the ordered accepted-edge projection")
            if node.kind is NodeKind.terminal and outgoing[node.node_id]:
                raise ValueError("terminal nodes cannot have outgoing accepted edges")

    def _validate_containment(
        self,
        nodes: dict[str, RoutingNode],
        edges: dict[str, RoutingEdge],
    ) -> None:
        for node in self.nodes:
            parent_id = node.containment.parent_node_id
            if parent_id is not None and parent_id not in nodes:
                raise ValueError("containment parent must reference a canonical node")

        for node in self.nodes:
            visited: set[str] = set()
            current: RoutingNode | None = node
            while current is not None:
                if current.node_id in visited:
                    raise ValueError("containment hierarchy must be acyclic")
                visited.add(current.node_id)
                parent_id = current.containment.parent_node_id
                current = nodes.get(parent_id) if parent_id is not None else None

        expected_children: dict[str, list[str]] = {node_id: [] for node_id in nodes}
        for child in self.nodes:
            parent_id = child.containment.parent_node_id
            if parent_id is not None:
                expected_children[parent_id].append(child.node_id)
        for node in self.nodes:
            if node.containment.child_node_ids != tuple(expected_children[node.node_id]):
                raise ValueError("containment child identifiers must be derived in node order")
            if expected_children[node.node_id] and node.kind not in {
                NodeKind.section,
                NodeKind.repeat_group,
            }:
                raise ValueError("only section and repeat group nodes can contain children")
            entry_id = node.containment.entry_child_node_id
            if entry_id is None:
                continue
            matching = tuple(
                edge
                for edge in edges.values()
                if edge.source_node_id == node.node_id and edge.target_node_id == entry_id
            )
            if len(matching) != 1 or matching[0].kind is not EdgeKind.unconditional:
                raise ValueError("section and repeat entry requires one unconditional entry edge")

    def _validate_condition_references(self, nodes: dict[str, RoutingNode]) -> None:
        conditions: list[CanonicalRoutingCondition] = []
        for node in self.nodes:
            if node.activation_condition is not None:
                conditions.append(node.activation_condition)
            if node.repeat_spec is not None and node.repeat_spec.continuation_condition is not None:
                conditions.append(node.repeat_spec.continuation_condition)
        conditions.extend(edge.condition for edge in self.edges if edge.condition is not None)
        for record in self.routing_audit.evidence:
            native = record.observation.native_expression
            if native is not None:
                conditions.append(native.canonical_projection)
        for condition in conditions:
            for question_node_id in _condition_question_ids(condition):
                node = nodes.get(question_node_id)
                if node is None or node.kind is not NodeKind.question:
                    raise ValueError("canonical condition references must identify question nodes")

    def _validate_loops(
        self,
        nodes: dict[str, RoutingNode],
        edges: dict[str, RoutingEdge],
        loops: dict[str, LoopDefinition],
        evidence: dict[str, EvidenceRecord],
    ) -> None:
        for loop in loops.values():
            _require_members(loop.member_node_ids, nodes, "loop member node")
            _require_members(loop.evidence_ids, evidence, "loop evidence")
            role_ids = (
                loop.entry_edge_ids
                + loop.member_edge_ids
                + loop.return_edge_ids
                + loop.exit_edge_ids
            )
            _require_members(role_ids, edges, "loop edge")
            members = set(loop.member_node_ids)
            if loop.repeat_group_node_id is not None:
                repeat_node = nodes.get(loop.repeat_group_node_id)
                if repeat_node is None or repeat_node.kind is not NodeKind.repeat_group:
                    raise ValueError("loop repeat group must reference a repeat group node")
            if any(
                edges[edge_id].source_node_id in members
                or edges[edge_id].target_node_id not in members
                for edge_id in loop.entry_edge_ids
            ):
                raise ValueError("loop entry edges must enter the member region")
            if any(
                edges[edge_id].source_node_id not in members
                or edges[edge_id].target_node_id not in members
                for edge_id in loop.member_edge_ids + loop.return_edge_ids
            ):
                raise ValueError("loop member and return edges must stay in the member region")
            if any(
                edges[edge_id].source_node_id not in members
                or edges[edge_id].target_node_id in members
                for edge_id in loop.exit_edge_ids
            ):
                raise ValueError("loop exit edges must leave the member region")


class RoutedAnswerCategory(AnswerCategory):
    """Deeply immutable routed form of one legacy answer category."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    code: StrictInt | StrictStr
    label: StrictStr
    is_missing: StrictBool = False


class RoutedNumericRange(NumericRange):
    """Deeply immutable routed form of one legacy numeric range."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    min_value: FiniteFloat | None = None
    max_value: FiniteFloat | None = None
    notes: StrictStr | None = None


class RoutedSurveyVariable(SurveyVariable):
    """Legacy-compatible variable with one nullable canonical node link."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    categories: tuple[RoutedAnswerCategory, ...] | None = None
    numeric_range: RoutedNumericRange | None = None
    routing_node_id: NonEmptyStr | None

    @field_validator("categories", mode="before")
    @classmethod
    def detach_categories(cls, value: object) -> object:
        """Detach mutable legacy categories before routed validation."""
        if value is None:
            return None
        if not isinstance(value, tuple | list):
            return value
        return tuple(
            {
                "code": item.code,
                "label": item.label,
                "is_missing": item.is_missing,
            }
            if isinstance(item, AnswerCategory)
            else item
            for item in value
        )

    @field_validator("numeric_range", mode="before")
    @classmethod
    def detach_numeric_range(cls, value: object) -> object:
        """Detach a mutable legacy numeric range before routed validation."""
        if isinstance(value, NumericRange):
            return {
                "min_value": value.min_value,
                "max_value": value.max_value,
                "notes": value.notes,
            }
        return value

    def to_survey_variable(self) -> SurveyVariable:
        """Reconstruct the exact ordered legacy variable type."""
        categories = (
            [
                AnswerCategory(
                    code=category.code,
                    label=category.label,
                    is_missing=category.is_missing,
                )
                for category in self.categories
            ]
            if self.categories is not None
            else None
        )
        numeric_range = (
            NumericRange(
                min_value=self.numeric_range.min_value,
                max_value=self.numeric_range.max_value,
                notes=self.numeric_range.notes,
            )
            if self.numeric_range is not None
            else None
        )
        return SurveyVariable(
            raw_name=self.raw_name,
            label=self.label,
            question_text=self.question_text,
            data_type=self.data_type,
            categories=categories,
            numeric_range=numeric_range,
            universe=self.universe,
            skip_condition_raw=self.skip_condition_raw,
            module=self.module,
            unit_of_analysis=self.unit_of_analysis,
            source_page=self.source_page,
            extraction_confidence=self.extraction_confidence,
            needs_review=self.needs_review,
            notes=self.notes,
        )


class RoutedSurveySVIS(SurveySVIS):
    """Versioned routed extension with an exact typed legacy projection."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    variables: tuple[RoutedSurveyVariable, ...]
    routing_schema_version: RoutingSchemaVersion
    routing_graph: QuestionnaireRoutingGraph

    @model_validator(mode="after")
    def validate_routed_links_and_versions(self) -> RoutedSurveySVIS:
        if self.routing_schema_version != self.routing_graph.schema_version:
            raise ValueError("routed and graph schema versions must be equal")
        if self.routing_graph.routing_audit.source_binding.survey_id != self.survey_id:
            raise ValueError("routing source binding survey must match the routed survey")
        nodes = {node.node_id: node for node in self.routing_graph.nodes}
        inventory_links: dict[int, str] = {}
        for item in self.routing_graph.routing_audit.inventory:
            for variable_index in item.linked_variable_indices:
                if variable_index >= len(self.variables):
                    raise ValueError(
                        "inventory variable link is outside the routed variable sequence"
                    )
                inventory_links[variable_index] = item.node_id
        for variable_index, variable in enumerate(self.variables):
            node = None if variable.routing_node_id is None else nodes.get(variable.routing_node_id)
            if variable.routing_node_id is not None and (
                node is None or node.kind is not NodeKind.question
            ):
                raise ValueError("routed variable links must reference question nodes")
            if variable.routing_node_id != inventory_links.get(variable_index):
                raise ValueError("routed variable links must match inventory variable indices")
        return self

    def to_survey_svis(self) -> SurveySVIS:
        """Reconstruct an exact ordered v1 SVIS without dictionary deletion."""
        return SurveySVIS(
            survey_id=self.survey_id,
            country_code=self.country_code,
            year=self.year,
            survey_name=self.survey_name,
            study_type=self.study_type,
            data_collection_mode=self.data_collection_mode,
            language=self.language,
            variables=[variable.to_survey_variable() for variable in self.variables],
            source_file=self.source_file,
            source_format=self.source_format,
            extraction_date=self.extraction_date,
            extraction_notes=self.extraction_notes,
        )


def canonical_routing_schema_json() -> str:
    """Return the canonical graph JSON Schema with deterministic formatting."""
    return (
        json.dumps(
            QuestionnaireRoutingGraph.model_json_schema(),
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def _validate_flow_shape(
    kind: EdgeKind,
    condition: object,
    priority: int | None,
) -> None:
    if (kind is EdgeKind.conditional) != (condition is not None):
        raise ValueError("only conditional flow records have a condition")
    if priority is not None and kind not in {EdgeKind.conditional, EdgeKind.default}:
        raise ValueError("priority is valid only for ordered conditional or default flow")


def _require_unique(values: tuple[object, ...], label: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"{label} must be unique")


_IndexValue = TypeVar("_IndexValue")


def _unique_index(
    items: tuple[_IndexValue, ...],
    key: Callable[[_IndexValue], str],
    label: str,
) -> dict[str, _IndexValue]:
    indexed = {key(item): item for item in items}
    if len(indexed) != len(items):
        raise ValueError(f"{label} must be unique")
    return indexed


def _require_members(
    values: tuple[str, ...],
    indexed: Mapping[str, object],
    label: str,
) -> None:
    if any(value not in indexed for value in values):
        raise ValueError(f"{label} references must exist")


def _ordered_unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _condition_question_ids(condition: CanonicalRoutingCondition) -> tuple[str, ...]:
    identifiers: list[str] = []
    stack = [condition]
    while stack:
        current = stack.pop()
        if current.question_node_id is not None:
            identifiers.append(current.question_node_id)
        if current.children:
            stack.extend(reversed(current.children))
    return tuple(identifiers)


def _validate_edge_support(
    edge: RoutingEdge,
    *,
    evidence: Mapping[str, EvidenceRecord],
    decisions: Mapping[str, ReviewDecision],
    candidates: Mapping[str, CandidateEdge],
    inventory: Mapping[str, InventoryItem],
    superseded_decisions: Set[str],
) -> None:
    decision_id = edge.review_decision_id
    if decision_id is None:
        if not inventory:
            raise ValueError("accepted edge evidence requires a complete audit inventory")
        if any(
            not _transition_evidence_matches_edge(
                edge,
                evidence[evidence_id].observation,
                inventory,
            )
            for evidence_id in edge.evidence_ids
        ):
            raise ValueError("accepted edge evidence must describe the same canonical route")
        return

    if decision_id in superseded_decisions:
        raise ValueError("accepted edge cannot cite a superseded review decision")
    decision = decisions[decision_id]
    if decision.action is ReviewAction.confirm_candidate:
        matching = tuple(
            candidate
            for candidate_id in decision.candidate_ids
            if (candidate := candidates[candidate_id]).target_node_id is not None
            and _edge_matches_candidate(edge, candidate, inventory, evidence)
        )
        if len(matching) != 1:
            raise ValueError("confirmed edge must match one active reviewed candidate")
        return
    if decision.action is ReviewAction.replace_candidate and decision.replacement is not None:
        if not _edge_matches_replacement(edge, decision.replacement, inventory, evidence):
            raise ValueError("replacement edge must match its active review decision")
        return
    raise ValueError("accepted edge review decision cannot reject or defer its route")


def _transition_evidence_matches_edge(
    edge: RoutingEdge,
    observation: EvidenceObservation,
    inventory: Mapping[str, InventoryItem],
) -> bool:
    if not isinstance(observation, TransitionEvidence):
        return False
    source = _resolve_audit_reference(observation.source, inventory)
    source_item = inventory.get(source) if source is not None else None
    target = _resolve_audit_reference(
        observation.target,
        inventory,
        default_section_path=(source_item.section_path if source_item is not None else ()),
    )
    if (
        source != edge.source_node_id
        or target != edge.target_node_id
        or observation.transition_kind.value != edge.kind.value
    ):
        return False
    condition = _project_audit_condition(
        observation.condition,
        inventory,
        default_section_path=(source_item.section_path if source_item is not None else ()),
    )
    return _conditions_match(edge.condition, condition)


def _edge_matches_candidate(
    edge: RoutingEdge,
    candidate: CandidateEdge,
    inventory: Mapping[str, InventoryItem],
    evidence: Mapping[str, EvidenceRecord],
) -> bool:
    source = inventory.get(candidate.source_node_id)
    condition = _project_audit_condition(
        candidate.condition,
        inventory,
        default_section_path=(source.section_path if source is not None else ()),
    )
    return (
        edge.source_node_id == candidate.source_node_id
        and edge.target_node_id == candidate.target_node_id
        and edge.kind is candidate.kind
        and edge.priority == candidate.priority
        and edge.evidence_ids == candidate.evidence_ids
        and _resolve_audit_reference(
            candidate.target_reference,
            inventory,
            default_section_path=(source.section_path if source is not None else ()),
        )
        == candidate.target_node_id
        and _conditions_match(edge.condition, condition)
        and all(
            _transition_evidence_matches_edge(edge, evidence[evidence_id].observation, inventory)
            for evidence_id in edge.evidence_ids
        )
    )


def _edge_matches_replacement(
    edge: RoutingEdge,
    replacement: ReplacementEdge,
    inventory: Mapping[str, InventoryItem],
    evidence: Mapping[str, EvidenceRecord],
) -> bool:
    source = inventory.get(replacement.source_node_id)
    condition = _project_audit_condition(
        replacement.condition,
        inventory,
        default_section_path=(source.section_path if source is not None else ()),
    )
    return (
        edge.source_node_id == replacement.source_node_id
        and edge.target_node_id == replacement.target_node_id
        and edge.kind is replacement.kind
        and edge.priority == replacement.priority
        and edge.evidence_ids == replacement.evidence_ids
        and _resolve_audit_reference(
            replacement.target_reference,
            inventory,
            default_section_path=(source.section_path if source is not None else ()),
        )
        == replacement.target_node_id
        and _conditions_match(edge.condition, condition)
        and all(
            _transition_evidence_matches_edge(edge, evidence[evidence_id].observation, inventory)
            for evidence_id in edge.evidence_ids
        )
    )


def _project_audit_condition(
    condition: ExtractedRoutingCondition | None,
    inventory: Mapping[str, InventoryItem],
    *,
    default_section_path: tuple[str, ...],
) -> CanonicalRoutingCondition | None:
    if condition is None:
        return None
    bindings: dict[tuple[tuple[str, ...], str, NodeKind], str] = {}
    stack = [condition]
    while stack:
        current = stack.pop()
        reference = current.item_reference
        if reference is not None:
            node_id = _resolve_audit_reference(
                reference,
                inventory,
                default_section_path=default_section_path,
            )
            if node_id is None:
                return None
            bindings[reference.binding_key] = node_id
        if current.children:
            stack.extend(current.children)
    try:
        return project_extracted_condition(condition, bindings)
    except ValueError:
        return None


def _resolve_audit_reference(
    reference: ItemReference,
    inventory: Mapping[str, InventoryItem],
    *,
    default_section_path: tuple[str, ...] = (),
) -> str | None:
    identity = _audit_alias(reference.source_item_id or reference.raw_reference)
    section = reference.section_path or default_section_path
    matches = tuple(
        item.node_id
        for item in inventory.values()
        if item.kind is reference.node_kind
        and _audit_alias(item.source_item_id or item.raw_reference) == identity
        and (not section or _audit_section(item.section_path) == _audit_section(section))
    )
    if not matches and section and not reference.section_path:
        matches = tuple(
            item.node_id
            for item in inventory.values()
            if item.kind is reference.node_kind
            and _audit_alias(item.source_item_id or item.raw_reference) == identity
        )
    return matches[0] if len(matches) == 1 else None


def _audit_alias(value: str) -> str:
    return normalized_alias_value(value)


def _audit_section(value: tuple[str, ...]) -> tuple[str, ...]:
    return normalize_section_path_value(value)


def _conditions_match(
    left: CanonicalRoutingCondition | None,
    right: CanonicalRoutingCondition | None,
) -> bool:
    if left is None or right is None:
        return left is right
    return _condition_support_identity(left) == _condition_support_identity(right)


def _condition_support_identity(condition: CanonicalRoutingCondition) -> str:
    value = condition.model_dump(mode="json")
    stack = [value]
    while stack:
        current = stack.pop()
        current.pop("raw_text", None)
        children = current.get("children")
        if isinstance(children, list):
            stack.extend(child for child in children if isinstance(child, dict))
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


__all__ = [
    "CandidateEdge",
    "CandidateStatus",
    "Containment",
    "DiagnosticSeverity",
    "DiscrepancyKind",
    "EdgeKind",
    "EvidenceRecord",
    "InventoryItem",
    "LoopDefinition",
    "LoopKind",
    "QuestionnaireRoutingGraph",
    "RepeatKind",
    "RepeatSpec",
    "ReplacementEdge",
    "ReviewAction",
    "ReviewDecision",
    "RoutedAnswerCategory",
    "RoutedNumericRange",
    "RoutedSurveySVIS",
    "RoutedSurveyVariable",
    "RoutingAudit",
    "RoutingDiagnostic",
    "RoutingDiscrepancy",
    "RoutingEdge",
    "RoutingNode",
    "RoutingSourceBinding",
    "TerminalKind",
    "canonical_routing_schema_json",
]
