"""Offline checksum validation for approved local EasyOCR artifacts."""

from __future__ import annotations

import hashlib
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TextIO


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
