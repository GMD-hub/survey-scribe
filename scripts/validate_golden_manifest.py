# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = [
#   "loguru==0.7.3",
#   "tomli==2.2.1",
# ]
# ///
"""Validate golden fixture rights, checksums, inventory, and thresholds."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

import tomli
from loguru import logger

REQUIRED_METRICS = {
    "exact_schema_compatibility",
    "variable_recall",
    "field_accuracy",
    "dense_repeated_table_recall",
}
ALLOWED_RIGHTS = {"repository-synthetic", "approved-sanitized"}
ALLOWED_KINDS = {"synthetic-expected-output", "sanitized-source", "sanitized-output"}
APPROVED_MINIMUMS = {
    "exact_schema_compatibility": 1.0,
    "variable_recall": 0.95,
    "field_accuracy": 0.95,
    "dense_repeated_table_recall": 0.95,
}
REQUIRED_FIXTURE_FIELDS = {
    "id",
    "path",
    "kind",
    "rights_basis",
    "restrictions",
    "creator",
    "purpose",
    "provenance",
    "approval_reference",
    "approval_date",
    "sha256",
    "expected_variable_count",
    "field_judgments",
    "provider",
    "model",
    "prompt_version",
}
REQUIRED_TEXT_FIELDS = REQUIRED_FIXTURE_FIELDS - {"expected_variable_count"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
JSON_POINTER_RE = re.compile(r"^(?:/(?:[^~/]|~[01])*)+$")


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as stream:
        return tomli.load(stream)


def _repository_path(path: Path, root: Path) -> Path:
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"path escapes the repository: {path}")
    return resolved


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_real_output(
    content: object,
    *,
    fixture_id: str,
    expected_source_id: str,
    expected_variable_count: int,
) -> list[str]:
    prefix = f"fixture {fixture_id}"
    if not isinstance(content, dict) or set(content) != {
        "schema_version",
        "source_fixture_id",
        "actual_output",
        "judgments",
    }:
        return [f"{prefix} sanitized output shape is invalid"]
    if content["schema_version"] != 1 or content["source_fixture_id"] != expected_source_id:
        return [f"{prefix} sanitized output source binding is invalid"]
    judgments = content["judgments"]
    if not isinstance(content["actual_output"], dict) or not isinstance(judgments, dict):
        return [f"{prefix} sanitized output payload is invalid"]
    if set(judgments) != {"variable_ids", "fields", "dense_repeated_tables"}:
        return [f"{prefix} sanitized output judgments are invalid"]
    variable_ids = judgments["variable_ids"]
    if (
        not isinstance(variable_ids, list)
        or len(variable_ids) != expected_variable_count
        or len(set(variable_ids)) != len(variable_ids)
        or any(not _is_nonempty_string(item) for item in variable_ids)
    ):
        return [f"{prefix} variable inventory is invalid"]
    fields = judgments["fields"]
    if not isinstance(fields, list) or not fields:
        return [f"{prefix} field judgments are invalid"]
    field_paths: set[str] = set()
    for field in fields:
        if (
            not isinstance(field, dict)
            or set(field) != {"path", "expected"}
            or not isinstance(field.get("path"), str)
            or not JSON_POINTER_RE.fullmatch(field["path"])
            or field["path"] in field_paths
        ):
            return [f"{prefix} field judgments are invalid"]
        field_paths.add(field["path"])
    dense_tables = judgments["dense_repeated_tables"]
    if not isinstance(dense_tables, list) or not dense_tables:
        return [f"{prefix} dense-table judgments are invalid"]
    table_ids: set[str] = set()
    for table in dense_tables:
        if not isinstance(table, dict) or set(table) != {"id", "row_variable_ids"}:
            return [f"{prefix} dense-table judgments are invalid"]
        table_id = table["id"]
        row_ids = table["row_variable_ids"]
        if (
            not _is_nonempty_string(table_id)
            or table_id in table_ids
            or not isinstance(row_ids, list)
            or not row_ids
            or len(set(row_ids)) != len(row_ids)
            or any(not _is_nonempty_string(item) or item not in variable_ids for item in row_ids)
        ):
            return [f"{prefix} dense-table judgments are invalid"]
        table_ids.add(table_id)
    return []


def validate(
    manifest_path: Path,
    thresholds_path: Path,
    *,
    repository_root: Path | None = None,
) -> list[str]:
    """Return all validation errors for the manifest and threshold policy."""
    errors: list[str] = []
    root = (repository_root or Path(__file__).resolve().parents[1]).resolve()
    try:
        resolved_manifest = _repository_path(manifest_path, root)
        resolved_thresholds = _repository_path(thresholds_path, root)
    except ValueError as exc:
        return [str(exc)]
    manifest = _load_toml(resolved_manifest)
    thresholds = _load_toml(resolved_thresholds)

    if manifest.get("schema_version") != 1:
        errors.append("manifest schema_version must equal 1")
    if manifest.get("corpus_status") not in {"synthetic-only", "approved-sanitized"}:
        errors.append("manifest corpus_status is invalid")

    fixtures = manifest.get("fixtures", [])
    if not isinstance(fixtures, list) or not fixtures:
        errors.append("manifest must define at least one fixture")
        fixtures = []

    fixture_ids: set[str] = set()
    fixture_paths: set[str] = set()
    fixture_records: dict[str, dict[str, Any]] = {}
    fixture_contents: dict[str, object] = {}
    for index, fixture in enumerate(fixtures, start=1):
        prefix = f"fixture {index}"
        if not isinstance(fixture, dict):
            errors.append(f"{prefix} must be a TOML table")
            continue
        missing = sorted(REQUIRED_FIXTURE_FIELDS - fixture.keys())
        if missing:
            errors.append(f"{prefix} missing fields: {', '.join(missing)}")
            continue
        invalid_text = sorted(
            field for field in REQUIRED_TEXT_FIELDS if not _is_nonempty_string(fixture[field])
        )
        if invalid_text:
            errors.append(f"{prefix} has empty or non-string fields: {', '.join(invalid_text)}")
            continue
        if fixture["id"] in fixture_ids:
            errors.append(f"{prefix} duplicates fixture id {fixture['id']}")
        fixture_ids.add(fixture["id"])
        fixture_records[fixture["id"]] = fixture
        if fixture["path"] in fixture_paths:
            errors.append(f"{prefix} duplicates fixture path {fixture['path']}")
        fixture_paths.add(fixture["path"])
        if fixture["kind"] not in ALLOWED_KINDS:
            errors.append(f"{prefix} has unsupported kind")
        if fixture["rights_basis"] not in ALLOWED_RIGHTS:
            errors.append(f"{prefix} has unapproved rights_basis")
        if fixture["rights_basis"] == "approved-sanitized":
            for field in ("approver", "sanitization_reference"):
                if not _is_nonempty_string(fixture.get(field)):
                    errors.append(f"{prefix} approved-sanitized rights require {field}")
        try:
            date.fromisoformat(fixture["approval_date"])
        except ValueError:
            errors.append(f"{prefix} approval_date must be ISO YYYY-MM-DD")
        if not SHA256_RE.fullmatch(fixture["sha256"]):
            errors.append(f"{prefix} sha256 must be 64 lowercase hexadecimal characters")
        count = fixture["expected_variable_count"]
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            errors.append(f"{prefix} expected_variable_count must be a nonnegative integer")

        try:
            fixture_path = _repository_path(Path(fixture["path"]), root)
        except ValueError:
            errors.append(f"{prefix} path escapes the repository")
            continue
        if not fixture_path.is_relative_to((root / "tests/fixtures").resolve()):
            errors.append(f"{prefix} path must be under tests/fixtures")
        if not fixture_path.is_file():
            errors.append(f"{prefix} file does not exist: {fixture['path']}")
        else:
            with fixture_path.open("rb") as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
            if actual != fixture["sha256"]:
                errors.append(f"{prefix} checksum mismatch")
            if fixture["kind"] in {"synthetic-expected-output", "sanitized-output"}:
                try:
                    content = json.loads(fixture_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    errors.append(f"{prefix} output must be valid UTF-8 JSON")
                else:
                    fixture_contents[fixture["id"]] = content
                    variables = content.get("variables") if isinstance(content, dict) else None
                    if (
                        fixture["kind"] == "synthetic-expected-output"
                        and isinstance(count, int)
                        and (not isinstance(variables, list) or len(variables) != count)
                    ):
                        errors.append(f"{prefix} expected_variable_count does not match JSON")

    real_sources = [
        fixture for fixture in fixture_records.values() if fixture.get("kind") == "sanitized-source"
    ]
    real_outputs = [
        fixture for fixture in fixture_records.values() if fixture.get("kind") == "sanitized-output"
    ]
    for fixture in (*real_sources, *real_outputs):
        if fixture["rights_basis"] != "approved-sanitized":
            errors.append(f"fixture {fixture['id']} real corpus requires approved-sanitized rights")
    bound_outputs: set[str] = set()
    for source in real_sources:
        output_id = source.get("output_fixture_id")
        output = fixture_records.get(output_id) if isinstance(output_id, str) else None
        if output is None or output.get("kind") != "sanitized-output":
            errors.append(f"fixture {source['id']} requires a valid output_fixture_id")
            continue
        if output.get("source_fixture_id") != source["id"]:
            errors.append(f"fixture {source['id']} output binding is not bidirectional")
            continue
        if output.get("expected_variable_count") != source["expected_variable_count"]:
            errors.append(f"fixture {source['id']} expected variable counts do not match")
            continue
        if output_id in bound_outputs:
            errors.append(f"fixture {output_id} is bound to more than one source")
            continue
        bound_outputs.add(output_id)
        content = fixture_contents.get(output_id)
        errors.extend(
            _validate_real_output(
                content,
                fixture_id=output_id,
                expected_source_id=source["id"],
                expected_variable_count=source["expected_variable_count"],
            )
        )
    for output in real_outputs:
        if output["id"] not in bound_outputs:
            errors.append(f"fixture {output['id']} is not bound to one sanitized source")

    has_real_corpus = (
        bool(real_sources)
        and bool(real_outputs)
        and len(bound_outputs) == len(real_sources) == len(real_outputs)
    )
    expected_status = "approved-sanitized" if has_real_corpus else "synthetic-only"
    if manifest.get("corpus_status") != expected_status:
        errors.append(f"manifest corpus_status must be {expected_status}")

    if thresholds.get("schema_version") != 1:
        errors.append("threshold schema_version must equal 1")
    metric_table = thresholds.get("metrics", {})
    if not isinstance(metric_table, dict):
        errors.append("threshold metrics must be a table")
        metric_table = {}
    missing_metrics = sorted(REQUIRED_METRICS - metric_table.keys())
    if missing_metrics:
        errors.append(f"thresholds missing metrics: {', '.join(missing_metrics)}")
    unknown_metrics = sorted(metric_table.keys() - REQUIRED_METRICS)
    if unknown_metrics:
        errors.append(f"thresholds contain unknown metrics: {', '.join(unknown_metrics)}")
    for name, value in metric_table.items():
        if not isinstance(value, int | float) or isinstance(value, bool):
            errors.append(f"metric {name} must be numeric")
        elif not 0 <= value <= 1:
            errors.append(f"metric {name} must be between 0 and 1")
        elif name in APPROVED_MINIMUMS and value < APPROVED_MINIMUMS[name]:
            errors.append(f"metric {name} is below the approved minimum")

    baselines = thresholds.get("baselines", {})
    if not isinstance(baselines, dict):
        errors.append("threshold baselines must be a table")
        baselines = {}
    missing_baselines = sorted(REQUIRED_METRICS - baselines.keys())
    if missing_baselines:
        errors.append(f"thresholds missing baselines: {', '.join(missing_baselines)}")
    unknown_baselines = sorted(baselines.keys() - REQUIRED_METRICS)
    if unknown_baselines:
        errors.append(f"thresholds contain unknown baselines: {', '.join(unknown_baselines)}")
    for name in REQUIRED_METRICS & baselines.keys():
        if not _is_nonempty_string(baselines[name]):
            errors.append(f"baseline {name} must be a nonempty string")

    availability = thresholds.get("availability")
    if not isinstance(availability, dict):
        errors.append("threshold availability must be a table")
    else:
        approved = availability.get("approved_real_corpus")
        if not isinstance(approved, bool) or approved != has_real_corpus:
            errors.append("approved_real_corpus must match validated sanitized fixture pairs")
        if not _is_nonempty_string(availability.get("reason")):
            errors.append("threshold availability requires a nonempty reason")

    return errors


def main() -> int:
    """Parse arguments and validate the repository golden policy."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("tests/fixtures/golden/manifest.toml"),
    )
    parser.add_argument(
        "--thresholds",
        type=Path,
        default=Path("tests/fixtures/golden/quality-thresholds.toml"),
    )
    args = parser.parse_args()
    logger.remove()
    logger.add(sys.stderr, format="{message}")

    try:
        errors = validate(args.manifest, args.thresholds)
    except (OSError, tomli.TOMLDecodeError):
        logger.exception("Golden policy validation failed")
        return 1

    if errors:
        for error in errors:
            logger.error(error)
        return 1
    logger.info("Golden manifest and thresholds are valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
