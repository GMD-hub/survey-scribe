"""Evaluate approved golden quality baselines without network access."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import tempfile
import tomllib
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

from loguru import logger

from survey_scribe.models.svis import SurveySVIS
from survey_scribe.serialization.legacy import legacy_payload

if __package__:
    from scripts.evaluate_routing import (
        DEFAULT_MECHANICS_MANIFEST,
        DEFAULT_SOURCE_MANIFEST,
        evaluate_repository_bundle,
    )
    from scripts.validate_golden_manifest import validate
else:
    from evaluate_routing import (
        DEFAULT_MECHANICS_MANIFEST,
        DEFAULT_SOURCE_MANIFEST,
        evaluate_repository_bundle,
    )
    from validate_golden_manifest import validate

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = Path("tests/fixtures/golden/manifest.toml")
DEFAULT_THRESHOLDS = Path("tests/fixtures/golden/quality-thresholds.toml")
DEFAULT_OUTPUT = Path(".cache/quality/evaluation.json")
REPORT_SCHEMA_VERSION = 2


def _deny_network(*_args: object, **_kwargs: object) -> None:
    raise RuntimeError("network access is blocked during quality evaluation")


@contextmanager
def network_blocked():
    """Block Python socket connections while deterministic evaluation runs."""
    create_connection = socket.create_connection
    connect = socket.socket.connect
    connect_ex = socket.socket.connect_ex
    socket.create_connection = _deny_network
    socket.socket.connect = _deny_network  # type: ignore[method-assign]
    socket.socket.connect_ex = _deny_network  # type: ignore[method-assign,assignment]
    try:
        yield
    finally:
        socket.create_connection = create_connection
        socket.socket.connect = connect  # type: ignore[method-assign]
        socket.socket.connect_ex = connect_ex  # type: ignore[method-assign,assignment]


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as stream:
        return tomllib.load(stream)


def _ratio(matched: int, expected: int) -> float | None:
    return matched / expected if expected else None


def _field_accuracy(expected: object, actual: object) -> tuple[int, int]:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return 0, len(expected)
        matched = 0
        total = 0
        for key, value in expected.items():
            child_matched, child_total = _field_accuracy(value, actual.get(key))
            matched += child_matched
            total += child_total
        return matched, total
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return 0, len(expected)
        matched = 0
        total = 0
        for index, value in enumerate(expected):
            child_actual = actual[index] if index < len(actual) else None
            child_matched, child_total = _field_accuracy(value, child_actual)
            matched += child_matched
            total += child_total
        return matched, total
    return (int(expected == actual), 1)


def _exact_value(expected: object, actual: object) -> bool:
    if type(expected) is not type(actual):
        return False
    if isinstance(expected, dict) and isinstance(actual, dict):
        return list(expected) == list(actual) and all(
            _exact_value(value, actual[key]) for key, value in expected.items()
        )
    if isinstance(expected, list) and isinstance(actual, list):
        return len(expected) == len(actual) and all(
            _exact_value(left, right) for left, right in zip(expected, actual, strict=True)
        )
    return expected == actual


def _json_value(value: object) -> object:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")  # type: ignore[union-attr]
    return value


def _json_pointer(value: object, pointer: str) -> object:
    current = value
    for raw_part in pointer.removeprefix("/").split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if part not in current:
                return None
            current = current[part]
        elif isinstance(current, list) and part.isdecimal() and int(part) < len(current):
            current = current[int(part)]
        else:
            return None
    return current


def _real_corpus_pairs(
    manifest: dict[str, Any],
) -> tuple[tuple[dict[str, Any], dict[str, Any]], ...]:
    fixtures = {
        fixture["id"]: fixture
        for fixture in manifest["fixtures"]
        if isinstance(fixture, dict) and isinstance(fixture.get("id"), str)
    }
    return tuple(
        (fixture, fixtures[fixture["output_fixture_id"]])
        for fixture in manifest["fixtures"]
        if fixture["kind"] == "sanitized-source"
    )


def _real_corpus_counts(
    pairs: tuple[tuple[dict[str, Any], dict[str, Any]], ...],
    *,
    repository_root: Path,
    actual_loader: Callable[[Path], object] | None,
) -> tuple[int, int, int, int, int, int]:
    variable_matches = 0
    variable_total = 0
    field_matches = 0
    field_total = 0
    dense_matches = 0
    dense_total = 0
    for source_fixture, output_fixture in pairs:
        fixture_payload = json.loads(
            (repository_root / output_fixture["path"]).read_text(encoding="utf-8")
        )
        actual = _json_value(
            actual_loader(repository_root / source_fixture["path"])
            if actual_loader is not None
            else fixture_payload["actual_output"]
        )
        actual_variables = actual.get("variables", []) if isinstance(actual, dict) else []
        actual_ids = [
            variable.get("raw_name")
            for variable in actual_variables
            if isinstance(variable, dict) and isinstance(variable.get("raw_name"), str)
        ]
        judgments = fixture_payload["judgments"]
        expected_ids = judgments["variable_ids"]
        remaining_ids = list(actual_ids)
        for expected_id in expected_ids:
            if expected_id in remaining_ids:
                variable_matches += 1
                remaining_ids.remove(expected_id)
        variable_total += len(expected_ids)
        for judgment in judgments["fields"]:
            field_matches += int(
                _exact_value(judgment["expected"], _json_pointer(actual, judgment["path"]))
            )
            field_total += 1
        remaining_dense_ids = list(actual_ids)
        for table in judgments["dense_repeated_tables"]:
            for expected_id in table["row_variable_ids"]:
                if expected_id in remaining_dense_ids:
                    dense_matches += 1
                    remaining_dense_ids.remove(expected_id)
                dense_total += 1
    return (
        variable_matches,
        variable_total,
        field_matches,
        field_total,
        dense_matches,
        dense_total,
    )


def _metric(
    *,
    name: str,
    threshold: float,
    baseline: str,
    value: float | None,
    available: bool,
) -> dict[str, object]:
    passed = value >= threshold if available and value is not None else None
    return {
        "name": name,
        "threshold": threshold,
        "baseline": baseline,
        "value": value,
        "available": available,
        "passed": passed,
    }


def evaluate(
    manifest_path: Path,
    thresholds_path: Path,
    *,
    repository_root: Path = REPOSITORY_ROOT,
    actual_loader: Callable[[Path], object] | None = None,
) -> dict[str, object]:
    """Build the authoritative deterministic quality report."""
    errors = validate(manifest_path, thresholds_path, repository_root=repository_root)
    if errors:
        raise ValueError("; ".join(errors))
    manifest = _load_toml(repository_root / manifest_path)
    thresholds = _load_toml(repository_root / thresholds_path)
    exact_matches = 0
    synthetic_fixtures = [
        fixture
        for fixture in manifest["fixtures"]
        if fixture["kind"] == "synthetic-expected-output"
    ]
    for fixture in synthetic_fixtures:
        fixture_path = repository_root / fixture["path"]
        expected = json.loads(fixture_path.read_text(encoding="utf-8"))
        actual = (
            actual_loader(fixture_path)
            if actual_loader is not None
            else legacy_payload(SurveySVIS.model_validate(expected))
        )
        exact_matches += int(_exact_value(expected, actual))
    exact = _ratio(exact_matches, len(synthetic_fixtures))
    real_pairs = _real_corpus_pairs(manifest)
    real_counts = _real_corpus_counts(
        real_pairs,
        repository_root=repository_root,
        actual_loader=actual_loader,
    )
    (
        variable_matches,
        variable_total,
        field_matches,
        field_total,
        dense_matches,
        dense_total,
    ) = real_counts
    availability = thresholds["availability"]
    real_available = bool(real_pairs)
    metric_thresholds = thresholds["metrics"]
    baselines = thresholds["baselines"]
    metrics = {
        "exact_schema_compatibility": _metric(
            name="exact_schema_compatibility",
            threshold=metric_thresholds["exact_schema_compatibility"],
            baseline=baselines["exact_schema_compatibility"],
            value=exact,
            available=bool(synthetic_fixtures),
        ),
        "variable_recall": _metric(
            name="variable_recall",
            threshold=metric_thresholds["variable_recall"],
            baseline=baselines["variable_recall"],
            value=(_ratio(variable_matches, variable_total) if real_available else None),
            available=real_available,
        ),
        "field_accuracy": _metric(
            name="field_accuracy",
            threshold=metric_thresholds["field_accuracy"],
            baseline=baselines["field_accuracy"],
            value=(_ratio(field_matches, field_total) if real_available else None),
            available=real_available,
        ),
        "dense_repeated_table_recall": _metric(
            name="dense_repeated_table_recall",
            threshold=metric_thresholds["dense_repeated_table_recall"],
            baseline=baselines["dense_repeated_table_recall"],
            value=_ratio(dense_matches, dense_total) if real_available else None,
            available=real_available,
        ),
    }
    routing_bundle, mechanics, routing = evaluate_repository_bundle(
        repository_root=repository_root,
        source_manifest=DEFAULT_SOURCE_MANIFEST,
    )
    routing_source_manifest = _load_toml(repository_root / DEFAULT_SOURCE_MANIFEST)
    failed_metrics = [
        name for name, metric in metrics.items() if metric["available"] and not metric["passed"]
    ]
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "offline": True,
        "corpus_status": manifest["corpus_status"],
        "availability_reason": availability["reason"],
        "corpus_evidence": [
            {
                "source_fixture_id": source["id"],
                "source_sha256": source["sha256"],
                "output_fixture_id": output["id"],
                "output_sha256": output["sha256"],
            }
            for source, output in real_pairs
        ],
        "metrics": metrics,
        "routing_mechanics": {
            "baseline": str(DEFAULT_MECHANICS_MANIFEST),
            "source_manifest": str(DEFAULT_SOURCE_MANIFEST),
            "evaluation_fixture": mechanics.evaluation.path,
            "source_fixture_ids": list(routing_bundle.source_fixture_ids),
            "source_fixtures": [
                {
                    "id": fixture["id"],
                    "path": fixture["path"],
                    "sha256": fixture["sha256"],
                }
                for fixture in routing_source_manifest["fixtures"]
            ],
            "evaluator": {
                "implementation": "scripts/evaluate_routing.py",
                "version": routing.evaluator_version,
                "purpose": mechanics.purpose,
                "measurement_provenance": mechanics.provenance,
                "restrictions": mechanics.restrictions,
            },
            "input_digests": {
                "source_manifest_sha256": routing.source_manifest_sha256,
                "mechanics_manifest_sha256": routing.mechanics_manifest_sha256,
                "evaluation_fixture_sha256": routing.evaluation_fixture_sha256,
                "expected_sha256": routing.expected_sha256,
                "first_pass_sha256": routing.first_pass_sha256,
                "post_review_sha256": routing.post_review_sha256,
            },
            "metrics": {
                "first_pass": routing.first_pass.model_dump(mode="json"),
                "post_review": routing.post_review.model_dump(mode="json"),
                "review_effect": routing.review_effect.model_dump(mode="json"),
            },
            "passed": routing.mechanics_passed,
        },
        "passed": not failed_metrics and routing.mechanics_passed,
    }


def _write_report(path: Path, report: dict[str, object]) -> None:
    target = path.absolute()
    if target.suffix != ".json" or target.is_symlink():
        raise ValueError("quality output must be a non-symlink JSON file")
    target.parent.mkdir(parents=True, exist_ok=True)
    content = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, target)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--thresholds", type=Path, default=DEFAULT_THRESHOLDS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--offline", action="store_true", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logger.remove()
    logger.add(sys.stderr, format="{message}")
    try:
        with network_blocked():
            report = evaluate(args.manifest, args.thresholds)
            _write_report(args.output, report)
    except (OSError, ValueError, json.JSONDecodeError, tomllib.TOMLDecodeError):
        logger.exception("Quality evaluation failed safely")
        return 1
    metrics = cast(dict[str, dict[str, object]], report["metrics"])
    for metric in metrics.values():
        logger.info(
            "{}: value={} threshold={} baseline={} available={}",
            metric["name"],
            metric["value"],
            metric["threshold"],
            metric["baseline"],
            metric["available"],
        )
    if report["passed"]:
        logger.info("Deterministic quality evaluation passed without provider access")
        return 0
    logger.error("Deterministic quality evaluation failed")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
