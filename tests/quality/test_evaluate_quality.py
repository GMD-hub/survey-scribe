"""Tests for the authoritative offline quality evaluation."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, cast

from scripts.evaluate_quality import evaluate, main


def test_quality_command_names_every_threshold_and_baseline(
    repository_root: Path, tmp_path: Path
) -> None:
    output = tmp_path / "quality.json"

    assert main(["--offline", "--output", str(output)]) == 0

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["passed"] is True
    assert set(report["metrics"]) == {
        "dense_repeated_table_recall",
        "exact_schema_compatibility",
        "field_accuracy",
        "variable_recall",
    }
    assert all(metric["baseline"] for metric in report["metrics"].values())
    assert report["metrics"]["exact_schema_compatibility"]["threshold"] == 1.0
    assert report["metrics"]["variable_recall"]["available"] is False
    routing = report["routing_mechanics"]
    assert routing["evaluator"]["implementation"] == "scripts/evaluate_routing.py"
    assert routing["evaluator"]["version"] == "1.1"
    assert routing["source_fixture_ids"]
    assert routing["source_fixture_ids"] == [
        fixture["id"] for fixture in routing["source_fixtures"]
    ]
    assert all(
        fixture["sha256"]
        == hashlib.sha256((repository_root / fixture["path"]).read_bytes()).hexdigest()
        for fixture in routing["source_fixtures"]
    )
    assert set(routing["input_digests"]) == {
        "evaluation_fixture_sha256",
        "expected_sha256",
        "first_pass_sha256",
        "mechanics_manifest_sha256",
        "post_review_sha256",
        "source_manifest_sha256",
    }
    assert all(
        len(value) == 64 and value != "0" * 64 for value in routing["input_digests"].values()
    )
    assert (
        routing["input_digests"]["source_manifest_sha256"]
        == hashlib.sha256((repository_root / routing["source_manifest"]).read_bytes()).hexdigest()
    )
    assert (
        routing["input_digests"]["evaluation_fixture_sha256"]
        == hashlib.sha256(
            (repository_root / routing["evaluation_fixture"]).read_bytes()
        ).hexdigest()
    )
    assert set(routing["metrics"]) == {"first_pass", "post_review", "review_effect"}


def test_quality_regression_fails_the_authoritative_result(repository_root: Path) -> None:
    def regressed_loader(path: Path) -> object:
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["survey_name"] = "Regressed value"
        return payload

    report = evaluate(
        Path("tests/fixtures/golden/manifest.toml"),
        Path("tests/fixtures/golden/quality-thresholds.toml"),
        repository_root=repository_root,
        actual_loader=regressed_loader,
    )

    metrics = cast(dict[str, dict[str, Any]], report["metrics"])
    exact = metrics["exact_schema_compatibility"]
    assert exact["value"] == 0.0
    assert exact["passed"] is False
    assert report["passed"] is False


def test_quality_regression_detects_field_order_and_scalar_type(repository_root: Path) -> None:
    def reordered_loader(path: Path) -> object:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {key: payload[key] for key in reversed(payload)}

    report = evaluate(
        Path("tests/fixtures/golden/manifest.toml"),
        Path("tests/fixtures/golden/quality-thresholds.toml"),
        repository_root=repository_root,
        actual_loader=reordered_loader,
    )

    metrics = cast(dict[str, dict[str, Any]], report["metrics"])
    assert metrics["exact_schema_compatibility"]["passed"] is False


def test_real_corpus_metrics_use_bound_source_output_and_independent_judgments(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    root = tmp_path / "repository"
    golden = root / "tests/fixtures/golden"
    golden.mkdir(parents=True)
    shutil.copytree(repository_root / "tests/fixtures/routing", root / "tests/fixtures/routing")
    for relative in (
        "tests/fixtures/routing_mechanics/manifest.toml",
        "tests/fixtures/routing_mechanics/routing-evaluation-v1.json",
    ):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repository_root / relative, target)
    source = golden / "approved-source.txt"
    source.write_text("approved sanitized source", encoding="utf-8")
    expected = {
        "schema_version": 1,
        "source_fixture_id": "approved-source",
        "actual_output": {
            "survey_name": "Expected survey",
            "country_code": "TST",
            "variables": [
                {"raw_name": "row_1", "label": "Expected first"},
                {"raw_name": "row_2", "label": "Expected second"},
                {"raw_name": "other", "label": "Other"},
            ],
        },
        "judgments": {
            "variable_ids": ["row_1", "row_2", "other", "missing"],
            "fields": [
                {"path": "/survey_name", "expected": "Expected survey"},
                {"path": "/country_code", "expected": "TST"},
                {"path": "/variables/0/label", "expected": "Expected first"},
                {"path": "/variables/1/label", "expected": "Expected second"},
            ],
            "dense_repeated_tables": [{"id": "roster", "row_variable_ids": ["row_1", "row_2"]}],
        },
    }
    output = golden / "approved-output.json"
    output.write_text(json.dumps(expected), encoding="utf-8")
    relative_source = source.relative_to(root).as_posix()
    relative_output = output.relative_to(root).as_posix()
    manifest = golden / "manifest.toml"
    fixture_common = (
        'rights_basis = "approved-sanitized"\n'
        'restrictions = "Approved local quality test."\n'
        'creator = "Quality test"\n'
        'purpose = "Verify real quality metric bindings."\n'
        'provenance = "Sanitized test fixture."\n'
        'approval_reference = "quality-test"\n'
        'approval_date = "2026-09-04"\n'
        'field_judgments = "Explicit JSON judgments."\n'
        'provider = "recorded"\n'
        'model = "recorded-model"\n'
        'prompt_version = "recorded-v1"\n'
        'approver = "Quality owner"\n'
        'sanitization_reference = "quality-test-sanitization"\n'
    )
    manifest.write_text(
        'schema_version = 1\ncorpus_status = "approved-sanitized"\n\n'
        '[[fixtures]]\nid = "approved-source"\n'
        f'path = "{relative_source}"\nkind = "sanitized-source"\n'
        f"{fixture_common}"
        f'sha256 = "{hashlib.sha256(source.read_bytes()).hexdigest()}"\n'
        'expected_variable_count = 4\noutput_fixture_id = "approved-output"\n\n'
        '[[fixtures]]\nid = "approved-output"\n'
        f'path = "{relative_output}"\nkind = "sanitized-output"\n'
        f"{fixture_common}"
        f'sha256 = "{hashlib.sha256(output.read_bytes()).hexdigest()}"\n'
        'expected_variable_count = 4\nsource_fixture_id = "approved-source"\n',
        encoding="utf-8",
    )
    thresholds = golden / "thresholds.toml"
    thresholds.write_text(
        "schema_version = 1\n"
        "[metrics]\n"
        "exact_schema_compatibility = 1.0\n"
        "variable_recall = 0.95\n"
        "field_accuracy = 0.95\n"
        "dense_repeated_table_recall = 0.95\n"
        "[baselines]\n"
        'exact_schema_compatibility = "golden:none"\n'
        'variable_recall = "approved:approved-source"\n'
        'field_accuracy = "approved:approved-source"\n'
        'dense_repeated_table_recall = "approved:approved-source"\n'
        "[availability]\nsynthetic_mechanics = true\napproved_real_corpus = true\n"
        'reason = "Approved sanitized pair is committed."\n',
        encoding="utf-8",
    )

    def independently_regressed_loader(path: Path) -> object:
        if path == source:
            actual = expected["actual_output"].copy()
            actual["survey_name"] = "Wrong survey"
            actual["variables"] = [
                {"raw_name": "row_1", "label": "Expected first"},
                {"raw_name": "row_2", "label": "Wrong second"},
                {"raw_name": "other", "label": "Other"},
            ]
            return actual
        return json.loads(path.read_text(encoding="utf-8"))

    report = evaluate(
        manifest.relative_to(root),
        thresholds.relative_to(root),
        repository_root=root,
        actual_loader=independently_regressed_loader,
    )

    metrics = cast(dict[str, dict[str, Any]], report["metrics"])
    assert metrics["exact_schema_compatibility"]["available"] is False
    assert metrics["variable_recall"]["value"] == 0.75
    assert metrics["field_accuracy"]["value"] == 0.5
    assert metrics["dense_repeated_table_recall"]["value"] == 1.0
    assert report["corpus_evidence"] == [
        {
            "source_fixture_id": "approved-source",
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "output_fixture_id": "approved-output",
            "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        }
    ]
