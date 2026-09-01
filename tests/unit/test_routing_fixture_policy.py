"""Tests for the fail-closed routing source fixture policy."""

from __future__ import annotations

import hashlib
import shutil
import tomllib
from pathlib import Path

import pytest

from scripts.validate_routing_fixtures import REQUIRED_CASES, validate

MANIFEST_RELATIVE = Path("tests/fixtures/routing/manifest.toml")
SCALE_RELATIVE = Path("tests/fixtures/routing/sources/scale-1000-items.txt")


def _copy_corpus(repository_root: Path, destination: Path) -> Path:
    source = repository_root / "tests/fixtures/routing"
    target = destination / "tests/fixtures/routing"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
    return destination / MANIFEST_RELATIVE


def _replace(manifest: Path, old: str, new: str) -> None:
    content = manifest.read_text(encoding="utf-8")
    assert old in content
    manifest.write_text(content.replace(old, new, 1), encoding="utf-8", newline="\n")


def _set_checksum(manifest: Path, fixture_id: str, digest: str) -> None:
    content = manifest.read_text(encoding="utf-8")
    marker = f'id = "{fixture_id}"'
    start = content.index(marker)
    checksum_start = content.index('sha256 = "', start) + len('sha256 = "')
    checksum_end = content.index('"', checksum_start)
    updated = content[:checksum_start] + digest + content[checksum_end:]
    manifest.write_text(updated, encoding="utf-8", newline="\n")


def test_repository_routing_source_corpus_is_valid(repository_root: Path) -> None:
    assert validate(repository_root / MANIFEST_RELATIVE, repository_root=repository_root) == []


def test_validation_is_independent_of_caller_directory(
    repository_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    assert validate(MANIFEST_RELATIVE, repository_root=repository_root) == []


def test_manifest_covers_each_required_case_and_commits_1000_items(
    repository_root: Path,
) -> None:
    with (repository_root / MANIFEST_RELATIVE).open("rb") as stream:
        manifest = tomllib.load(stream)

    covered = {
        case for fixture in manifest["fixtures"] for case in fixture["expected_logical_cases"]
    }
    assert covered == REQUIRED_CASES
    scale = next(fixture for fixture in manifest["fixtures"] if fixture["id"] == "scale-1000-items")
    assert scale["declared_item_count"] == 1000

    scale_text = (repository_root / SCALE_RELATIVE).read_text(encoding="utf-8")
    assert sum(line.startswith("ITEM ") for line in scale_text.splitlines()) == 1000


def test_checksum_drift_fails(repository_root: Path, tmp_path: Path) -> None:
    manifest = _copy_corpus(repository_root, tmp_path)
    fixture = tmp_path / "tests/fixtures/routing/sources/skip-with-fallthrough.txt"
    fixture.write_text(fixture.read_text(encoding="utf-8") + "Changed.\n", encoding="utf-8")

    assert "fixture 1 checksum mismatch" in validate(manifest, repository_root=tmp_path)


@pytest.mark.parametrize("field", ["rights_basis", "creator", "provenance"])
def test_missing_rights_or_provenance_fails(
    repository_root: Path,
    tmp_path: Path,
    field: str,
) -> None:
    manifest = _copy_corpus(repository_root, tmp_path)
    content = manifest.read_text(encoding="utf-8")
    line = next(line for line in content.splitlines() if line.startswith(f"{field} = "))
    _replace(manifest, line, f'{field} = ""')

    errors = validate(manifest, repository_root=tmp_path)
    assert f"fixture 1 field {field} must be a nonempty string" in errors


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        (
            'id = "answer-code-branches-default"',
            'id = "skip-with-fallthrough"',
            "fixture 2 duplicates fixture id",
        ),
        (
            'path = "tests/fixtures/routing/sources/answer-code-branches-default.txt"',
            'path = "tests/fixtures/routing/sources/skip-with-fallthrough.txt"',
            "fixture 2 duplicates fixture path",
        ),
    ],
)
def test_duplicate_fixture_identity_fails(
    repository_root: Path,
    tmp_path: Path,
    old: str,
    new: str,
    expected: str,
) -> None:
    manifest = _copy_corpus(repository_root, tmp_path)
    _replace(manifest, old, new)

    assert any(error.startswith(expected) for error in validate(manifest, repository_root=tmp_path))


def test_malformed_manifest_fails_closed(repository_root: Path, tmp_path: Path) -> None:
    manifest = _copy_corpus(repository_root, tmp_path)
    manifest.write_bytes(b"[[fixtures]\n")

    errors = validate(manifest, repository_root=tmp_path)
    assert errors == ["manifest is not valid TOML"]


def test_missing_required_case_fails(repository_root: Path, tmp_path: Path) -> None:
    manifest = _copy_corpus(repository_root, tmp_path)
    _replace(
        manifest,
        'expected_logical_cases = ["garbled_target"]',
        'expected_logical_cases = ["screen_out_terminal"]',
    )

    errors = validate(manifest, repository_root=tmp_path)
    assert "manifest is missing required cases: garbled_target" in errors


def test_unknown_case_fails(repository_root: Path, tmp_path: Path) -> None:
    manifest = _copy_corpus(repository_root, tmp_path)
    _replace(
        manifest,
        'expected_logical_cases = ["garbled_target"]',
        'expected_logical_cases = ["garbled_target", "future_case"]',
    )

    errors = validate(manifest, repository_root=tmp_path)
    assert "fixture 10 has unsupported expected logical cases: future_case" in errors


def test_weakened_scale_count_fails(repository_root: Path, tmp_path: Path) -> None:
    manifest = _copy_corpus(repository_root, tmp_path)
    _replace(manifest, "declared_item_count = 1000", "declared_item_count = 999")

    errors = validate(manifest, repository_root=tmp_path)
    assert "scale fixture must declare at least 1000 items" in errors


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "../outside.txt",
        "tests/fixtures/routing/../legacy/schema-contract-v1.json",
        "tests\\fixtures\\routing\\sources\\skip-with-fallthrough.txt",
        "tests/fixtures/routing/sources/.env",
        "tests/fixtures/routing/sources/private-key.pem",
    ],
)
def test_unconfined_or_restricted_path_fails(
    repository_root: Path,
    tmp_path: Path,
    unsafe_path: str,
) -> None:
    manifest = _copy_corpus(repository_root, tmp_path)
    _replace(
        manifest,
        'path = "tests/fixtures/routing/sources/skip-with-fallthrough.txt"',
        f'path = "{unsafe_path.replace(chr(92), chr(92) * 2)}"',
    )

    errors = validate(manifest, repository_root=tmp_path)
    assert any(error.startswith("fixture 1 path") for error in errors)


def test_symlinked_fixture_fails(
    repository_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _copy_corpus(repository_root, tmp_path)
    fixture = tmp_path / "tests/fixtures/routing/sources/skip-with-fallthrough.txt"
    is_symlink = Path.is_symlink

    def simulated_is_symlink(path: Path) -> bool:
        return path == fixture or is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", simulated_is_symlink)

    assert "fixture 1 path must not use symlinks" in validate(manifest, repository_root=tmp_path)


@pytest.mark.parametrize(
    "secret",
    [
        "-----BEGIN PRIVATE KEY-----",
        "AKIAIOSFODNN7EXAMPLE",
        "api_key = sk-proj-abcdefghijklmnopqrstuvwxyz123456",
    ],
)
def test_secret_pattern_fails_without_echoing_secret(
    repository_root: Path,
    tmp_path: Path,
    secret: str,
) -> None:
    manifest = _copy_corpus(repository_root, tmp_path)
    fixture = tmp_path / "tests/fixtures/routing/sources/prompt-injection.txt"
    fixture.write_text(f"ITEM P1\nQuestion: {secret}\n", encoding="utf-8", newline="\n")
    _set_checksum(manifest, "prompt-injection", hashlib.sha256(fixture.read_bytes()).hexdigest())

    errors = validate(manifest, repository_root=tmp_path)
    assert "fixture 13 contains a prohibited secret pattern" in errors
    assert all(secret not in error for error in errors)


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        (
            'corpus_status = "synthetic-source-only"',
            'corpus_status = "approved-sanitized"',
            "manifest corpus_status must be synthetic-source-only",
        ),
        ("source_only = true", "source_only = false", "manifest must be source-only"),
        (
            "benchmark_eligible = false",
            "benchmark_eligible = true",
            "manifest must be ineligible for model-quality benchmarks",
        ),
        (
            'artifact_kind = "synthetic-questionnaire-source"',
            'artifact_kind = "expected-routing-graph"',
            "fixture 1 must be a synthetic questionnaire source",
        ),
    ],
)
def test_source_only_and_benchmark_policy_cannot_be_relaxed(
    repository_root: Path,
    tmp_path: Path,
    old: str,
    new: str,
    expected: str,
) -> None:
    manifest = _copy_corpus(repository_root, tmp_path)
    _replace(manifest, old, new)

    assert expected in validate(manifest, repository_root=tmp_path)


def test_fixture_level_benchmark_eligibility_fails(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    manifest = _copy_corpus(repository_root, tmp_path)
    first_fixture = manifest.read_text(encoding="utf-8").index("[[fixtures]]")
    content = manifest.read_text(encoding="utf-8")
    field = content.index("benchmark_eligible = false", first_fixture)
    updated = content[:field] + content[field:].replace(
        "benchmark_eligible = false", "benchmark_eligible = true", 1
    )
    manifest.write_text(updated, encoding="utf-8", newline="\n")

    errors = validate(manifest, repository_root=tmp_path)
    assert "fixture 1 must be ineligible for model-quality benchmarks" in errors


def test_unlisted_or_non_source_artifact_fails(repository_root: Path, tmp_path: Path) -> None:
    manifest = _copy_corpus(repository_root, tmp_path)
    unexpected = tmp_path / "tests/fixtures/routing/expected-graph.json"
    unexpected.write_text("{}\n", encoding="utf-8")

    errors = validate(manifest, repository_root=tmp_path)
    assert "routing fixture corpus contains unlisted or non-source files" in errors


def test_crlf_fails_even_with_matching_checksum(repository_root: Path, tmp_path: Path) -> None:
    manifest = _copy_corpus(repository_root, tmp_path)
    fixture = tmp_path / "tests/fixtures/routing/sources/skip-with-fallthrough.txt"
    fixture.write_bytes(fixture.read_bytes().replace(b"\n", b"\r\n"))
    _set_checksum(
        manifest, "skip-with-fallthrough", hashlib.sha256(fixture.read_bytes()).hexdigest()
    )

    errors = validate(manifest, repository_root=tmp_path)
    assert "fixture 1 must use LF line endings" in errors


def test_missing_terminal_lf_fails_even_with_matching_checksum(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    manifest = _copy_corpus(repository_root, tmp_path)
    fixture = tmp_path / "tests/fixtures/routing/sources/skip-with-fallthrough.txt"
    fixture.write_bytes(fixture.read_bytes().removesuffix(b"\n"))
    _set_checksum(
        manifest, "skip-with-fallthrough", hashlib.sha256(fixture.read_bytes()).hexdigest()
    )

    errors = validate(manifest, repository_root=tmp_path)
    assert "fixture 1 must end with LF" in errors


def test_unknown_manifest_or_fixture_fields_fail_closed(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    manifest = _copy_corpus(repository_root, tmp_path)
    _replace(manifest, "schema_version = 1", 'schema_version = 1\nexpected_graph = "none"')
    _replace(
        manifest, "declared_item_count = 3", 'declared_item_count = 3\nmodel_response = "none"'
    )

    errors = validate(manifest, repository_root=tmp_path)
    assert "manifest has unsupported fields: expected_graph" in errors
    assert "fixture 1 has unsupported fields: model_response" in errors
