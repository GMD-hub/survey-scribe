"""Offline OCR artifact manifest and checksum validator contracts."""

from __future__ import annotations

import hashlib
from io import StringIO
from pathlib import Path

import pytest

from survey_scribe.sources import ocr as ocr_source
from survey_scribe.sources.ocr import (
    APPROVED_OCR_ARTIFACTS,
    OcrArtifact,
    OcrArtifactValidation,
    main,
    validate_ocr_cache,
)


def test_approved_manifest_matches_dependency_record_exactly() -> None:
    expected = (
        OcrArtifact(
            filename="craft_mlt_25k.zip",
            size=77_251_756,
            sha256="8dc6a1c703a89ed56308ef742d26ebd45c656248cbbbda6e7fe60e569f873e65",
        ),
        OcrArtifact(
            filename="english_g2.zip",
            size=14_040_947,
            sha256="1b5eaebf1c062de6205560c97ffcfa8dc0e6f413c340e8adc5cfc57e159f61ff",
        ),
    )
    assert expected == APPROVED_OCR_ARTIFACTS


def test_validator_accepts_small_injected_manifest_without_network(tmp_path: Path) -> None:
    payload = b"synthetic OCR artifact"
    artifact = OcrArtifact(
        filename="small.zip",
        size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )
    (tmp_path / artifact.filename).write_bytes(payload)

    result = validate_ocr_cache(tmp_path, manifest=(artifact,))

    assert result[0].status == "valid"
    assert result[0].checksum_checked is True


def test_wrong_size_does_not_falsely_report_a_passed_checksum(tmp_path: Path) -> None:
    artifact = OcrArtifact(filename="small.zip", size=10, sha256="0" * 64)
    (tmp_path / artifact.filename).write_bytes(b"wrong")

    result = validate_ocr_cache(tmp_path, manifest=(artifact,))

    assert result[0].status == "size_mismatch"
    assert result[0].checksum_checked is False


def test_same_size_corruption_reports_sha256_mismatch(tmp_path: Path) -> None:
    expected = b"approved"
    artifact = OcrArtifact(
        filename="small.zip",
        size=len(expected),
        sha256=hashlib.sha256(expected).hexdigest(),
    )
    (tmp_path / artifact.filename).write_bytes(b"corrupt!")

    result = validate_ocr_cache(tmp_path, manifest=(artifact,))

    assert result[0].status == "sha256_mismatch"
    assert result[0].checksum_checked is True


def test_no_argument_behavior_is_deterministic_when_cache_is_not_configured() -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_code = main(environ={}, stdout=stdout, stderr=stderr)

    assert exit_code == 2
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == (
        "OCR cache is not configured. Set SURVEY_SCRIBE_OCR_CACHE or DOCLING_ARTIFACTS_PATH.\n"
    )


def test_configured_missing_cache_reports_missing_not_valid(tmp_path: Path) -> None:
    stdout = StringIO()
    stderr = StringIO()

    exit_code = main(
        environ={"SURVEY_SCRIBE_OCR_CACHE": str(tmp_path)}, stdout=stdout, stderr=stderr
    )

    assert exit_code == 1
    assert "MISSING craft_mlt_25k.zip" in stdout.getvalue()
    assert "MISSING english_g2.zip" in stdout.getvalue()
    assert "passed" not in stdout.getvalue().lower()
    assert stderr.getvalue() == "OCR artifact validation failed: 0/2 valid.\n"


def test_validator_reports_unsafe_resolution_and_hash_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"artifact"
    artifact = OcrArtifact(
        filename="small.zip",
        size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )
    candidate = tmp_path / artifact.filename
    candidate.write_bytes(payload)
    original_resolve = Path.resolve

    def fail_candidate(path: Path, strict: bool = False) -> Path:
        if path == candidate:
            raise OSError
        return original_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", fail_candidate)
    result = validate_ocr_cache(tmp_path, manifest=(artifact,))
    assert result[0].status == "unsafe"
    assert result[0].checksum_checked is False

    monkeypatch.setattr(Path, "resolve", original_resolve)

    def fail_hash(_path: Path) -> str:
        raise OSError

    monkeypatch.setattr(ocr_source, "_sha256", fail_hash)
    result = validate_ocr_cache(tmp_path, manifest=(artifact,))
    assert result[0].status == "unsafe"
    assert result[0].checksum_checked is False


def test_validator_rejects_resolved_path_outside_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    candidate = cache / "small.zip"
    candidate.write_bytes(b"x")
    outside = tmp_path / "outside.zip"
    outside.write_bytes(b"x")
    artifact = OcrArtifact(
        filename="small.zip",
        size=1,
        sha256=hashlib.sha256(b"x").hexdigest(),
    )
    original_resolve = Path.resolve

    def escape_candidate(path: Path, strict: bool = False) -> Path:
        if path == candidate:
            return outside
        return original_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", escape_candidate)
    result = validate_ocr_cache(cache, manifest=(artifact,))

    assert result[0].status == "unsafe"
    assert result[0].checksum_checked is False


def test_main_rejects_missing_directory_and_reports_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stdout = StringIO()
    stderr = StringIO()
    missing = tmp_path / "missing"

    assert (
        main(
            environ={"DOCLING_ARTIFACTS_PATH": str(missing)},
            stdout=stdout,
            stderr=stderr,
        )
        == 2
    )
    assert stderr.getvalue() == "Configured OCR cache directory does not exist.\n"

    artifact = OcrArtifact(filename="small.zip", size=1, sha256="0" * 64)
    monkeypatch.setattr(
        ocr_source,
        "validate_ocr_cache",
        lambda _cache: (OcrArtifactValidation(artifact, "valid", True),),
    )
    stdout = StringIO()
    stderr = StringIO()

    exit_code = main(
        environ={"SURVEY_SCRIBE_OCR_CACHE": str(tmp_path)},
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stdout.getvalue() == ("OK small.zip\nOCR artifact validation passed: 1/1 valid.\n")
    assert stderr.getvalue() == ""
