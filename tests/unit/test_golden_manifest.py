"""Tests for strict golden manifest and threshold validation."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from scripts.validate_golden_manifest import validate


def _copy_policy(repository_root: Path, destination: Path) -> tuple[Path, Path, Path]:
    fixture_relative = Path("tests/fixtures/legacy/schema-contract-v1.json")
    manifest_relative = Path("tests/fixtures/golden/manifest.toml")
    thresholds_relative = Path("tests/fixtures/golden/quality-thresholds.toml")
    for relative in (fixture_relative, manifest_relative, thresholds_relative):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repository_root / relative, target)
    return (
        destination / manifest_relative,
        destination / thresholds_relative,
        destination / fixture_relative,
    )


def test_validation_is_independent_of_caller_directory(
    repository_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert (
        validate(
            Path("tests/fixtures/golden/manifest.toml"),
            Path("tests/fixtures/golden/quality-thresholds.toml"),
            repository_root=repository_root,
        )
        == []
    )


def test_checksum_drift_fails(repository_root: Path, tmp_path: Path) -> None:
    manifest, thresholds, fixture = _copy_policy(repository_root, tmp_path)
    fixture.write_text("{}\n", encoding="utf-8")
    errors = validate(manifest, thresholds, repository_root=tmp_path)
    assert "fixture 1 checksum mismatch" in errors


def test_boolean_inventory_count_fails(repository_root: Path, tmp_path: Path) -> None:
    manifest, thresholds, _fixture = _copy_policy(repository_root, tmp_path)
    content = manifest.read_text(encoding="utf-8").replace(
        "expected_variable_count = 1", "expected_variable_count = false"
    )
    manifest.write_text(content, encoding="utf-8")
    errors = validate(manifest, thresholds, repository_root=tmp_path)
    assert "fixture 1 expected_variable_count must be a nonnegative integer" in errors


def test_empty_provenance_fails(repository_root: Path, tmp_path: Path) -> None:
    manifest, thresholds, _fixture = _copy_policy(repository_root, tmp_path)
    content = manifest.read_text(encoding="utf-8").replace(
        'creator = "Survey Scribe Phase 1 implementation"', 'creator = ""'
    )
    manifest.write_text(content, encoding="utf-8")
    errors = validate(manifest, thresholds, repository_root=tmp_path)
    assert any("empty or non-string fields: creator" in error for error in errors)


def test_weakened_threshold_fails(repository_root: Path, tmp_path: Path) -> None:
    manifest, thresholds, _fixture = _copy_policy(repository_root, tmp_path)
    content = thresholds.read_text(encoding="utf-8").replace(
        "variable_recall = 0.95", "variable_recall = 0.50"
    )
    thresholds.write_text(content, encoding="utf-8")
    errors = validate(manifest, thresholds, repository_root=tmp_path)
    assert "metric variable_recall is below the approved minimum" in errors


def test_missing_or_unknown_baseline_and_metric_fail(repository_root: Path, tmp_path: Path) -> None:
    manifest, thresholds, _fixture = _copy_policy(repository_root, tmp_path)
    content = thresholds.read_text(encoding="utf-8")
    content = content.replace(
        'dense_repeated_table_recall = "unavailable:approved-real-corpus"\n', ""
    )
    content = content.replace(
        "dense_repeated_table_recall = 0.95\n",
        "dense_repeated_table_recall = 0.95\nunknown_metric = 1.0\n",
    )
    content = content.replace(
        "[availability]\n", 'unknown_baseline = "not-approved"\n\n[availability]\n'
    )
    thresholds.write_text(content, encoding="utf-8")

    errors = validate(manifest, thresholds, repository_root=tmp_path)

    assert "thresholds contain unknown metrics: unknown_metric" in errors
    assert "thresholds missing baselines: dense_repeated_table_recall" in errors
    assert "thresholds contain unknown baselines: unknown_baseline" in errors


def test_approved_corpus_requires_exact_bidirectional_fixture_bindings(
    repository_root: Path, tmp_path: Path
) -> None:
    manifest, thresholds, _fixture = _copy_policy(repository_root, tmp_path)
    source = tmp_path / "tests/fixtures/golden/source.txt"
    output = tmp_path / "tests/fixtures/golden/output.json"
    source.write_text("sanitized", encoding="utf-8")
    output_payload = {
        "schema_version": 1,
        "source_fixture_id": "wrong-source",
        "actual_output": {"variables": [{"raw_name": "row_1"}]},
        "judgments": {
            "variable_ids": ["row_1"],
            "fields": [{"path": "/variables/0/raw_name", "expected": "row_1"}],
            "dense_repeated_tables": [{"id": "table", "row_variable_ids": ["row_1"]}],
        },
    }
    output.write_text(json.dumps(output_payload), encoding="utf-8")
    common = (
        'rights_basis = "approved-sanitized"\nrestrictions = "test"\ncreator = "test"\n'
        'purpose = "test"\nprovenance = "test"\napproval_reference = "test"\n'
        'approval_date = "2026-09-04"\nfield_judgments = "test"\nprovider = "none"\n'
        'model = "none"\nprompt_version = "none"\napprover = "owner"\n'
        'sanitization_reference = "test"\nexpected_variable_count = 1\n'
    )
    manifest.write_text(
        'schema_version = 1\ncorpus_status = "approved-sanitized"\n\n'
        '[[fixtures]]\nid = "source"\npath = "tests/fixtures/golden/source.txt"\n'
        f'kind = "sanitized-source"\n{common}'
        f'sha256 = "{hashlib.sha256(source.read_bytes()).hexdigest()}"\n'
        'output_fixture_id = "output"\n\n'
        '[[fixtures]]\nid = "output"\npath = "tests/fixtures/golden/output.json"\n'
        f'kind = "sanitized-output"\n{common}'
        f'sha256 = "{hashlib.sha256(output.read_bytes()).hexdigest()}"\n'
        'source_fixture_id = "wrong-source"\n',
        encoding="utf-8",
    )
    thresholds.write_text(
        thresholds.read_text(encoding="utf-8").replace(
            "approved_real_corpus = false", "approved_real_corpus = true"
        ),
        encoding="utf-8",
    )

    errors = validate(manifest, thresholds, repository_root=tmp_path)

    assert "fixture source output binding is not bidirectional" in errors
    assert "fixture output is not bound to one sanitized source" in errors
