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
            if fixture["kind"] == "synthetic-expected-output" and isinstance(count, int):
                try:
                    content = json.loads(fixture_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    errors.append(f"{prefix} expected output must be valid UTF-8 JSON")
                else:
                    variables = content.get("variables") if isinstance(content, dict) else None
                    if not isinstance(variables, list) or len(variables) != count:
                        errors.append(f"{prefix} expected_variable_count does not match JSON")

    if thresholds.get("schema_version") != 1:
        errors.append("threshold schema_version must equal 1")
    metric_table = thresholds.get("metrics", {})
    if not isinstance(metric_table, dict):
        errors.append("threshold metrics must be a table")
        metric_table = {}
    missing_metrics = sorted(REQUIRED_METRICS - metric_table.keys())
    if missing_metrics:
        errors.append(f"thresholds missing metrics: {', '.join(missing_metrics)}")
    for name, value in metric_table.items():
        if not isinstance(value, int | float) or isinstance(value, bool):
            errors.append(f"metric {name} must be numeric")
        elif not 0 <= value <= 1:
            errors.append(f"metric {name} must be between 0 and 1")
        elif name in APPROVED_MINIMUMS and value < APPROVED_MINIMUMS[name]:
            errors.append(f"metric {name} is below the approved minimum")

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
