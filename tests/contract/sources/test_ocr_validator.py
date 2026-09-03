"""Offline OCR artifact manifest and checksum validator contracts."""

from __future__ import annotations

import hashlib
import zipfile
from io import BytesIO, StringIO
from pathlib import Path

import pytest

from survey_scribe.sources import ocr as ocr_source
from survey_scribe.sources.ocr import (
    APPROVED_OCR_ARTIFACTS,
    OcrArtifact,
    OcrArtifactValidation,
    OcrCacheError,
    main,
    resolve_ocr_cache,
    validate_ocr_cache,
    validated_ocr_model_snapshot,
)


def _write_runtime_artifact(
    cache: Path,
    *,
    model_payload: bytes = b"approved model",
    member_name: str = "small.pth",
) -> OcrArtifact:
    archive_buffer = BytesIO()
    with zipfile.ZipFile(archive_buffer, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr(member_name, model_payload)
    archive_payload = archive_buffer.getvalue()
    artifact = OcrArtifact(
        filename="small.zip",
        size=len(archive_payload),
        sha256=hashlib.sha256(archive_payload).hexdigest(),
    )
    (cache / artifact.filename).write_bytes(archive_payload)
    (cache / "small.pth").write_bytes(model_payload)
    return artifact


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


def test_runtime_resolver_validates_archive_and_consumed_model_bytes(tmp_path: Path) -> None:
    model_name = "small.pth"
    model_payload = b"synthetic model weights"
    archive_buffer = BytesIO()
    with zipfile.ZipFile(archive_buffer, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr(f"release/{model_name}", model_payload)
    archive_payload = archive_buffer.getvalue()
    artifact = OcrArtifact(
        filename="small.zip",
        size=len(archive_payload),
        sha256=hashlib.sha256(archive_payload).hexdigest(),
    )
    (tmp_path / artifact.filename).write_bytes(archive_payload)
    model = tmp_path / model_name
    model.write_bytes(model_payload)

    assert resolve_ocr_cache(tmp_path, manifest=(artifact,)) == tmp_path.resolve()

    model.write_bytes(b"corrupt model weights")
    with pytest.raises(OcrCacheError, match="model (size|digest)"):
        resolve_ocr_cache(tmp_path, manifest=(artifact,))

    model.write_bytes(model_payload)
    with validated_ocr_model_snapshot(tmp_path, manifest=(artifact,)) as snapshot:
        snapshot_path = snapshot
        model.write_bytes(b"changed after snapshot")
        assert (snapshot / model_name).read_bytes() == model_payload
    assert snapshot_path.exists() is False


def test_runtime_resolver_rejects_archive_drift_and_missing_model_member(tmp_path: Path) -> None:
    payload = b"not a zip"
    artifact = OcrArtifact(
        filename="small.zip",
        size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )
    (tmp_path / artifact.filename).write_bytes(payload)

    with pytest.raises(OcrCacheError, match="could not be validated"):
        resolve_ocr_cache(tmp_path, manifest=(artifact,))


def test_runtime_resolver_rejects_same_size_drift_symlinks_and_wrong_members(
    tmp_path: Path,
) -> None:
    artifact = _write_runtime_artifact(tmp_path)
    archive = tmp_path / artifact.filename
    original_archive = archive.read_bytes()
    archive.write_bytes(bytes(reversed(original_archive)))
    with pytest.raises(OcrCacheError, match="archive digest"):
        resolve_ocr_cache(tmp_path, manifest=(artifact,))

    archive.write_bytes(original_archive)
    model = tmp_path / "small.pth"
    model.write_bytes(b"rejected model")
    with pytest.raises(OcrCacheError, match="model digest"):
        resolve_ocr_cache(tmp_path, manifest=(artifact,))

    wrong_member = _write_runtime_artifact(tmp_path, member_name="other.pth")
    with pytest.raises(OcrCacheError, match="model member"):
        resolve_ocr_cache(tmp_path, manifest=(wrong_member,))

    symlink_target = tmp_path / "outside.pth"
    symlink_target.write_bytes(b"approved model")
    model.unlink()
    try:
        model.symlink_to(symlink_target)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    valid = _write_runtime_artifact(tmp_path)
    model.unlink()
    model.symlink_to(symlink_target)
    with pytest.raises(OcrCacheError, match="unsafe artifact paths"):
        resolve_ocr_cache(tmp_path, manifest=(valid,))


def test_private_ocr_snapshot_revalidates_archive_errors(tmp_path: Path) -> None:
    artifact = _write_runtime_artifact(tmp_path)
    changed = artifact.__class__(
        filename=artifact.filename,
        size=artifact.size,
        sha256="0" * 64,
    )
    with pytest.raises(OcrCacheError, match="changed after validation"):
        ocr_source._approved_model_payload(tmp_path, changed)

    payload = b"not a zip"
    broken = OcrArtifact(
        filename="broken.zip",
        size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )
    (tmp_path / broken.filename).write_bytes(payload)
    with pytest.raises(OcrCacheError, match="could not be snapshotted"):
        ocr_source._approved_model_payload(tmp_path, broken)


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
