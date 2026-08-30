"""Offline OCR artifact manifest and checksum validator contracts."""

from __future__ import annotations

import hashlib
from io import StringIO
from pathlib import Path

from survey_scribe.sources.ocr import (
    APPROVED_OCR_ARTIFACTS,
    OcrArtifact,
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
