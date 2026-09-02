"""Deterministic routing-quality evaluator tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.evaluate_routing import (
    EvaluationBundle,
    EvaluationEdge,
    EvaluationLoop,
    EvaluationNode,
    EvaluationStage,
    MechanicsManifest,
    UnresolvedRoute,
    evaluate_bundle,
    load_evaluation_bundle,
    main,
    run_scale_evidence,
)
from survey_scribe.models.routing import EdgeKind, LoopKind, TerminalKind
from survey_scribe.routing.contracts import CanonicalRoutingCondition, ConditionOperator, NodeKind


def _condition(value: str | int | bool, *, raw_text: str) -> CanonicalRoutingCondition:
    return CanonicalRoutingCondition(
        operator=ConditionOperator.equals,
        question_node_id="Q1",
        value=value,
        values=None,
        children=None,
        raw_text=raw_text,
    )


def _nodes(*, invented: bool = False) -> tuple[EvaluationNode, ...]:
    return (
        EvaluationNode(
            node_id="ENTRY",
            source_item_id=None,
            kind=NodeKind.entry,
            terminal_kind=None,
        ),
        EvaluationNode(
            node_id="Q1",
            source_item_id="Q1",
            kind=NodeKind.question,
            terminal_kind=None,
        ),
        EvaluationNode(
            node_id="Q2",
            source_item_id="INVENTED" if invented else "Q2",
            kind=NodeKind.question,
            terminal_kind=None,
        ),
        EvaluationNode(
            node_id="END",
            source_item_id=None,
            kind=NodeKind.terminal,
            terminal_kind=TerminalKind.survey_complete,
        ),
    )


def _edge(
    source: str = "Q1",
    target: str = "Q2",
    *,
    condition: CanonicalRoutingCondition | None = None,
    kind: EdgeKind = EdgeKind.conditional,
    priority: int | None = 1,
) -> EvaluationEdge:
    return EvaluationEdge(
        source_node_id=source,
        target_node_id=target,
        kind=kind,
        condition=condition or _condition("yes", raw_text="expected prose"),
        priority=priority,
    )


def _stage(
    *,
    nodes: tuple[EvaluationNode, ...] | None = None,
    edges: tuple[EvaluationEdge, ...] = (),
    loops: tuple[EvaluationLoop, ...] = (),
    unresolved: tuple[UnresolvedRoute, ...] = (),
) -> EvaluationStage:
    return EvaluationStage(
        nodes=nodes if nodes is not None else _nodes(),
        edges=edges,
        loops=loops,
        unresolved_routes=unresolved,
    )


def _bundle(
    expected: EvaluationStage,
    first_pass: EvaluationStage,
    post_review: EvaluationStage,
) -> EvaluationBundle:
    return EvaluationBundle(
        schema_version=1,
        artifact_kind="deterministic-routing-quality",
        benchmark_eligible=False,
        claim_scope="deterministic-mechanics-only",
        g6_status="not_run",
        source_manifest_sha256="0" * 64,
        source_fixture_ids=("synthetic-case",),
        expected=expected,
        first_pass=first_pass,
        post_review=post_review,
    )


def test_exact_match_ignores_raw_condition_text_and_separates_stages() -> None:
    expected_edge = _edge(condition=_condition("yes", raw_text="PRIVATE_EXPECTED_SENTINEL"))
    actual_edge = _edge(condition=_condition("yes", raw_text="PRIVATE_ACTUAL_SENTINEL"))
    expected = _stage(edges=(expected_edge,))
    first_pass = _stage()
    post_review = _stage(edges=(actual_edge,))

    report = evaluate_bundle(_bundle(expected, first_pass, post_review))

    assert report.first_pass.edges.recall == 0.0
    assert report.first_pass.targets.value == 0.0
    assert report.post_review.edges.precision == 1.0
    assert report.post_review.edges.recall == 1.0
    assert report.post_review.conditions.value == 1.0
    assert report.review_effect.edge_recall_delta == 1.0
    assert report.review_effect.target_accuracy_delta == 1.0
    assert report.mechanics_passed is True
    serialized = report.model_dump_json()
    assert "PRIVATE_EXPECTED_SENTINEL" not in serialized
    assert "PRIVATE_ACTUAL_SENTINEL" not in serialized


def test_multigraph_scoring_penalizes_missing_extra_reversed_and_parallel_edges() -> None:
    edge = _edge()
    expected = _stage(edges=(edge, edge))
    actual = _stage(
        edges=(
            edge,
            _edge(source="Q2", target="Q1"),
            _edge(target="END"),
        )
    )

    metrics = evaluate_bundle(_bundle(expected, actual, actual)).first_pass

    assert metrics.edges.expected_count == 2
    assert metrics.edges.actual_count == 3
    assert metrics.edges.matched_count == 1
    assert metrics.edges.precision == pytest.approx(1 / 3)
    assert metrics.edges.recall == 0.5
    assert metrics.targets.value == 0.5


def test_condition_ast_is_type_strict_and_unresolved_routes_are_penalties() -> None:
    expected = _stage(edges=(_edge(condition=_condition(1, raw_text="one")),))
    unresolved = UnresolvedRoute(
        source_node_id="Q1",
        kind=EdgeKind.conditional,
        condition=_condition(1, raw_text="unresolved"),
        priority=1,
    )
    actual = _stage(
        edges=(_edge(condition=_condition(True, raw_text="boolean")),),
        unresolved=(unresolved,),
    )

    metrics = evaluate_bundle(_bundle(expected, actual, actual)).first_pass

    assert metrics.edges.matched_count == 0
    assert metrics.conditions.value == 0.0
    assert metrics.targets.value == 1.0
    assert metrics.targets.actual_count == 2
    assert metrics.unresolved_route_count == 1


def test_target_and_condition_metrics_are_independent() -> None:
    expected_edge = _edge(condition=_condition("yes", raw_text="expected"))
    wrong_condition = _edge(condition=_condition("no", raw_text="wrong condition"))
    wrong_target = _edge(target="END", condition=_condition("yes", raw_text="same condition"))
    expected = _stage(edges=(expected_edge,))

    condition_report = evaluate_bundle(
        _bundle(expected, _stage(edges=(wrong_condition,)), _stage(edges=(wrong_condition,)))
    )
    target_report = evaluate_bundle(
        _bundle(expected, _stage(edges=(wrong_target,)), _stage(edges=(wrong_target,)))
    )

    assert condition_report.post_review.targets.value == 1.0
    assert condition_report.post_review.conditions.value == 0.0
    assert target_report.post_review.targets.value == 0.0
    assert target_report.post_review.conditions.value == 1.0


def test_commutative_conditions_normalize_and_opaque_conditions_do_not_collapse() -> None:
    yes = _condition("yes", raw_text="yes")
    no = _condition("no", raw_text="no")
    expected_all = CanonicalRoutingCondition(
        operator=ConditionOperator.all,
        question_node_id=None,
        value=None,
        values=None,
        children=(yes, no),
        raw_text="yes and no",
    )
    reordered_all = expected_all.model_copy(update={"children": (no, yes)})
    expected = _stage(edges=(_edge(condition=expected_all),))
    reordered = _stage(edges=(_edge(condition=reordered_all),))

    assert evaluate_bundle(_bundle(expected, reordered, reordered)).mechanics_passed is True

    opaque_a = CanonicalRoutingCondition(
        operator=ConditionOperator.opaque,
        question_node_id=None,
        value=None,
        values=None,
        children=None,
        raw_text="custom rule A",
    )
    opaque_b = opaque_a.model_copy(update={"raw_text": "custom rule B"})
    opaque_report = evaluate_bundle(
        _bundle(
            _stage(edges=(_edge(condition=opaque_a),)),
            _stage(edges=(_edge(condition=opaque_b),)),
            _stage(edges=(_edge(condition=opaque_b),)),
        )
    )
    assert opaque_report.post_review.edges.matched_count == 0
    assert opaque_report.post_review.conditions.value is None
    assert opaque_report.post_review.opaque_conditions.value == 1.0


def test_unresolved_routes_reduce_precision_and_report_a_rate() -> None:
    edge = _edge()
    unresolved = UnresolvedRoute(
        source_node_id="Q1",
        kind=EdgeKind.conditional,
        condition=_condition("no", raw_text="unresolved"),
        priority=2,
    )
    expected = _stage(edges=(edge,))
    actual = _stage(edges=(edge,), unresolved=(unresolved,))

    metrics = evaluate_bundle(_bundle(expected, actual, actual)).post_review

    assert metrics.edges.precision == 0.5
    assert metrics.edges.recall == 1.0
    assert metrics.targets.actual_count == 2
    assert metrics.unresolved_routes.value == 0.5
    assert evaluate_bundle(_bundle(expected, actual, actual)).mechanics_passed is False


def test_terminal_loop_and_invented_source_id_checks_are_explicit() -> None:
    loop = EvaluationLoop(
        kind=LoopKind.correction_return,
        repeat_group_node_id=None,
        member_node_ids=("Q1", "Q2"),
    )
    loop_edges = (
        EvaluationEdge(
            source_node_id="Q1",
            target_node_id="Q2",
            kind=EdgeKind.unconditional,
            condition=None,
            priority=None,
        ),
        EvaluationEdge(
            source_node_id="Q2",
            target_node_id="Q1",
            kind=EdgeKind.unconditional,
            condition=None,
            priority=None,
        ),
    )
    expected = _stage(edges=loop_edges, loops=(loop,))
    actual_nodes = tuple(
        node.model_copy(
            update={"terminal_kind": TerminalKind.screened_out} if node.node_id == "END" else {}
        )
        for node in _nodes(invented=True)
    )
    actual = _stage(nodes=actual_nodes, edges=loop_edges)

    report = evaluate_bundle(_bundle(expected, actual, actual))

    assert report.first_pass.terminals.value == 0.0
    assert report.first_pass.loops.value == 0.0
    assert report.first_pass.invented_source_id_count == 1
    assert report.mechanics_passed is False


def test_extra_loop_classification_fails_mechanics_completion() -> None:
    expected_loop = EvaluationLoop(
        kind=LoopKind.correction_return,
        repeat_group_node_id=None,
        member_node_ids=("Q1", "Q2"),
    )
    extra_loop = EvaluationLoop(
        kind=LoopKind.other,
        repeat_group_node_id=None,
        member_node_ids=("Q1", "Q2"),
    )
    loop_edges = (
        EvaluationEdge(
            source_node_id="Q1",
            target_node_id="Q2",
            kind=EdgeKind.unconditional,
            condition=None,
            priority=None,
        ),
        EvaluationEdge(
            source_node_id="Q2",
            target_node_id="Q1",
            kind=EdgeKind.unconditional,
            condition=None,
            priority=None,
        ),
    )
    expected = _stage(edges=loop_edges, loops=(expected_loop,))
    actual = _stage(edges=loop_edges, loops=(expected_loop, extra_loop))

    report = evaluate_bundle(_bundle(expected, actual, actual))

    assert report.post_review.loops.expected_count == 1
    assert report.post_review.loops.actual_count == 2
    assert report.post_review.loops.matched_count == 1
    assert report.mechanics_passed is False


def test_condition_references_must_identify_known_nodes() -> None:
    unknown = _condition("yes", raw_text="unknown").model_copy(
        update={"question_node_id": "UNKNOWN"}
    )

    with pytest.raises(ValueError, match="condition must reference known nodes"):
        _stage(edges=(_edge(condition=unknown),))


def test_stage_rejects_terminal_outgoing_and_duplicate_default_edges() -> None:
    terminal_edge = EvaluationEdge(
        source_node_id="END",
        target_node_id="Q1",
        kind=EdgeKind.unconditional,
        condition=None,
        priority=None,
    )
    with pytest.raises(ValueError, match="terminal nodes cannot have outgoing"):
        _stage(edges=(terminal_edge,))

    default = EvaluationEdge(
        source_node_id="Q1",
        target_node_id="END",
        kind=EdgeKind.default,
        condition=None,
        priority=1,
    )
    with pytest.raises(ValueError, match="at most one default"):
        _stage(edges=(default, default))


def test_bundle_policy_uses_strict_primitives() -> None:
    empty = EvaluationStage(nodes=(), edges=(), loops=(), unresolved_routes=())
    payload = _bundle(empty, empty, empty).model_dump(mode="python")
    payload["schema_version"] = True

    with pytest.raises(ValueError):
        EvaluationBundle.model_validate(payload)


def test_mechanics_manifest_rejects_unknown_policy_fields() -> None:
    payload = {
        "schema_version": 1,
        "artifact_kind": "deterministic-routing-mechanics",
        "benchmark_eligible": False,
        "identity_schema": "routing-node-fallback-v1",
        "source_conversion_schema_version": "1.0",
        "purpose": "Freeze deterministic inventory, identity, containment, variable-link, and partial-output mechanics.",
        "provenance": "Generated only from repository-authored synthetic normalized blocks and fixed SVIS records; no model response was used.",
        "restrictions": "Mechanics regression testing only; not approved for model-quality benchmarking.",
        "output": {"path": "tests/fixtures/routing_mechanics/output.json", "sha256": "0" * 64},
        "evaluation": {
            "path": "tests/fixtures/routing_mechanics/evaluation.json",
            "sha256": "0" * 64,
        },
        "unexpected": True,
    }

    with pytest.raises(ValueError):
        MechanicsManifest.model_validate(payload)


@pytest.mark.parametrize(
    ("first_edges", "post_edges", "expected_delta"),
    [
        ((), (_edge(),), 1.0),
        ((_edge(),), (), -1.0),
        ((_edge(),), (_edge(),), 0.0),
    ],
)
def test_review_effect_reports_improvement_degradation_and_no_change(
    first_edges: tuple[EvaluationEdge, ...],
    post_edges: tuple[EvaluationEdge, ...],
    expected_delta: float,
) -> None:
    expected = _stage(edges=(_edge(),))

    report = evaluate_bundle(_bundle(expected, _stage(edges=first_edges), _stage(edges=post_edges)))

    assert report.review_effect.edge_recall_delta == expected_delta


def test_zero_denominators_are_unavailable_instead_of_nan_or_perfect() -> None:
    empty = _stage()

    metrics = evaluate_bundle(_bundle(empty, empty, empty)).first_pass

    assert metrics.edges.precision is None
    assert metrics.edges.recall is None
    assert metrics.targets.value is None
    assert metrics.conditions.value is None
    assert metrics.loops.value is None
    assert evaluate_bundle(_bundle(empty, empty, empty)).mechanics_passed is False


def test_committed_bundle_is_checksummed_and_cli_writes_content_safe_reports(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    mechanics_manifest = repository_root / "tests/fixtures/routing_mechanics/manifest.toml"
    bundle = load_evaluation_bundle(mechanics_manifest, repository_root=repository_root)
    assert bundle.benchmark_eligible is False
    assert bundle.g6_status == "not_run"

    report_path = tmp_path / "routing-evaluation.json"
    scale_path = tmp_path / "routing-scale.json"
    result = main(
        [
            "--manifest",
            str(repository_root / "tests/fixtures/routing/manifest.toml"),
            "--output",
            str(report_path),
            "--scale-output",
            str(scale_path),
        ]
    )

    assert result == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    scale = json.loads(scale_path.read_text(encoding="utf-8"))
    assert report["mechanics_passed"] is True
    assert report["g6_status"] == "not_run"
    assert report["claim_scope"] == "deterministic-mechanics-only"
    assert report["source_manifest_sha256"] == bundle.source_manifest_sha256
    assert report["evaluation_fixture_sha256"] == (
        hashlib.sha256(
            (
                repository_root / "tests/fixtures/routing_mechanics/routing-evaluation-v1.json"
            ).read_bytes()
        ).hexdigest()
    )
    assert scale["node_count"] == 1_000
    assert scale["edge_count"] == 3_000
    assert scale["deterministic"] is True
    assert "source_quote" not in report_path.read_text(encoding="utf-8")


def test_cli_rejects_aliased_and_protected_report_paths(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    common = [
        "--manifest",
        str(repository_root / "tests/fixtures/routing/manifest.toml"),
    ]
    same_path = tmp_path / "same.json"

    assert (
        main(
            [
                *common,
                "--output",
                str(same_path),
                "--scale-output",
                str(same_path),
            ]
        )
        == 1
    )
    assert not same_path.exists()

    protected = repository_root / "roadmap.json"
    before = protected.read_bytes()
    assert (
        main(
            [
                *common,
                "--output",
                str(protected),
                "--scale-output",
                str(tmp_path / "scale.json"),
            ]
        )
        == 1
    )
    assert protected.read_bytes() == before


def test_scale_evidence_is_deterministic_and_has_no_timing_threshold() -> None:
    evidence = run_scale_evidence(node_count=1_000, edge_count=3_000)

    assert evidence.node_count == 1_000
    assert evidence.edge_count == 3_000
    assert evidence.deterministic is True
    assert len(evidence.semantic_sha256) == 64
    assert evidence.duration_seconds > 0
    assert evidence.peak_bytes > 0
    assert "threshold" not in type(evidence).model_fields
