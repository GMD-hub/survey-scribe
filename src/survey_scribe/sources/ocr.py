"""Offline checksum validation for approved local EasyOCR artifacts."""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import zipfile
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, TextIO


@dataclass(frozen=True, slots=True)
class OcrArtifact:
    """One approved local OCR archive and its immutable digest metadata."""

    filename: str
    size: int
    sha256: str


APPROVED_OCR_ARTIFACTS = (
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

OcrValidationStatus = Literal["valid", "missing", "size_mismatch", "sha256_mismatch", "unsafe"]


@dataclass(frozen=True, slots=True)
class OcrArtifactValidation:
    """Accurate local validation state for one approved OCR archive."""

    artifact: OcrArtifact
    status: OcrValidationStatus
    checksum_checked: bool


class OcrCacheError(ValueError):
    """Configured OCR files do not match the approved runtime artifacts."""


class _ReadableBinary(Protocol):
    def read(self, size: int = -1, /) -> bytes: ...


def resolve_ocr_cache(
    cache: Path,
    *,
    manifest: Sequence[OcrArtifact] = APPROVED_OCR_ARTIFACTS,
) -> Path:
    """Return one confined cache only when archives and consumed models match."""
    try:
        cache_root = cache.resolve(strict=True)
    except OSError as error:
        raise OcrCacheError("Configured OCR cache directory does not exist") from error
    if cache.is_symlink() or not cache_root.is_dir():
        raise OcrCacheError("Configured OCR cache directory is unsafe")

    for artifact in manifest:
        archive = cache_root / artifact.filename
        model_name = f"{Path(artifact.filename).stem}.pth"
        model = cache_root / model_name
        if archive.is_symlink() or model.is_symlink():
            raise OcrCacheError("Configured OCR cache contains unsafe artifact paths")
        try:
            with archive.open("rb") as archive_stream:
                archive_details = os.fstat(archive_stream.fileno())
                if archive_details.st_size != artifact.size:
                    raise OcrCacheError("Configured OCR archive size does not match")
                archive_digest = _sha256_stream(archive_stream)
                if archive_digest != artifact.sha256:
                    raise OcrCacheError("Configured OCR archive digest does not match")
                archive_stream.seek(0)
                with zipfile.ZipFile(archive_stream) as bundle:
                    members = tuple(
                        item
                        for item in bundle.infolist()
                        if not item.is_dir() and Path(item.filename).name == model_name
                    )
                    if len(members) != 1:
                        raise OcrCacheError("Approved OCR archive model member is invalid")
                    member = members[0]
                    with bundle.open(member) as model_stream:
                        approved_model_digest = _sha256_stream(model_stream)
            resolved_model = model.resolve(strict=True)
            if not resolved_model.is_relative_to(cache_root) or not resolved_model.is_file():
                raise OcrCacheError("Configured OCR model path is unsafe")
            with resolved_model.open("rb") as model_stream:
                model_details = os.fstat(model_stream.fileno())
                if model_details.st_size != member.file_size:
                    raise OcrCacheError("Configured OCR model size does not match")
                if _sha256_stream(model_stream) != approved_model_digest:
                    raise OcrCacheError("Configured OCR model digest does not match")
        except OcrCacheError:
            raise
        except (OSError, KeyError, zipfile.BadZipFile, RuntimeError) as error:
            raise OcrCacheError("Configured OCR cache could not be validated") from error
    return cache_root


@contextmanager
def validated_ocr_model_snapshot(
    cache: Path,
    *,
    manifest: Sequence[OcrArtifact] = APPROVED_OCR_ARTIFACTS,
) -> Iterator[Path]:
    """Yield private model files extracted from revalidated approved archives."""
    cache_root = resolve_ocr_cache(cache, manifest=manifest)
    with tempfile.TemporaryDirectory(prefix="survey-scribe-ocr-") as directory:
        snapshot = Path(directory)
        for artifact in manifest:
            model_name, model_payload = _approved_model_payload(cache_root, artifact)
            target = snapshot / model_name
            target.write_bytes(model_payload)
        yield snapshot


def _approved_model_payload(cache_root: Path, artifact: OcrArtifact) -> tuple[str, bytes]:
    archive = cache_root / artifact.filename
    model_name = f"{Path(artifact.filename).stem}.pth"
    try:
        with archive.open("rb") as archive_stream:
            details = os.fstat(archive_stream.fileno())
            if (
                details.st_size != artifact.size
                or _sha256_stream(archive_stream) != artifact.sha256
            ):
                raise OcrCacheError("Configured OCR archive changed after validation")
            archive_stream.seek(0)
            with zipfile.ZipFile(archive_stream) as bundle:
                members = tuple(
                    item
                    for item in bundle.infolist()
                    if not item.is_dir() and Path(item.filename).name == model_name
                )
                if len(members) != 1:
                    raise OcrCacheError("Approved OCR archive model member is invalid")
                with bundle.open(members[0]) as model_stream:
                    return model_name, model_stream.read()
    except OcrCacheError:
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError) as error:
        raise OcrCacheError("Configured OCR cache could not be snapshotted") from error


def validate_ocr_cache(
    cache: Path,
    *,
    manifest: Sequence[OcrArtifact] = APPROVED_OCR_ARTIFACTS,
) -> tuple[OcrArtifactValidation, ...]:
    """Validate local files without fetching or redistributing artifacts.

    Args:
        cache: Local directory that contains OCR archives.
        manifest: Expected artifact names, byte sizes, and SHA-256 digests.

    Returns:
        One validation result per manifest item in manifest order.

    Note:
        Validation is caller-enforced. PDF conversion does not call this function
        automatically.
    """
    cache_root = cache.resolve()
    results: list[OcrArtifactValidation] = []
    for artifact in manifest:
        candidate = cache / artifact.filename
        if not candidate.is_file():
            results.append(OcrArtifactValidation(artifact, "missing", False))
            continue
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            results.append(OcrArtifactValidation(artifact, "unsafe", False))
            continue
        if not resolved.is_relative_to(cache_root):
            results.append(OcrArtifactValidation(artifact, "unsafe", False))
            continue
        try:
            if resolved.stat().st_size != artifact.size:
                results.append(OcrArtifactValidation(artifact, "size_mismatch", False))
                continue
            digest = _sha256(resolved)
        except OSError:
            results.append(OcrArtifactValidation(artifact, "unsafe", False))
            continue
        status: OcrValidationStatus = "valid" if digest == artifact.sha256 else "sha256_mismatch"
        results.append(OcrArtifactValidation(artifact, status, True))
    return tuple(results)


def main(
    *,
    environ: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Validate the configured local OCR cache and return a deterministic exit code.

    Args:
        environ: Environment mapping used to locate the cache.
        stdout: Stream for per-artifact status and successful summary output.
        stderr: Stream for configuration and validation failures.

    Returns:
        ``0`` when every artifact is valid, ``1`` after validation failures, or
        ``2`` when no existing cache directory is configured.
    """
    environment = os.environ if environ is None else environ
    output = sys.stdout if stdout is None else stdout
    errors = sys.stderr if stderr is None else stderr
    configured = environment.get("SURVEY_SCRIBE_OCR_CACHE") or environment.get(
        "DOCLING_ARTIFACTS_PATH"
    )
    if not configured:
        errors.write(
            "OCR cache is not configured. Set SURVEY_SCRIBE_OCR_CACHE or DOCLING_ARTIFACTS_PATH.\n"
        )
        return 2
    cache = Path(configured)
    if not cache.is_dir():
        errors.write("Configured OCR cache directory does not exist.\n")
        return 2

    results = validate_ocr_cache(cache)
    status_labels = {
        "valid": "OK",
        "missing": "MISSING",
        "size_mismatch": "SIZE_MISMATCH",
        "sha256_mismatch": "SHA256_MISMATCH",
        "unsafe": "UNSAFE",
    }
    for result in results:
        output.write(f"{status_labels[result.status]} {result.artifact.filename}\n")
    valid_count = sum(result.status == "valid" for result in results)
    if valid_count != len(results):
        errors.write(f"OCR artifact validation failed: {valid_count}/{len(results)} valid.\n")
        return 1
    output.write(f"OCR artifact validation passed: {valid_count}/{len(results)} valid.\n")
    return 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_stream(stream: _ReadableBinary) -> str:
    digest = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()
