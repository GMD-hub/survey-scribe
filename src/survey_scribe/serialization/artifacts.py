"""Transactional local artifact generation and publication."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, TypeVar
from uuid import uuid4

from pydantic import BaseModel

from survey_scribe.errors import (
    ArtifactCollisionError,
    ArtifactWriteError,
    redact_data,
    redact_exception,
)
from survey_scribe.results import ArtifactKind, ArtifactReference, ExtractionResult
from survey_scribe.serialization.legacy import legacy_json_bytes

T = TypeVar("T")

_INTERNAL_ROOT = ".survey-scribe"
_SURVEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True)
class _Generation(Generic[T]):
    generation_id: str
    directory: Path
    main_path: Path
    sidecar_path: Path | None
    manifest_path: Path
    main_content: bytes
    references: tuple[ArtifactReference, ...]


def write_result(
    result: ExtractionResult[T],
    output_dir: Path,
    *,
    sidecar: bool = True,
    overwrite: bool = False,
) -> ExtractionResult[T]:
    """Publish an immutable generation and atomically switch stable readers."""
    if result.output is None:
        raise ArtifactWriteError("validation", "A failed result has no main output to write")
    survey_id = result.survey_id
    if survey_id is None:
        raise ArtifactWriteError("validation", "The result has no survey_id")
    _validate_survey_id(survey_id)

    root = output_dir.resolve()
    survey_root = root / _INTERNAL_ROOT / survey_id
    legacy_path = root / f"{survey_id}_svis.json"
    active_path = survey_root / "active.json"
    try:
        survey_root.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise ArtifactWriteError("setup", redact_exception(error)) from None

    with _survey_lock(survey_root):
        if not overwrite and (active_path.exists() or legacy_path.exists()):
            raise ArtifactCollisionError(
                f"Artifacts already exist for survey {survey_id}; pass overwrite=True"
            )
        try:
            generation = _write_generation(result, survey_root, sidecar=sidecar)
        except Exception as error:
            if isinstance(error, ArtifactWriteError):
                raise
            sensitive_values = _questionnaire_text(result.output)
            raise ArtifactWriteError(
                "generation",
                redact_exception(error, sensitive_values=sensitive_values),
            ) from None

        backup_path: Path | None = None
        projection_written = False
        try:
            backup_path = _backup_projection(legacy_path)
            _atomic_write_bytes(legacy_path, generation.main_content)
            projection_written = True
        except Exception as error:
            _remove_if_exists(backup_path)
            raise ArtifactWriteError("projection", redact_exception(error)) from None

        pointer_content = _json_bytes(
            {
                "schema_version": 1,
                "survey_id": survey_id,
                "run_id": result.run_id,
                "generation_id": generation.generation_id,
                "path": f"generations/{generation.generation_id}",
                "manifest_sha256": _sha256(generation.manifest_path.read_bytes()),
            }
        )
        try:
            _atomic_write_bytes(active_path, pointer_content)
        except Exception as error:
            rollback_error = _rollback_projection(
                legacy_path,
                backup_path=backup_path,
                projection_written=projection_written,
            )
            message = redact_exception(error)
            if rollback_error is not None:
                message = f"{message}; projection rollback: {redact_exception(rollback_error)}"
            raise ArtifactWriteError("pointer", message) from None
        _remove_if_exists(backup_path)

        references = generation.references + (
            ArtifactReference(
                kind=ArtifactKind.legacy,
                path=legacy_path,
                generation_id=generation.generation_id,
                sha256=_sha256(generation.main_content),
            ),
            ArtifactReference(
                kind=ArtifactKind.active_pointer,
                path=active_path,
                generation_id=generation.generation_id,
                sha256=_sha256(pointer_content),
            ),
        )
        return result.model_copy(update={"artifacts": references})


def _validate_survey_id(survey_id: str) -> None:
    if survey_id in {".", ".."} or _SURVEY_ID.fullmatch(survey_id) is None:
        raise ArtifactWriteError(
            "validation",
            "survey_id must contain only letters, numbers, dot, underscore, or hyphen",
        )


@contextmanager
def _survey_lock(survey_root: Path) -> Any:
    lock_path = survey_root / ".write.lock"
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ArtifactCollisionError(
            f"Another artifact writer is active for survey {survey_root.name}"
        ) from None
    except OSError as error:
        raise ArtifactWriteError("lock", redact_exception(error)) from None
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(f"pid={os.getpid()}\n".encode("ascii"))
            stream.flush()
            os.fsync(stream.fileno())
        yield
    finally:
        with suppress(OSError):
            lock_path.unlink(missing_ok=True)


def _write_generation(
    result: ExtractionResult[T], survey_root: Path, *, sidecar: bool
) -> _Generation[T]:
    generation_id = uuid4().hex
    generation_directory = survey_root / "generations" / generation_id
    generation_directory.mkdir(parents=True, exist_ok=False)
    survey_id = result.survey_id
    if survey_id is None or result.output is None:
        raise ArtifactWriteError("validation", "A writable result requires output and survey_id")
    main_path = generation_directory / f"{survey_id}_svis.json"
    sidecar_path = generation_directory / f"{survey_id}_sidecar.json" if sidecar else None
    manifest_path = generation_directory / "manifest.json"
    main_content = legacy_json_bytes(result.output)
    references: list[ArtifactReference] = []
    file_records: list[dict[str, Any]] = []
    try:
        _write_new_file(main_path, main_content)
        main_digest = _sha256(main_content)
        references.append(
            ArtifactReference(
                kind=ArtifactKind.main,
                path=main_path,
                generation_id=generation_id,
                sha256=main_digest,
            )
        )
        file_records.append(
            {
                "kind": "main",
                "path": main_path.name,
                "sha256": main_digest,
                "size": len(main_content),
            }
        )
        if sidecar_path is not None:
            sidecar_values = result.model_dump(mode="json", exclude={"output", "artifacts"})
            sidecar_content = _json_bytes(
                redact_data(
                    sidecar_values,
                    sensitive_values=_questionnaire_text(result.output),
                )
            )
            _write_new_file(sidecar_path, sidecar_content)
            sidecar_digest = _sha256(sidecar_content)
            references.append(
                ArtifactReference(
                    kind=ArtifactKind.sidecar,
                    path=sidecar_path,
                    generation_id=generation_id,
                    sha256=sidecar_digest,
                )
            )
            file_records.append(
                {
                    "kind": "sidecar",
                    "path": sidecar_path.name,
                    "sha256": sidecar_digest,
                    "size": len(sidecar_content),
                }
            )
        manifest_content = _json_bytes(
            {
                "schema_version": 1,
                "survey_id": survey_id,
                "run_id": result.run_id,
                "generation_id": generation_id,
                "files": file_records,
            }
        )
        _write_new_file(manifest_path, manifest_content)
        references.append(
            ArtifactReference(
                kind=ArtifactKind.manifest,
                path=manifest_path,
                generation_id=generation_id,
                sha256=_sha256(manifest_content),
            )
        )
        _validate_generation(generation_directory, file_records, manifest_path)
        _fsync_directory(generation_directory)
    except Exception:
        shutil.rmtree(generation_directory, ignore_errors=True)
        raise
    return _Generation(
        generation_id=generation_id,
        directory=generation_directory,
        main_path=main_path,
        sidecar_path=sidecar_path,
        manifest_path=manifest_path,
        main_content=main_content,
        references=tuple(references),
    )


def _write_new_file(path: Path, content: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _validate_generation(
    generation_directory: Path,
    file_records: list[dict[str, Any]],
    manifest_path: Path,
) -> None:
    json.loads(manifest_path.read_text(encoding="utf-8"))
    for record in file_records:
        path = generation_directory / str(record["path"])
        content = path.read_bytes()
        json.loads(content)
        if len(content) != record["size"] or _sha256(content) != record["sha256"]:
            raise OSError(f"Artifact validation failed for {path.name}")


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        _fsync_directory(path.parent)
    finally:
        temporary_path.unlink(missing_ok=True)


def _backup_projection(path: Path) -> Path | None:
    if not path.exists():
        return None
    descriptor, backup_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".backup", dir=path.parent
    )
    os.close(descriptor)
    backup_path = Path(backup_name)
    try:
        shutil.copyfile(path, backup_path)
        with backup_path.open("ab") as stream:
            os.fsync(stream.fileno())
    except Exception:
        backup_path.unlink(missing_ok=True)
        raise
    return backup_path


def _rollback_projection(
    legacy_path: Path,
    *,
    backup_path: Path | None,
    projection_written: bool,
) -> OSError | None:
    if not projection_written:
        return None
    try:
        if backup_path is None:
            legacy_path.unlink(missing_ok=True)
        else:
            os.replace(backup_path, legacy_path)
        _fsync_directory(legacy_path.parent)
    except OSError as error:
        return error
    return None


def _remove_if_exists(path: Path | None) -> None:
    if path is not None:
        path.unlink(missing_ok=True)


def _questionnaire_text(output: Any) -> tuple[str, ...]:
    values = output.model_dump(mode="python") if isinstance(output, BaseModel) else output
    found: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "question_text" and isinstance(item, str) and item:
                    found.append(item)
                else:
                    collect(item)
        elif isinstance(value, list | tuple):
            for item in value:
                collect(item)

    collect(values)
    return tuple(found)


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)
