"""Tests for strict golden manifest and threshold validation."""

from __future__ import annotations

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
