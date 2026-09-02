# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = [
#   "loguru==0.7.3",
#   "pydantic>=2.11.7,<3",
# ]
# ///
"""Evaluate deterministic routing mechanics without provider access."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import tempfile
import tomllib
import tracemalloc
from collections import Counter
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from time import perf_counter
from typing import Annotated, Literal

from loguru import logger
from pydantic import Field, StrictBool, StrictFloat, StrictInt, StrictStr, model_validator

from survey_scribe.models.routing import EdgeKind, LoopKind, TerminalKind
from survey_scribe.routing.algorithms import iterative_strongly_connected_components
from survey_scribe.routing.contracts import (
    CanonicalRoutingCondition,
    ConditionOperator,
    NodeKind,
    NonEmptyStr,
    StrictRoutingModel,
)

if __package__:
    from scripts.validate_routing_fixtures import validate as validate_source_manifest
else:
    from validate_routing_fixtures import validate as validate_source_manifest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_MANIFEST = Path("tests/fixtures/routing/manifest.toml")
DEFAULT_MECHANICS_MANIFEST = Path("tests/fixtures/routing_mechanics/manifest.toml")
DEFAULT_REPORT = Path(".cache/routing-evaluation/report.json")
DEFAULT_SCALE_REPORT = Path(".cache/routing-evaluation/scale-report.json")
MECHANICS_ROOT = PurePosixPath("tests/fixtures/routing_mechanics")
REPORT_ROOT = PurePosixPath(".cache/routing-evaluation")
SHA256_PATTERN = r"^[0-9a-f]{64}$"
EVALUATOR_VERSION = "1.1"

NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
Sha256 = Annotated[str, Field(pattern=SHA256_PATTERN)]
MECHANICS_PURPOSE = (
    "Freeze deterministic inventory, identity, containment, variable-link, "
    "and partial-output mechanics."
)
MECHANICS_PROVENANCE = (
    "Generated only from repository-authored synthetic normalized blocks and fixed SVIS "
    "records; no model response was used."
)
MECHANICS_RESTRICTIONS = (
    "Mechanics regression testing only; not approved for model-quality benchmarking."
)


class ManifestArtifact(StrictRoutingModel):
    """One confined checksummed mechanics artifact."""

    path: NonEmptyStr
    sha256: Sha256


class MechanicsManifest(StrictRoutingModel):
    """Strict governance boundary for deterministic mechanics fixtures."""

    schema_version: StrictInt
    artifact_kind: StrictStr
    benchmark_eligible: StrictBool
    identity_schema: StrictStr
    source_conversion_schema_version: StrictStr
    purpose: StrictStr
    provenance: StrictStr
    restrictions: StrictStr
    output: ManifestArtifact
    evaluation: ManifestArtifact

    @model_validator(mode="after")
    def validate_policy(self) -> MechanicsManifest:
        if self.schema_version != 1:
            raise ValueError("mechanics manifest schema version is unsupported")
        if self.artifact_kind != "deterministic-routing-mechanics":
            raise ValueError("mechanics manifest artifact kind is unsupported")
        if self.benchmark_eligible:
            raise ValueError("mechanics manifest must be benchmark-ineligible")
        if self.identity_schema != "routing-node-fallback-v1":
            raise ValueError("mechanics manifest identity schema is unsupported")
        if self.source_conversion_schema_version != "1.0":
            raise ValueError("mechanics manifest source schema is unsupported")
        if self.purpose != MECHANICS_PURPOSE:
            raise ValueError("mechanics manifest purpose is unsupported")
        if self.provenance != MECHANICS_PROVENANCE:
            raise ValueError("mechanics manifest provenance is unsupported")
        if self.restrictions != MECHANICS_RESTRICTIONS:
            raise ValueError("mechanics manifest restrictions are invalid")
        return self


class EvaluationNode(StrictRoutingModel):
    """Content-safe canonical node facts used by mechanics evaluation."""

    node_id: NonEmptyStr
    source_item_id: NonEmptyStr | None
    kind: NodeKind
    terminal_kind: TerminalKind | None

    @model_validator(mode="after")
    def validate_terminal(self) -> EvaluationNode:
        if (self.kind is NodeKind.terminal) != (self.terminal_kind is not None):
            raise ValueError("terminal kind is required only for terminal nodes")
        return self


class EvaluationEdge(StrictRoutingModel):
    """One accepted directed multigraph edge without evidence prose."""

    source_node_id: NonEmptyStr
    target_node_id: NonEmptyStr
    kind: EdgeKind
    condition: CanonicalRoutingCondition | None
    priority: NonNegativeInt | None

    @model_validator(mode="after")
    def validate_flow_shape(self) -> EvaluationEdge:
        if (self.kind is EdgeKind.conditional) != (self.condition is not None):
            raise ValueError("only conditional evaluation edges have a condition")
        if self.priority is not None and self.kind not in {
            EdgeKind.conditional,
            EdgeKind.default,
        }:
            raise ValueError("priority is valid only for conditional or default edges")
        return self


class UnresolvedRoute(StrictRoutingModel):
    """One unresolved branch that cannot count as an accepted prediction."""

    source_node_id: NonEmptyStr
    kind: EdgeKind
    condition: CanonicalRoutingCondition | None
    priority: NonNegativeInt | None

    @model_validator(mode="after")
    def validate_flow_shape(self) -> UnresolvedRoute:
        if (self.kind is EdgeKind.conditional) != (self.condition is not None):
            raise ValueError("only conditional unresolved routes have a condition")
        if self.priority is not None and self.kind not in {
            EdgeKind.conditional,
            EdgeKind.default,
        }:
            raise ValueError("priority is valid only for conditional or default routes")
        return self


class EvaluationLoop(StrictRoutingModel):
    """Bounded loop classification without source or reviewer prose."""

    kind: LoopKind
    repeat_group_node_id: NonEmptyStr | None
    member_node_ids: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_loop(self) -> EvaluationLoop:
        if len(set(self.member_node_ids)) != len(self.member_node_ids):
            raise ValueError("evaluation loop member identifiers must be unique")
        declared_repeat = self.kind in {LoopKind.repeat_group, LoopKind.repeat_until}
        if declared_repeat != (self.repeat_group_node_id is not None):
            raise ValueError("declared repeat loops require one repeat group node")
        return self


class EvaluationStage(StrictRoutingModel):
    """Accepted graph facts and separate unresolved routes at one quality stage."""

    nodes: tuple[EvaluationNode, ...]
    edges: tuple[EvaluationEdge, ...]
    loops: tuple[EvaluationLoop, ...]
    unresolved_routes: tuple[UnresolvedRoute, ...]

    @model_validator(mode="after")
    def validate_references(self) -> EvaluationStage:
        node_ids = tuple(node.node_id for node in self.nodes)
        if len(set(node_ids)) != len(node_ids):
            raise ValueError("evaluation node identifiers must be unique")
        known_nodes = set(node_ids)
        if self.nodes:
            if not any(node.kind is NodeKind.entry for node in self.nodes):
                raise ValueError("nonempty evaluation stages require an entry node")
            if not any(node.kind is NodeKind.terminal for node in self.nodes):
                raise ValueError("nonempty evaluation stages require a terminal node")
        terminal_nodes = {node.node_id for node in self.nodes if node.kind is NodeKind.terminal}
        entry_nodes = {node.node_id for node in self.nodes if node.kind is NodeKind.entry}
        default_sources: set[str] = set()
        for edge in self.edges:
            if edge.source_node_id not in known_nodes or edge.target_node_id not in known_nodes:
                raise ValueError("evaluation edge endpoints must reference known nodes")
            if edge.source_node_id in terminal_nodes:
                raise ValueError("evaluation terminal nodes cannot have outgoing edges")
            if edge.target_node_id in entry_nodes:
                raise ValueError("evaluation entry nodes cannot have incoming edges")
            if edge.kind is EdgeKind.default:
                if edge.source_node_id in default_sources:
                    raise ValueError("evaluation nodes can have at most one default edge")
                default_sources.add(edge.source_node_id)
            if not _condition_references_known_nodes(edge.condition, known_nodes):
                raise ValueError("evaluation edge condition must reference known nodes")
        for route in self.unresolved_routes:
            if route.source_node_id not in known_nodes:
                raise ValueError("unresolved route source must reference a known node")
            if not _condition_references_known_nodes(route.condition, known_nodes):
                raise ValueError("unresolved route condition must reference known nodes")
        loop_keys = tuple(
            (loop.kind, loop.repeat_group_node_id, loop.member_node_ids) for loop in self.loops
        )
        if len(set(loop_keys)) != len(loop_keys):
            raise ValueError("evaluation loop identities must be unique")
        adjacency: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
        for edge in self.edges:
            adjacency[edge.source_node_id].append(edge.target_node_id)
        cyclic_components = {
            frozenset(component)
            for component in iterative_strongly_connected_components(node_ids, adjacency)
            if len(component) > 1 or any(node_id in adjacency[node_id] for node_id in component)
        }
        for loop in self.loops:
            if any(node_id not in known_nodes for node_id in loop.member_node_ids):
                raise ValueError("evaluation loop members must reference known nodes")
            if (
                loop.repeat_group_node_id is not None
                and loop.repeat_group_node_id not in known_nodes
            ):
                raise ValueError("evaluation repeat loop must reference a known group node")
            if frozenset(loop.member_node_ids) not in cyclic_components:
                raise ValueError("evaluation loop members must identify one accepted cycle")
        return self


class EvaluationBundle(StrictRoutingModel):
    """Checksummed synthetic first-pass and post-review mechanics fixture."""

    schema_version: StrictInt
    artifact_kind: Literal["deterministic-routing-quality"]
    benchmark_eligible: StrictBool
    claim_scope: Literal["deterministic-mechanics-only"]
    g6_status: Literal["not_run"]
    source_manifest_sha256: Sha256
    source_fixture_ids: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    expected: EvaluationStage
    first_pass: EvaluationStage
    post_review: EvaluationStage

    @model_validator(mode="after")
    def validate_policy(self) -> EvaluationBundle:
        if self.schema_version != 1:
            raise ValueError("evaluation bundle schema version is unsupported")
        if self.benchmark_eligible:
            raise ValueError("evaluation bundle must be benchmark-ineligible")
        if len(set(self.source_fixture_ids)) != len(self.source_fixture_ids):
            raise ValueError("evaluation source fixture identifiers must be unique")
        return self


class CountMetric(StrictRoutingModel):
    """Multiset precision and recall counts."""

    expected_count: NonNegativeInt
    actual_count: NonNegativeInt
    matched_count: NonNegativeInt
    precision: StrictFloat | None
    recall: StrictFloat | None


class AccuracyMetric(StrictRoutingModel):
    """Exact-match accuracy with an explicit unavailable state."""

    expected_count: NonNegativeInt
    actual_count: NonNegativeInt
    matched_count: NonNegativeInt
    value: StrictFloat | None


class RateMetric(StrictRoutingModel):
    """Observed count over an explicit evaluated-route denominator."""

    count: NonNegativeInt
    total_count: NonNegativeInt
    value: StrictFloat | None


class StageMetrics(StrictRoutingModel):
    """Content-safe mechanics metrics for one routing stage."""

    nodes: CountMetric
    edges: CountMetric
    targets: AccuracyMetric
    conditions: AccuracyMetric
    terminals: AccuracyMetric
    loops: AccuracyMetric
    unresolved_route_count: NonNegativeInt
    unresolved_routes: RateMetric
    opaque_conditions: RateMetric
    invented_source_id_count: NonNegativeInt


class ReviewEffect(StrictRoutingModel):
    """Post-review metric changes relative to first-pass quality."""

    edge_precision_delta: StrictFloat | None
    edge_recall_delta: StrictFloat | None
    target_accuracy_delta: StrictFloat | None
    condition_accuracy_delta: StrictFloat | None
    terminal_accuracy_delta: StrictFloat | None
    loop_accuracy_delta: StrictFloat | None
    unresolved_rate_delta: StrictFloat | None
    opaque_rate_delta: StrictFloat | None


class EvaluationReport(StrictRoutingModel):
    """Deterministic evaluator report with no questionnaire or reviewer prose."""

    schema_version: Literal[1]
    claim_scope: Literal["deterministic-mechanics-only"]
    g6_status: Literal["not_run"]
    evaluator_version: Literal["1.1"]
    source_manifest_sha256: Sha256
    mechanics_manifest_sha256: Sha256
    evaluation_fixture_sha256: Sha256
    expected_sha256: Sha256
    first_pass_sha256: Sha256
    post_review_sha256: Sha256
    first_pass: StageMetrics
    post_review: StageMetrics
    review_effect: ReviewEffect
    mechanics_passed: StrictBool


class ScaleEvidence(StrictRoutingModel):
    """Questionnaire-scale evidence without a cross-platform time threshold."""

    schema_version: Literal[1]
    node_count: NonNegativeInt
    edge_count: NonNegativeInt
    semantic_sha256: Sha256
    deterministic: StrictBool
    platform: NonEmptyStr
    machine: NonEmptyStr
    processor: NonEmptyStr
    python: NonEmptyStr
    duration_seconds: Annotated[StrictFloat, Field(gt=0.0)]
    peak_bytes: Annotated[StrictInt, Field(gt=0)]
    timer_method: Literal["time.perf_counter"]
    peak_memory_method: Literal["tracemalloc traced Python allocations"]


def _condition_payload(condition: CanonicalRoutingCondition | None) -> object:
    if condition is None:
        return None
    children = (
        [_condition_payload(child) for child in condition.children]
        if condition.children is not None
        else None
    )
    if children is not None and condition.operator in {
        ConditionOperator.all,
        ConditionOperator.any,
    }:
        children.sort(key=_identity)
    values = (
        sorted((_typed_scalar(value) for value in condition.values), key=_identity)
        if condition.values is not None
        else None
    )
    raw_text_sha256 = None
    if condition.operator is ConditionOperator.opaque and condition.raw_text is not None:
        normalized = " ".join(condition.raw_text.split())
        raw_text_sha256 = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return {
        "children": children,
        "operator": condition.operator.value,
        "question_node_id": condition.question_node_id,
        "raw_text_sha256": raw_text_sha256,
        "value": _typed_scalar(condition.value) if condition.value is not None else None,
        "values": values,
    }


def _typed_scalar(value: str | int | float | bool) -> object:
    value_type = (
        "boolean"
        if type(value) is bool
        else "integer"
        if type(value) is int
        else "number"
        if type(value) is float
        else "string"
    )
    return {"type": value_type, "value": value}


def _condition_references_known_nodes(
    condition: CanonicalRoutingCondition | None,
    known_nodes: set[str],
) -> bool:
    if condition is None:
        return True
    stack = [condition]
    while stack:
        current = stack.pop()
        if current.question_node_id is not None and current.question_node_id not in known_nodes:
            return False
        if current.children is not None:
            stack.extend(current.children)
    return True


def _identity(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _node_identity(node: EvaluationNode) -> str:
    return _identity(
        {
            "kind": node.kind.value,
            "node_id": node.node_id,
            "source_item_id": node.source_item_id,
            "terminal_kind": node.terminal_kind.value if node.terminal_kind is not None else None,
        }
    )


def _edge_identity(edge: EvaluationEdge) -> str:
    return _identity(
        {
            "condition": _condition_payload(edge.condition),
            "kind": edge.kind.value,
            "priority": edge.priority,
            "source": edge.source_node_id,
            "target": edge.target_node_id,
        }
    )


def _target_identity(edge: EvaluationEdge) -> str:
    return _identity(
        {
            "kind": edge.kind.value,
            "priority": edge.priority,
            "source": edge.source_node_id,
            "target": edge.target_node_id,
        }
    )


def _condition_identity(edge: EvaluationEdge) -> str:
    return _identity(
        {
            "kind": edge.kind.value,
            "priority": edge.priority,
            "source": edge.source_node_id,
            "condition": _condition_payload(edge.condition),
        }
    )


def _terminal_identity(node: EvaluationNode) -> str:
    return _identity(
        {
            "node_id": node.node_id,
            "terminal_kind": node.terminal_kind.value if node.terminal_kind is not None else None,
        }
    )


def _loop_identity(loop: EvaluationLoop) -> str:
    return _identity(
        {
            "kind": loop.kind.value,
            "members": loop.member_node_ids,
            "repeat_group": loop.repeat_group_node_id,
        }
    )


def _count_metric(expected: Counter[str], actual: Counter[str]) -> CountMetric:
    matched = sum((expected & actual).values())
    expected_count = sum(expected.values())
    actual_count = sum(actual.values())
    return CountMetric(
        expected_count=expected_count,
        actual_count=actual_count,
        matched_count=matched,
        precision=matched / actual_count if actual_count else None,
        recall=matched / expected_count if expected_count else None,
    )


def _accuracy_metric(expected: Counter[str], actual: Counter[str]) -> AccuracyMetric:
    matched = sum((expected & actual).values())
    expected_count = sum(expected.values())
    actual_count = sum(actual.values())
    return AccuracyMetric(
        expected_count=expected_count,
        actual_count=actual_count,
        matched_count=matched,
        value=matched / expected_count if expected_count else None,
    )


def _rate_metric(count: int, total_count: int) -> RateMetric:
    return RateMetric(
        count=count,
        total_count=total_count,
        value=count / total_count if total_count else None,
    )


def _contains_opaque(condition: CanonicalRoutingCondition | None) -> bool:
    if condition is None:
        return False
    stack = [condition]
    while stack:
        current = stack.pop()
        if current.operator is ConditionOperator.opaque:
            return True
        if current.children is not None:
            stack.extend(current.children)
    return False


def _unresolved_edge_identity(route: UnresolvedRoute, ordinal: int) -> str:
    return _identity(
        {
            "condition": _condition_payload(route.condition),
            "kind": route.kind.value,
            "ordinal": ordinal,
            "priority": route.priority,
            "source": route.source_node_id,
            "target": None,
            "unresolved": True,
        }
    )


def _unresolved_target_identity(route: UnresolvedRoute, ordinal: int) -> str:
    return _identity(
        {
            "kind": route.kind.value,
            "ordinal": ordinal,
            "priority": route.priority,
            "source": route.source_node_id,
            "target": None,
            "unresolved": True,
        }
    )


def _stage_metrics(expected: EvaluationStage, actual: EvaluationStage) -> StageMetrics:
    expected_sources = {
        node.source_item_id for node in expected.nodes if node.source_item_id is not None
    }
    invented_sources = {
        node.source_item_id
        for node in actual.nodes
        if node.source_item_id is not None and node.source_item_id not in expected_sources
    }
    expected_conditions = Counter(
        _condition_identity(edge)
        for edge in expected.edges
        if edge.kind is EdgeKind.conditional and not _contains_opaque(edge.condition)
    )
    actual_conditions = Counter(
        _condition_identity(edge)
        for edge in actual.edges
        if edge.kind is EdgeKind.conditional and not _contains_opaque(edge.condition)
    )
    actual_edge_identities = Counter(_edge_identity(edge) for edge in actual.edges)
    actual_target_identities = Counter(_target_identity(edge) for edge in actual.edges)
    for ordinal, route in enumerate(actual.unresolved_routes):
        actual_edge_identities[_unresolved_edge_identity(route, ordinal)] += 1
        actual_target_identities[_unresolved_target_identity(route, ordinal)] += 1
    total_actual_routes = len(actual.edges) + len(actual.unresolved_routes)
    opaque_count = sum(_contains_opaque(edge.condition) for edge in actual.edges) + sum(
        _contains_opaque(route.condition) for route in actual.unresolved_routes
    )
    return StageMetrics(
        nodes=_count_metric(
            Counter(_node_identity(node) for node in expected.nodes),
            Counter(_node_identity(node) for node in actual.nodes),
        ),
        edges=_count_metric(
            Counter(_edge_identity(edge) for edge in expected.edges),
            actual_edge_identities,
        ),
        targets=_accuracy_metric(
            Counter(_target_identity(edge) for edge in expected.edges),
            actual_target_identities,
        ),
        conditions=_accuracy_metric(expected_conditions, actual_conditions),
        terminals=_accuracy_metric(
            Counter(_terminal_identity(node) for node in expected.nodes if node.terminal_kind),
            Counter(_terminal_identity(node) for node in actual.nodes if node.terminal_kind),
        ),
        loops=_accuracy_metric(
            Counter(_loop_identity(loop) for loop in expected.loops),
            Counter(_loop_identity(loop) for loop in actual.loops),
        ),
        unresolved_route_count=len(actual.unresolved_routes),
        unresolved_routes=_rate_metric(len(actual.unresolved_routes), total_actual_routes),
        opaque_conditions=_rate_metric(opaque_count, total_actual_routes),
        invented_source_id_count=len(invented_sources),
    )


def _delta(after: float | None, before: float | None) -> float | None:
    if after is None or before is None:
        return None
    return after - before


def _stage_digest(stage: EvaluationStage) -> str:
    payload = {
        "edges": sorted(_edge_identity(edge) for edge in stage.edges),
        "loops": sorted(_loop_identity(loop) for loop in stage.loops),
        "nodes": sorted(_node_identity(node) for node in stage.nodes),
        "unresolved": sorted(
            _identity(
                {
                    "condition": _condition_payload(route.condition),
                    "kind": route.kind.value,
                    "priority": route.priority,
                    "source": route.source_node_id,
                }
            )
            for route in stage.unresolved_routes
        ),
    }
    return hashlib.sha256(_identity(payload).encode("ascii")).hexdigest()


def _metric_complete(metric: CountMetric | AccuracyMetric) -> bool:
    if isinstance(metric, CountMetric):
        return (
            metric.expected_count == metric.actual_count == metric.matched_count
            and metric.precision in {None, 1.0}
            and metric.recall in {None, 1.0}
        )
    return (
        metric.expected_count == metric.actual_count == metric.matched_count
        and metric.value in {None, 1.0}
    )


def evaluate_bundle(
    bundle: EvaluationBundle,
    *,
    mechanics_manifest_sha256: str = "0" * 64,
    evaluation_fixture_sha256: str = "0" * 64,
) -> EvaluationReport:
    """Compare expected mechanics with first-pass and post-review snapshots."""
    first_pass = _stage_metrics(bundle.expected, bundle.first_pass)
    post_review = _stage_metrics(bundle.expected, bundle.post_review)
    review_effect = ReviewEffect(
        edge_precision_delta=_delta(post_review.edges.precision, first_pass.edges.precision),
        edge_recall_delta=_delta(post_review.edges.recall, first_pass.edges.recall),
        target_accuracy_delta=_delta(post_review.targets.value, first_pass.targets.value),
        condition_accuracy_delta=_delta(
            post_review.conditions.value,
            first_pass.conditions.value,
        ),
        terminal_accuracy_delta=_delta(
            post_review.terminals.value,
            first_pass.terminals.value,
        ),
        loop_accuracy_delta=_delta(post_review.loops.value, first_pass.loops.value),
        unresolved_rate_delta=_delta(
            post_review.unresolved_routes.value,
            first_pass.unresolved_routes.value,
        ),
        opaque_rate_delta=_delta(
            post_review.opaque_conditions.value,
            first_pass.opaque_conditions.value,
        ),
    )
    mechanics_passed = (
        bool(bundle.expected.nodes)
        and bool(bundle.expected.edges)
        and all(
            _metric_complete(metric)
            for metric in (
                post_review.nodes,
                post_review.edges,
                post_review.targets,
                post_review.conditions,
                post_review.terminals,
                post_review.loops,
            )
        )
        and post_review.unresolved_route_count == 0
        and post_review.invented_source_id_count == 0
        and first_pass.invented_source_id_count == 0
    )
    return EvaluationReport(
        schema_version=1,
        claim_scope=bundle.claim_scope,
        g6_status=bundle.g6_status,
        evaluator_version=EVALUATOR_VERSION,
        source_manifest_sha256=bundle.source_manifest_sha256,
        mechanics_manifest_sha256=mechanics_manifest_sha256,
        evaluation_fixture_sha256=evaluation_fixture_sha256,
        expected_sha256=_stage_digest(bundle.expected),
        first_pass_sha256=_stage_digest(bundle.first_pass),
        post_review_sha256=_stage_digest(bundle.post_review),
        first_pass=first_pass,
        post_review=post_review,
        review_effect=review_effect,
        mechanics_passed=mechanics_passed,
    )


def _scale_stage(node_count: int, edge_count: int) -> EvaluationStage:
    if node_count < 2:
        raise ValueError("scale evidence requires at least two nodes")
    maximum_edges = node_count * (node_count - 1) // 2
    if edge_count < node_count - 1 or edge_count > maximum_edges:
        raise ValueError("scale edge count must fit the deterministic acyclic graph")
    nodes = tuple(
        EvaluationNode(
            node_id=f"n{index:04d}",
            source_item_id=f"Q{index:04d}" if 0 < index < node_count - 1 else None,
            kind=(
                NodeKind.entry
                if index == 0
                else NodeKind.terminal
                if index == node_count - 1
                else NodeKind.question
            ),
            terminal_kind=(TerminalKind.survey_complete if index == node_count - 1 else None),
        )
        for index in range(node_count)
    )
    pairs = [(index, index + 1) for index in range(node_count - 1)]
    distance = 2
    while len(pairs) < edge_count:
        for source in range(node_count - distance):
            pairs.append((source, source + distance))
            if len(pairs) == edge_count:
                break
        distance += 1
    edges = tuple(
        EvaluationEdge(
            source_node_id=f"n{source:04d}",
            target_node_id=f"n{target:04d}",
            kind=EdgeKind.unconditional,
            condition=None,
            priority=None,
        )
        for source, target in pairs
    )
    return EvaluationStage(nodes=nodes, edges=edges, loops=(), unresolved_routes=())


def run_scale_evidence(*, node_count: int, edge_count: int) -> ScaleEvidence:
    """Measure two independent iterative mechanics builds and one full score.

    Args:
        node_count: Number of nodes in each generated stage.
        edge_count: Number of directed edges in each generated stage.

    Returns:
        Hardware, timing, memory, counts, and semantic determinism evidence.

    Raises:
        ValueError: Counts are not strict integers or cannot form the graph.
    """
    if type(node_count) is not int or type(edge_count) is not int:
        raise ValueError("scale counts must be strict integers")
    tracemalloc.start()
    started = perf_counter()
    first_stage = _scale_stage(node_count, edge_count)
    second_stage = _scale_stage(node_count, edge_count)
    report = evaluate_bundle(
        EvaluationBundle(
            schema_version=1,
            artifact_kind="deterministic-routing-quality",
            benchmark_eligible=False,
            claim_scope="deterministic-mechanics-only",
            g6_status="not_run",
            source_manifest_sha256="0" * 64,
            source_fixture_ids=("synthetic-scale",),
            expected=first_stage,
            first_pass=second_stage,
            post_review=second_stage,
        )
    )
    first_digest = _stage_digest(first_stage)
    second_digest = _stage_digest(second_stage)
    duration_seconds = perf_counter() - started
    _current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return ScaleEvidence(
        schema_version=1,
        node_count=len(first_stage.nodes),
        edge_count=len(first_stage.edges),
        semantic_sha256=first_digest,
        deterministic=first_digest == second_digest and report.mechanics_passed,
        platform=platform.platform(),
        machine=platform.machine() or "not reported",
        processor=platform.processor() or "not reported",
        python=platform.python_version(),
        duration_seconds=duration_seconds,
        peak_bytes=peak_bytes,
        timer_method="time.perf_counter",
        peak_memory_method="tracemalloc traced Python allocations",
    )


def _resolve_mechanics_path(value: object, root: Path) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("evaluation fixture path must be a nonempty string")
    if "\\" in value:
        raise ValueError("evaluation fixture path must use forward slashes")
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or "." in relative.parts
        or ".." in relative.parts
        or not relative.is_relative_to(MECHANICS_ROOT)
        or relative.suffix != ".json"
    ):
        raise ValueError("evaluation fixture path must stay in routing_mechanics")
    candidate = root.joinpath(*relative.parts)
    if candidate.is_symlink() or any(parent.is_symlink() for parent in candidate.parents):
        raise ValueError("evaluation fixture path must not use symlinks")
    return candidate


def load_evaluation_bundle(
    mechanics_manifest: Path = DEFAULT_MECHANICS_MANIFEST,
    *,
    repository_root: Path | None = None,
    source_manifest: Path = DEFAULT_SOURCE_MANIFEST,
) -> EvaluationBundle:
    """Load one checksummed synthetic mechanics bundle fail-closed.

    Args:
        mechanics_manifest: Repository-relative canonical manifest path.
        repository_root: Repository root override used by tests.
        source_manifest: Validated synthetic source manifest bound to the bundle.

    Returns:
        Strict validated evaluation bundle.

    Raises:
        OSError: A required manifest or fixture cannot be read.
        ValueError: A policy, path, checksum, or JSON boundary is invalid.
    """
    root = (repository_root or REPOSITORY_ROOT).resolve()
    manifest_path = (
        mechanics_manifest if mechanics_manifest.is_absolute() else root / mechanics_manifest
    )
    expected_manifest = root / DEFAULT_MECHANICS_MANIFEST
    if manifest_path.absolute() != expected_manifest:
        raise ValueError("mechanics manifest path must use the repository fixture")
    if manifest_path.is_symlink():
        raise ValueError("mechanics manifest must not be a symlink")
    with manifest_path.open("rb") as stream:
        manifest = MechanicsManifest.model_validate(tomllib.load(stream))
    fixture_path = _resolve_mechanics_path(manifest.evaluation.path, root)
    content = fixture_path.read_bytes()
    if hashlib.sha256(content).hexdigest() != manifest.evaluation.sha256:
        raise ValueError("evaluation fixture checksum mismatch")
    bundle = EvaluationBundle.model_validate(_load_json_without_duplicates(content))
    source_path = source_manifest if source_manifest.is_absolute() else root / source_manifest
    source_content = source_path.read_bytes()
    source_data = tomllib.loads(source_content.decode("utf-8"))
    fixtures = source_data.get("fixtures")
    if not isinstance(fixtures, list):
        raise ValueError("source manifest fixture binding is invalid")
    fixture_ids = tuple(
        fixture.get("id")
        for fixture in fixtures
        if isinstance(fixture, dict) and isinstance(fixture.get("id"), str)
    )
    if hashlib.sha256(source_content).hexdigest() != bundle.source_manifest_sha256:
        raise ValueError("source manifest checksum does not match the evaluation bundle")
    if fixture_ids != bundle.source_fixture_ids:
        raise ValueError("source manifest fixtures do not match the evaluation bundle")
    return bundle


def _load_json_without_duplicates(content: bytes) -> object:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("evaluation fixture contains duplicate JSON fields")
            result[key] = value
        return result

    return json.loads(content, object_pairs_hook=reject_duplicates)


def _json_bytes(value: StrictRoutingModel) -> bytes:
    return (
        json.dumps(value.model_dump(mode="json"), ensure_ascii=True, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _validated_report_path(path: Path) -> Path:
    resolved = path.absolute()
    if resolved.suffix != ".json":
        raise ValueError("routing evaluation reports must use a JSON suffix")
    if resolved.is_symlink():
        raise ValueError("routing evaluation reports must not use symlinks")
    repository_root = REPOSITORY_ROOT.resolve()
    if resolved.is_relative_to(repository_root):
        allowed_root = repository_root.joinpath(*REPORT_ROOT.parts)
        if not resolved.is_relative_to(allowed_root):
            raise ValueError("repository reports must stay in the routing evaluation cache")
        resolved.parent.mkdir(parents=True, exist_ok=True)
    elif not resolved.parent.is_dir():
        raise ValueError("external report directories must already exist")
    if any(parent.is_symlink() for parent in resolved.parents if parent != Path(resolved.anchor)):
        raise ValueError("routing evaluation report parents must not use symlinks")
    return resolved


def _write_reports(
    report_path: Path,
    report: EvaluationReport,
    scale_path: Path,
    scale: ScaleEvidence,
) -> None:
    report_target = _validated_report_path(report_path)
    scale_target = _validated_report_path(scale_path)
    if report_target == scale_target:
        raise ValueError("mechanics and scale reports require distinct paths")
    payloads = (
        (scale_target, _json_bytes(scale)),
        (report_target, _json_bytes(report)),
    )
    temporary_paths: list[Path] = []
    try:
        for target, content in payloads:
            with tempfile.NamedTemporaryFile(
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
                temporary_paths.append(Path(stream.name))
        for (target, _content), temporary in zip(payloads, temporary_paths, strict=True):
            os.replace(temporary, target)
    finally:
        for temporary in temporary_paths:
            temporary.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    """Build the deterministic repository evaluator parser.

    Returns:
        Parser for source validation, mechanics reports, and scale reports.
    """
    parser = argparse.ArgumentParser(
        description="Evaluate synthetic questionnaire-routing mechanics without provider access."
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_SOURCE_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--scale-output", type=Path, default=DEFAULT_SCALE_REPORT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run deterministic mechanics and scale evaluation.

    Args:
        argv: Arguments without the executable name, or process arguments when omitted.

    Returns:
        Zero only when source validation, mechanics, and scale checks pass.
    """
    args = build_parser().parse_args(argv)
    logger.remove()
    logger.add(sys.stderr, format="{message}")
    try:
        source_errors = validate_source_manifest(args.manifest, repository_root=REPOSITORY_ROOT)
        if source_errors:
            logger.error("Routing source manifest validation failed")
            return 1
        bundle = load_evaluation_bundle(
            repository_root=REPOSITORY_ROOT,
            source_manifest=args.manifest,
        )
        mechanics_content = (REPOSITORY_ROOT / DEFAULT_MECHANICS_MANIFEST).read_bytes()
        mechanics_data = MechanicsManifest.model_validate(tomllib.loads(mechanics_content.decode()))
        evaluation_content = _resolve_mechanics_path(
            mechanics_data.evaluation.path,
            REPOSITORY_ROOT,
        ).read_bytes()
        report = evaluate_bundle(
            bundle,
            mechanics_manifest_sha256=hashlib.sha256(mechanics_content).hexdigest(),
            evaluation_fixture_sha256=hashlib.sha256(evaluation_content).hexdigest(),
        )
        scale = run_scale_evidence(node_count=1_000, edge_count=3_000)
        _write_reports(args.output, report, args.scale_output, scale)
    except (OSError, ValueError, tomllib.TOMLDecodeError):
        logger.error("Routing mechanics evaluation failed safely")
        return 1
    passed = report.mechanics_passed and scale.deterministic
    if passed:
        logger.info("Routing mechanics evaluation passed without provider access")
        return 0
    logger.error("Routing mechanics evaluation failed safely")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
