"""Deterministic artifact validation, recovery, and filesystem edge cases."""

from __future__ import annotations

import ctypes
import errno
import json
import os
import stat
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pydantic import BaseModel, ValidationError

from survey_scribe.errors import ArtifactCollisionError, ArtifactWriteError
from survey_scribe.models import SurveySVIS
from survey_scribe.results import ArtifactKind, ExtractionResult
from survey_scribe.serialization import artifacts
from survey_scribe.serialization.artifacts import (
    ArtifactPlan,
    JsonArtifactSerializer,
    SerializedArtifact,
    SurveySVISArtifactSerializer,
)


class GenericOutput(BaseModel):
    survey_id: str
    values: list[int] = []


def _result(*, survey_id: str = "EDGE_CASE", run_id: str = "run-edge") -> ExtractionResult:
    return ExtractionResult(
        output=GenericOutput(survey_id=survey_id, values=[1]),
        run_id=run_id,
    )


def _main_file(
    *,
    generation_filename: str = "EDGE_CASE_result.json",
    content: bytes = b"{}",
    publication_filename: str | None = "EDGE_CASE_result.json",
    publication_kind: ArtifactKind | str | None = ArtifactKind.projection,
) -> SerializedArtifact:
    return SerializedArtifact(
        kind=ArtifactKind.main,
        generation_filename=generation_filename,
        content=content,
        publication_filename=publication_filename,
        publication_kind=publication_kind,
    )


@pytest.mark.parametrize(
    ("plan_factory", "message"),
    [
        (
            lambda: ArtifactPlan(
                survey_id="EDGE_CASE", files=(_main_file(),), manifest_schema_version=2
            ),
            "schema version",
        ),
        (lambda: ArtifactPlan(survey_id="EDGE_CASE", files=()), "exactly one main"),
        (
            lambda: ArtifactPlan(
                survey_id="EDGE_CASE",
                files=(
                    _main_file(publication_filename=None, publication_kind=None),
                    SerializedArtifact(
                        kind=ArtifactKind.sidecar,
                        generation_filename="EDGE_CASE_result.json",
                        content=b"{}",
                    ),
                ),
            ),
            "generation filenames must be unique",
        ),
        (
            lambda: ArtifactPlan(
                survey_id="EDGE_CASE",
                files=(_main_file(content=cast(bytes, "not-bytes")),),
            ),
            "content must be bytes",
        ),
        (
            lambda: ArtifactPlan(
                survey_id="EDGE_CASE",
                files=(_main_file(publication_filename=None),),
            ),
            "publication kind requires",
        ),
        (
            lambda: ArtifactPlan(
                survey_id="EDGE_CASE",
                files=(_main_file(publication_kind=None),),
            ),
            "publication filename requires",
        ),
        (
            lambda: ArtifactPlan(
                survey_id="EDGE_CASE",
                files=(
                    _main_file(),
                    SerializedArtifact(
                        kind=ArtifactKind.sidecar,
                        generation_filename="other.json",
                        content=b"{}",
                        publication_filename="EDGE_CASE_result.json",
                        publication_kind=ArtifactKind.sidecar,
                    ),
                ),
            ),
            "publication filenames must be unique",
        ),
    ],
)
def test_artifact_plan_rejects_inconsistent_files(plan_factory: Any, message: str) -> None:
    with pytest.raises(ArtifactWriteError, match=message):
        plan_factory()


def test_json_serializer_wraps_snapshot_validation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingAdapter:
        def __init__(self, output_type: type[Any]) -> None:
            del output_type

        def dump_python(self, output: Any, *, mode: str) -> Any:
            del output, mode
            raise ValueError("snapshot rejected")

    monkeypatch.setattr(artifacts, "TypeAdapter", FailingAdapter)

    with pytest.raises(ArtifactWriteError, match="snapshot rejected"):
        JsonArtifactSerializer(GenericOutput).build_plan(
            GenericOutput(survey_id="EDGE_CASE"), survey_id="EDGE_CASE"
        )


def test_json_serializer_wraps_legacy_encoding_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_encoding(value: Any) -> bytes:
        del value
        raise TypeError("JSON keys must be strings")

    monkeypatch.setattr(artifacts, "legacy_json_bytes", fail_encoding)

    with pytest.raises(ArtifactWriteError, match="JSON keys must be strings"):
        JsonArtifactSerializer(GenericOutput).build_plan(
            GenericOutput(survey_id="EDGE_CASE"), survey_id="EDGE_CASE"
        )


def test_svis_serializer_requires_exact_runtime_type() -> None:
    with pytest.raises(ArtifactWriteError, match="exact output type"):
        SurveySVISArtifactSerializer().build_plan(cast(SurveySVIS, object()), survey_id="EDGE_CASE")


def test_svis_serializer_wraps_detached_validation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = SurveySVIS(
        survey_id="EDGE_CASE",
        country_code="TST",
        year=2024,
        survey_name="Synthetic Survey",
        variables=[],
        source_file="questionnaire.pdf",
        source_format="pdf",
        extraction_date=date(2024, 6, 1),
    )
    validation_error = ValidationError.from_exception_data("SurveySVIS", [])

    def fail_validation(value: Any) -> SurveySVIS:
        del value
        raise validation_error

    monkeypatch.setattr(SurveySVIS, "model_validate", fail_validation)

    with pytest.raises(ArtifactWriteError, match="ValidationError"):
        SurveySVISArtifactSerializer().build_plan(output, survey_id="EDGE_CASE")


def test_result_without_string_identity_keeps_survey_id_unset() -> None:
    class NonStringIdentity:
        survey_id = 42

    result = ExtractionResult(output=NonStringIdentity())

    assert result.survey_id is None


def test_write_rejects_missing_result_identity_before_setup(tmp_path: Path) -> None:
    result = ExtractionResult[dict[str, int]](output={"value": 1})

    with pytest.raises(ArtifactWriteError, match="no survey_id"):
        result.write(tmp_path)

    assert not tmp_path.exists() or list(tmp_path.iterdir()) == []


def test_write_wraps_unexpected_serializer_failure(tmp_path: Path) -> None:
    class FailingSerializer:
        def build_plan(self, output: GenericOutput, *, survey_id: str) -> ArtifactPlan:
            del output, survey_id
            raise RuntimeError("serializer failed")

    with pytest.raises(ArtifactWriteError, match="serializer failed") as error:
        _result().write(tmp_path, serializer=FailingSerializer())

    assert error.value.stage == "validation"


def test_write_rejects_plan_for_another_survey(tmp_path: Path) -> None:
    class MismatchedSerializer:
        def build_plan(self, output: GenericOutput, *, survey_id: str) -> ArtifactPlan:
            del output, survey_id
            return ArtifactPlan(
                survey_id="OTHER_SURVEY",
                files=(
                    _main_file(
                        generation_filename="OTHER_SURVEY_result.json",
                        publication_filename="OTHER_SURVEY_result.json",
                    ),
                ),
            )

    with pytest.raises(ArtifactWriteError, match="plan survey_id"):
        _result().write(tmp_path, serializer=MismatchedSerializer())


def test_write_preserves_setup_artifact_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def reject_setup(parent: Path, name: str) -> Path:
        del parent, name
        raise ArtifactWriteError("path", "unsafe setup component")

    monkeypatch.setattr(artifacts, "_ensure_directory", reject_setup)

    with pytest.raises(ArtifactWriteError, match="unsafe setup component") as error:
        _result().write(tmp_path)

    assert error.value.stage == "path"


def test_write_wraps_unexpected_recovery_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_alias(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise RuntimeError("alias storage unavailable")

    monkeypatch.setattr(artifacts, "_claim_identity_alias", fail_alias)

    with pytest.raises(ArtifactWriteError, match="alias storage unavailable") as error:
        _result().write(tmp_path)

    assert error.value.stage == "recovery"


def test_write_preserves_generation_artifact_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_generation(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        raise ArtifactWriteError("generation", "known generation failure")

    monkeypatch.setattr(artifacts, "_write_generation", fail_generation)

    with pytest.raises(ArtifactWriteError, match="known generation failure") as error:
        _result().write(tmp_path)

    assert error.value.stage == "generation"


@pytest.mark.parametrize(
    ("raised", "expected_stage"),
    [
        (ArtifactWriteError("recovery", "stale transaction"), "recovery"),
        (RuntimeError("journal creation failed"), "journal"),
    ],
)
def test_write_classifies_transaction_setup_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    raised: Exception,
    expected_stage: str,
) -> None:
    def fail_transaction(*args: Any, **kwargs: Any) -> Path:
        del args, kwargs
        raise raised

    monkeypatch.setattr(artifacts, "_prepare_transaction", fail_transaction)

    with pytest.raises(ArtifactWriteError) as error:
        _result().write(tmp_path)

    assert error.value.stage == expected_stage


def test_write_detects_generation_content_changed_before_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_prepare = artifacts._prepare_transaction

    def corrupt_after_prepare(
        root: Path,
        survey_root: Path,
        survey_id: str,
        generation: artifacts._Generation,
        pointer: artifacts._ActivePointer,
    ) -> Path:
        transaction = original_prepare(root, survey_root, survey_id, generation, pointer)
        source_name = generation.publications[0].source_filename
        (generation.directory / source_name).write_bytes(b'{"changed": true}')
        return transaction

    monkeypatch.setattr(artifacts, "_prepare_transaction", corrupt_after_prepare)

    with pytest.raises(ArtifactWriteError, match="digest changed") as error:
        _result().write(tmp_path)

    assert error.value.stage == "projection"
    assert not (tmp_path / "EDGE_CASE_result.json").exists()


def test_write_without_sidecar_or_projection_records_only_generation_files(
    tmp_path: Path,
) -> None:
    class GenerationOnlySerializer:
        def build_plan(self, output: GenericOutput, *, survey_id: str) -> ArtifactPlan:
            del output
            return ArtifactPlan(
                survey_id=survey_id,
                files=(
                    _main_file(
                        publication_filename=None,
                        publication_kind=None,
                    ),
                ),
            )

    written = _result().write(
        tmp_path,
        sidecar=False,
        serializer=GenerationOnlySerializer(),
    )

    assert {reference.kind for reference in written.artifacts} == {
        ArtifactKind.main,
        ArtifactKind.manifest,
        ArtifactKind.active_pointer,
    }
    manifest_path = next(
        reference.path for reference in written.artifacts if reference.kind == ArtifactKind.manifest
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert [record["kind"] for record in manifest["files"]] == [ArtifactKind.main]
    assert not (tmp_path / "EDGE_CASE_result.json").exists()


def test_generation_failure_removes_uncommitted_staging_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def reject_generation(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise OSError("manifest validation failed")

    monkeypatch.setattr(artifacts, "_validate_generation", reject_generation)

    with pytest.raises(ArtifactWriteError, match="manifest validation failed"):
        _result().write(tmp_path)

    staging_paths = list((tmp_path / ".survey-scribe" / "surveys").rglob("*.staging"))
    assert staging_paths == []


def test_failure_after_generation_commit_preserves_recoverable_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_after_commit(stage: str) -> None:
        if stage == "after_generation_commit":
            raise OSError("post-commit checkpoint failed")

    monkeypatch.setattr(artifacts, "_publication_checkpoint", fail_after_commit)

    with pytest.raises(ArtifactWriteError, match="post-commit checkpoint failed"):
        _result().write(tmp_path)

    generations_root = next((tmp_path / ".survey-scribe" / "surveys").glob("*/generations"))
    assert len([path for path in generations_root.iterdir() if path.is_dir()]) == 1
    assert not any(path.name.endswith(".staging") for path in generations_root.iterdir())


def test_transaction_failure_removes_staging_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_replace = artifacts._durable_replace

    def reject_transaction_commit(source: Path, destination: Path) -> None:
        if source.name.startswith(".transaction."):
            raise OSError("transaction commit failed")
        original_replace(source, destination)

    monkeypatch.setattr(artifacts, "_durable_replace", reject_transaction_commit)

    with pytest.raises(ArtifactWriteError, match="transaction commit failed") as error:
        _result().write(tmp_path)

    assert error.value.stage == "journal"
    staging_paths = list((tmp_path / ".survey-scribe" / "surveys").rglob("*.staging"))
    assert staging_paths == []


def test_sync_failure_after_transaction_rename_leaves_recoverable_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_sync = artifacts._fsync_directory
    failed = False

    def fail_after_transaction_rename(path: Path) -> None:
        nonlocal failed
        if not failed and (path / "transaction").is_dir():
            failed = True
            raise OSError("transaction directory sync failed")
        original_sync(path)

    monkeypatch.setattr(artifacts, "_fsync_directory", fail_after_transaction_rename)

    with pytest.raises(ArtifactWriteError, match="transaction directory sync failed"):
        _result().write(tmp_path)

    transaction = next((tmp_path / ".survey-scribe" / "surveys").glob("*/transaction"))
    assert transaction.is_dir()
    with pytest.raises(ArtifactCollisionError):
        _result(run_id="recovery-probe").write(tmp_path)
    assert not transaction.exists()


def test_prepare_transaction_rejects_existing_recovery_state(tmp_path: Path) -> None:
    survey_root = tmp_path / "survey"
    survey_root.mkdir()
    (survey_root / "transaction").mkdir()
    generation_id = "1" * 32
    generation = artifacts._Generation(
        generation_id=generation_id,
        directory=tmp_path / "generation",
        manifest_content=b"{}",
        references=(),
        publications=(),
    )
    pointer = artifacts._ActivePointer(
        survey_id="EDGE_CASE",
        run_id="run-edge",
        generation_id=generation_id,
        path=f"generations/{generation_id}",
        manifest_sha256="0" * 64,
    )

    with pytest.raises(ArtifactWriteError, match="unrecovered"):
        artifacts._prepare_transaction(
            tmp_path,
            survey_root,
            "EDGE_CASE",
            generation,
            pointer,
        )


def test_corrupt_exact_identity_is_rejected(tmp_path: Path) -> None:
    written = _result().write(tmp_path)
    main = next(reference for reference in written.artifacts if reference.kind == ArtifactKind.main)
    identity_path = main.path.parents[2] / "identity.json"
    identity_path.write_text('{"schema_version": 1, "survey_id": "OTHER"}', encoding="utf-8")

    with pytest.raises(ArtifactWriteError, match="exact survey identity"):
        _result(run_id="replacement").write(tmp_path, overwrite=True)


@pytest.mark.parametrize(
    ("alias_content", "message"),
    [
        (b"not-json", "JSONDecodeError"),
        (b'{"schema_version": 1, "survey_id": "OTHER"}', "aliases another"),
    ],
)
def test_corrupt_portable_identity_alias_is_rejected(
    tmp_path: Path,
    alias_content: bytes,
    message: str,
) -> None:
    _result().write(tmp_path)
    alias_path = next((tmp_path / ".survey-scribe" / "aliases").glob("*.json"))
    alias_path.write_bytes(alias_content)

    with pytest.raises(ArtifactWriteError, match=message):
        _result(run_id="replacement").write(tmp_path, overwrite=True)


def _journal_payload(*, generation_id: str = "1" * 32) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "survey_id": "EDGE_CASE",
        "generation_id": generation_id,
        "phase": "prepared",
        "pointer": {
            "schema_version": 1,
            "survey_id": "EDGE_CASE",
            "run_id": "run-edge",
            "generation_id": generation_id,
            "path": f"generations/{generation_id}",
            "manifest_sha256": "0" * 64,
        },
        "publications": [],
        "backups": [],
    }


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda payload: payload.update(survey_id="OTHER"), "survey identity"),
        (
            lambda payload: payload["pointer"].update(generation_id="2" * 32),
            "generation identity",
        ),
        (
            lambda payload: payload["pointer"].update(path=f"generations/{'2' * 32}"),
            "pointer path",
        ),
        (
            lambda payload: payload["backups"].append(
                {
                    "scope": "survey",
                    "filename": "other.json",
                    "backup_filename": None,
                }
            ),
            "pointer backup path",
        ),
        (
            lambda payload: payload["backups"].append(
                {
                    "scope": "output",
                    "filename": "EDGE_CASE_result.json",
                    "backup_filename": "../backup.bin",
                }
            ),
            "backup path",
        ),
    ],
)
def test_load_journal_rejects_inconsistent_recovery_metadata(
    tmp_path: Path, mutate: Any, message: str
) -> None:
    payload = _journal_payload()
    mutate(payload)
    journal_path = tmp_path / "journal.json"
    journal_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ArtifactWriteError, match=message):
        artifacts._load_journal(journal_path, "EDGE_CASE")


@pytest.mark.parametrize("content", [b"not-json", b"{}"])
def test_load_journal_wraps_parser_and_schema_errors(tmp_path: Path, content: bytes) -> None:
    journal_path = tmp_path / "journal.json"
    journal_path.write_bytes(content)

    with pytest.raises(ArtifactWriteError, match="recovery"):
        artifacts._load_journal(journal_path, "EDGE_CASE")


def _recovery_tree(tmp_path: Path) -> tuple[Path, Path, dict[str, Any]]:
    root = tmp_path / "output"
    survey_root = root / ".survey-scribe" / "survey"
    generation_id = "1" * 32
    generation = survey_root / "generations" / generation_id
    transaction = survey_root / "transaction"
    generation.mkdir(parents=True)
    transaction.mkdir()
    publication_content = b'{"value": 1}'
    manifest_content = artifacts._json_bytes(
        {
            "schema_version": 1,
            "survey_id": "EDGE_CASE",
            "run_id": "run-edge",
            "generation_id": generation_id,
            "files": [
                {
                    "kind": "main",
                    "path": "EDGE_CASE_result.json",
                    "sha256": artifacts._sha256(publication_content),
                    "size": len(publication_content),
                }
            ],
        }
    )
    (generation / "manifest.json").write_bytes(manifest_content)
    (generation / "EDGE_CASE_result.json").write_bytes(publication_content)
    payload = _journal_payload(generation_id=generation_id)
    payload["pointer"]["manifest_sha256"] = artifacts._sha256(manifest_content)
    payload["publications"] = [
        {
            "filename": "EDGE_CASE_result.json",
            "source_filename": "EDGE_CASE_result.json",
            "kind": "projection",
            "sha256": artifacts._sha256(publication_content),
        }
    ]
    (transaction / "journal.json").write_text(json.dumps(payload), encoding="utf-8")
    return root, survey_root, payload


@pytest.mark.parametrize(
    ("corrupt_name", "message"),
    [
        ("manifest.json", "manifest digest"),
        ("EDGE_CASE_result.json", "publication digest"),
    ],
)
def test_recovery_rejects_changed_generation_content(
    tmp_path: Path, corrupt_name: str, message: str
) -> None:
    root, survey_root, payload = _recovery_tree(tmp_path)
    generation = survey_root / "generations" / payload["generation_id"]
    (generation / corrupt_name).write_bytes(b'{"corrupt": true}')

    with pytest.raises(ArtifactWriteError, match=message):
        artifacts._recover_transaction(root, survey_root, "EDGE_CASE")

    assert (survey_root / "transaction").exists()


def test_recovery_rejects_journal_publications_that_differ_from_manifest(tmp_path: Path) -> None:
    root, survey_root, payload = _recovery_tree(tmp_path)
    payload["publications"] = []
    (survey_root / "transaction" / "journal.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    with pytest.raises(ArtifactWriteError, match="publications do not match"):
        artifacts._recover_transaction(root, survey_root, "EDGE_CASE")


def test_rollback_skips_unpublished_targets_and_removes_new_targets(tmp_path: Path) -> None:
    root = tmp_path / "output"
    survey_root = root / "survey"
    transaction = survey_root / "transaction"
    transaction.mkdir(parents=True)
    output_target = root / "projection.json"
    pointer_target = survey_root / "active.json"
    output_target.write_bytes(b"new output")
    pointer_target.write_bytes(b"new pointer")
    journal = artifacts._PublicationJournal(
        survey_id="EDGE_CASE",
        generation_id="1" * 32,
        phase="prepared",
        pointer=artifacts._ActivePointer(
            survey_id="EDGE_CASE",
            run_id="run-edge",
            generation_id="1" * 32,
            path=f"generations/{'1' * 32}",
            manifest_sha256="0" * 64,
        ),
        publications=(),
        backups=(
            artifacts._JournalBackup(
                scope="output", filename="projection.json", backup_filename=None
            ),
            artifacts._JournalBackup(scope="survey", filename="active.json", backup_filename=None),
        ),
    )

    assert (
        artifacts._rollback_transaction(
            root,
            survey_root,
            transaction,
            journal,
            restore_publications=False,
            restore_pointer=True,
        )
        is None
    )
    assert output_target.read_bytes() == b"new output"
    assert not pointer_target.exists()
    assert not transaction.exists()


@pytest.mark.parametrize(
    ("name", "message"),
    [
        (".invalid.staging", "generation staging"),
        (".transaction.invalid.staging", "transaction staging"),
    ],
)
def test_cleanup_rejects_untrusted_staging_names(tmp_path: Path, name: str, message: str) -> None:
    survey_root = tmp_path / "survey"
    generations = survey_root / "generations"
    generations.mkdir(parents=True)
    parent = survey_root if name.startswith(".transaction.") else generations
    (parent / name).mkdir()

    with pytest.raises(ArtifactWriteError, match=message):
        artifacts._cleanup_staging(survey_root)


def test_cleanup_removes_valid_generation_and_transaction_staging(tmp_path: Path) -> None:
    survey_root = tmp_path / "survey"
    generations = survey_root / "generations"
    generations.mkdir(parents=True)
    generation_staging = generations / f".{'1' * 32}.staging"
    transaction_staging = survey_root / f".transaction.{'2' * 32}.staging"
    (generation_staging / "nested").mkdir(parents=True)
    (generation_staging / "nested" / "artifact.json").write_text("{}", encoding="utf-8")
    transaction_staging.mkdir()

    artifacts._cleanup_staging(survey_root)

    assert not generation_staging.exists()
    assert not transaction_staging.exists()


def test_validate_generation_rejects_invalid_manifest_json(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_bytes(b"not-json")

    with pytest.raises(json.JSONDecodeError):
        artifacts._validate_generation(tmp_path, [], manifest_path)


def test_validate_generation_rejects_record_digest_mismatch(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    artifact_path = tmp_path / "artifact.json"
    manifest_path.write_bytes(b"{}")
    artifact_path.write_bytes(b"{}")
    records = [
        {
            "path": "artifact.json",
            "size": 2,
            "sha256": "0" * 64,
        }
    ]

    with pytest.raises(OSError, match="validation failed"):
        artifacts._validate_generation(tmp_path, records, manifest_path)


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor-relative lock contract")
def test_lock_open_failure_is_classified_as_lock_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_open = artifacts.os.open

    def fail_open(
        path: Any,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if path == "survey.lock" and dir_fd is not None:
            raise OSError(errno.EIO, "lock device failed")
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(artifacts.os, "open", fail_open)

    with (
        pytest.raises(ArtifactWriteError, match="lock device failed") as error,
        artifacts._survey_lock(tmp_path / "survey.lock", "EDGE_CASE"),
    ):
        pytest.fail("lock unexpectedly acquired")

    assert error.value.stage == "lock"


@pytest.mark.skipif(os.name == "nt", reason="POSIX os.replace failure contract")
def test_atomic_write_removes_temporary_file_after_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_replace(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise OSError("replace failed")

    monkeypatch.setattr(artifacts.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        artifacts._atomic_write_bytes(tmp_path / "target.json", b"{}")

    assert list(tmp_path.iterdir()) == []


def test_read_rejects_file_that_changes_during_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "artifact.json"
    path.write_bytes(b"{}")
    details = os.lstat(path)
    changed = SimpleNamespace(
        st_mode=details.st_mode,
        st_dev=details.st_dev + 1,
        st_ino=details.st_ino,
    )
    monkeypatch.setattr(artifacts, "_reject_reparse", lambda *args, **kwargs: changed)

    with pytest.raises(OSError, match="changed during"):
        artifacts._read_bytes_no_follow(path)


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor validation contract")
def test_read_rejects_descriptor_that_is_not_regular(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "artifact.json"
    path.write_bytes(b"{}")
    real_fstat = artifacts.os.fstat
    before = os.lstat(path)
    calls = 0

    def non_regular_fstat(descriptor: int) -> Any:
        nonlocal calls
        calls += 1
        if calls == 2:
            return SimpleNamespace(st_mode=stat.S_IFDIR, st_dev=before.st_dev, st_ino=before.st_ino)
        return real_fstat(descriptor)

    monkeypatch.setattr(artifacts.os, "fstat", non_regular_fstat)

    with pytest.raises(OSError, match="not a regular file"):
        artifacts._read_bytes_no_follow(path)


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor-relative operation contract")
@pytest.mark.parametrize("operation", ["new", "replace"])
def test_write_retains_verified_parent_during_hostile_path_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    parent = tmp_path / "parent"
    parent.mkdir()
    retained = tmp_path / "retained"
    outside = tmp_path / "outside"
    outside.mkdir()
    target = parent / "artifact.json"
    if operation == "replace":
        target.write_bytes(b"old")

    real_open = artifacts.os.open
    swapped = False

    def swap_after_parent_open(
        path: str | os.PathLike[str],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
        if not swapped and dir_fd is None and Path(path) == parent:
            parent.rename(retained)
            parent.symlink_to(outside, target_is_directory=True)
            swapped = True
        return descriptor

    monkeypatch.setattr(artifacts.os, "open", swap_after_parent_open)

    if operation == "new":
        artifacts._write_new_file(target, b"safe")
    else:
        artifacts._atomic_write_bytes(target, b"safe")

    assert (retained / target.name).read_bytes() == b"safe"
    assert list(outside.iterdir()) == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX ancestor identity contract")
def test_registered_ancestor_replacement_is_rejected_before_write(tmp_path: Path) -> None:
    internal = tmp_path / ".survey-scribe"
    parent = internal / "surveys"
    parent.mkdir(parents=True)
    retained = tmp_path / "retained-internal"

    with artifacts._directory_identity_scope((tmp_path, internal, parent)):
        internal.rename(retained)
        parent.mkdir(parents=True)

        with pytest.raises(ArtifactWriteError, match="anchor changed"):
            artifacts._write_new_file(parent / "escaped.json", b"unsafe")

    assert not (parent / "escaped.json").exists()


def test_directory_identity_scope_rejects_unsafe_paths_and_registers_once(tmp_path: Path) -> None:
    regular = tmp_path / "regular"
    regular.write_bytes(b"x")
    with (
        pytest.raises(ArtifactWriteError, match="anchor is unsafe"),
        artifacts._directory_identity_scope((regular,)),
    ):
        pytest.fail("unsafe identity scope entered")
    with (
        pytest.raises(ArtifactWriteError, match="path"),
        artifacts._directory_identity_scope((tmp_path / "missing",)),
    ):
        pytest.fail("missing identity scope entered")

    child = tmp_path / "child"
    child.mkdir()
    artifacts._register_directory_identity(child)
    assert artifacts._ACTIVE_DIRECTORY_IDENTITIES.get() == ()
    with artifacts._directory_identity_scope((tmp_path,)):
        artifacts._register_directory_identity(child)
        artifacts._register_directory_identity(child)
        assert len(artifacts._ACTIVE_DIRECTORY_IDENTITIES.get()) == 2
        artifacts._verify_active_directory_chain(Path("unrelated"))


def test_reject_reparse_enforces_expected_path_type(tmp_path: Path) -> None:
    regular_file = tmp_path / "artifact.json"
    regular_file.write_bytes(b"{}")
    directory = tmp_path / "directory"
    directory.mkdir()

    with pytest.raises(ArtifactWriteError, match="not a directory"):
        artifacts._reject_reparse(regular_file, require_directory=True)
    with pytest.raises(ArtifactWriteError, match="not a regular file"):
        artifacts._reject_reparse(directory, require_directory=False)


@pytest.mark.parametrize(
    ("entry_mode", "message"),
    [
        (stat.S_IFLNK, "symlink or reparse"),
        (0, "unexpected artifact path"),
    ],
)
@pytest.mark.skipif(os.name == "nt", reason="POSIX mode-bit removal contract")
def test_safe_remove_tree_refuses_unsafe_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    entry_mode: int,
    message: str,
) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    entry = root / "entry"
    entry.write_bytes(b"data")
    real_stat = artifacts.os.stat

    def unsafe_entry_stat(path: Any, *args: Any, **kwargs: Any) -> Any:
        if path == entry.name and kwargs.get("dir_fd") is not None:
            return SimpleNamespace(st_mode=entry_mode, st_file_attributes=0)
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(artifacts.os, "stat", unsafe_entry_stat)

    with pytest.raises(OSError, match=message):
        artifacts._safe_remove_tree(root)


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory fsync contract")
def test_remove_file_durable_handles_missing_and_existing_targets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    synced: list[int] = []
    target = tmp_path / "artifact.json"

    monkeypatch.setattr(artifacts.os, "fsync", synced.append)
    artifacts._remove_file_durable(target)
    target.write_bytes(b"{}")
    artifacts._remove_file_durable(target)

    assert not target.exists()
    assert len(synced) == 1


def test_posix_lock_helpers_delegate_to_flock(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[int, int]] = []
    fake_fcntl = SimpleNamespace(
        LOCK_EX=1,
        LOCK_NB=2,
        LOCK_UN=4,
        flock=lambda descriptor, operation: calls.append((descriptor, operation)),
    )

    monkeypatch.setattr(artifacts, "os", SimpleNamespace(name="posix"))
    monkeypatch.setitem(__import__("sys").modules, "fcntl", fake_fcntl)
    artifacts._lock_descriptor(7)
    artifacts._unlock_descriptor(7)

    assert calls == [(7, 3), (7, 4)]


def test_posix_durable_replace_uses_atomic_os_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del monkeypatch
    source = tmp_path / "source.tmp"
    destination = tmp_path / "destination.json"
    source.write_bytes(b"replacement")

    artifacts._durable_replace(source, destination)

    assert destination.read_bytes() == b"replacement"
    assert not source.exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory fsync contract")
def test_posix_directory_sync_closes_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, int]] = []
    real_close = artifacts.os.close

    monkeypatch.setattr(
        artifacts.os,
        "fsync",
        lambda descriptor: calls.append(("fsync", descriptor)),
    )

    def close(descriptor: int) -> None:
        calls.append(("close", descriptor))
        real_close(descriptor)

    monkeypatch.setattr(artifacts.os, "close", close)

    artifacts._fsync_directory(tmp_path)

    assert [name for name, _ in calls] == ["fsync", "close"]
    assert calls[0][1] == calls[1][1]


@pytest.mark.skipif(os.name != "nt", reason="Windows durable replacement branch")
def test_windows_durable_replace_propagates_move_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingMove:
        argtypes: Any = None
        restype: Any = None

        def __call__(self, *args: Any) -> bool:
            del args
            return False

    kernel32 = SimpleNamespace(MoveFileExW=FailingMove())
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: kernel32)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 5)

    with pytest.raises(OSError):
        artifacts._durable_replace(Path("source"), Path("destination"))


class _WindowsFunction:
    def __init__(self, result: Any) -> None:
        self.result = result
        self.argtypes: Any = None
        self.restype: Any = None

    def __call__(self, *args: Any) -> Any:
        del args
        return self.result


@pytest.mark.skipif(os.name != "nt", reason="Windows directory flush branch")
@pytest.mark.parametrize("create_failed", [True, False])
def test_windows_directory_sync_propagates_handle_and_flush_failures(
    monkeypatch: pytest.MonkeyPatch, create_failed: bool
) -> None:
    from ctypes import wintypes

    invalid_handle = wintypes.HANDLE(-1).value
    kernel32 = SimpleNamespace(
        CreateFileW=_WindowsFunction(invalid_handle if create_failed else 21),
        FlushFileBuffers=_WindowsFunction(False),
        CloseHandle=_WindowsFunction(True),
    )
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: kernel32)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 5)

    with pytest.raises(OSError):
        artifacts._fsync_directory(Path("directory"))


class _WindowsApiFunction:
    def __init__(self, callback: Any) -> None:
        self.callback = callback
        self.argtypes: Any = None
        self.restype: Any = None

    def __call__(self, *args: Any) -> Any:
        return self.callback(*args)


def test_windows_handle_helpers_validate_identity_and_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    close_calls: list[int] = []

    def information(_handle: object, pointer: Any) -> bool:
        pointer._obj.file_attributes = 0x10
        pointer._obj.file_index_high = 2
        pointer._obj.file_index_low = 3
        return True

    kernel32 = SimpleNamespace(
        CreateFileW=_WindowsApiFunction(lambda *_args: 21),
        GetFileInformationByHandle=_WindowsApiFunction(information),
        CloseHandle=_WindowsApiFunction(lambda handle: close_calls.append(handle) or True),
    )
    monkeypatch.setattr(ctypes, "WinDLL", lambda *_args, **_kwargs: kernel32, raising=False)
    monkeypatch.setattr(ctypes, "WinError", lambda code: OSError(code), raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 5, raising=False)

    assert artifacts._open_windows_handle(Path("directory"), require_directory=True) == (
        21,
        (2 << 32) | 3,
    )
    artifacts._close_windows_handle(21)
    assert close_calls == [21]


@pytest.mark.parametrize("failure", ["create", "information", "reparse", "type"])
def test_windows_handle_helpers_reject_unsafe_or_failed_handles(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    from ctypes import wintypes

    close_calls: list[int] = []

    def information(_handle: object, pointer: Any) -> bool:
        if failure == "information":
            return False
        pointer._obj.file_attributes = 0x400 if failure == "reparse" else 0
        pointer._obj.file_index_high = 0
        pointer._obj.file_index_low = 1
        return True

    handle = wintypes.HANDLE(-1).value if failure == "create" else 21
    kernel32 = SimpleNamespace(
        CreateFileW=_WindowsApiFunction(lambda *_args: handle),
        GetFileInformationByHandle=_WindowsApiFunction(information),
        CloseHandle=_WindowsApiFunction(lambda value: close_calls.append(value) or True),
    )
    monkeypatch.setattr(ctypes, "WinDLL", lambda *_args, **_kwargs: kernel32, raising=False)
    monkeypatch.setattr(ctypes, "WinError", lambda code: OSError(code), raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 5, raising=False)

    expected = OSError if failure in {"create", "information"} else ArtifactWriteError
    with pytest.raises(expected):
        artifacts._open_windows_handle(Path("unsafe"), require_directory=True)
    if failure in {"information", "reparse", "type"}:
        assert close_calls == [21]


def test_windows_handle_close_failure_is_propagated(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel32 = SimpleNamespace(CloseHandle=_WindowsApiFunction(lambda _handle: False))
    monkeypatch.setattr(ctypes, "WinDLL", lambda *_args, **_kwargs: kernel32, raising=False)
    monkeypatch.setattr(ctypes, "WinError", lambda code: OSError(code), raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 5, raising=False)

    with pytest.raises(OSError):
        artifacts._close_windows_handle(21)


def test_windows_file_descriptor_helpers_transfer_or_close_handles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    opened: list[tuple[int, int]] = []
    closed: list[int] = []
    fake_msvcrt = SimpleNamespace(
        open_osfhandle=lambda handle, flags: opened.append((handle, flags)) or 31
    )
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
    monkeypatch.setattr(artifacts, "_open_windows_handle", lambda *_args, **_kwargs: (21, 1))
    monkeypatch.setattr(artifacts, "_close_windows_handle", closed.append)

    assert artifacts._open_windows_file_no_follow(Path("file")) == 31
    assert artifacts._open_windows_lock_file(Path("lock")) == 31
    assert opened == [(21, os.O_RDONLY), (21, os.O_RDWR)]

    fake_msvcrt.open_osfhandle = lambda *_args: (_ for _ in ()).throw(OSError("failed"))
    with pytest.raises(OSError):
        artifacts._open_windows_file_no_follow(Path("file"))
    assert closed == [21]


def test_windows_remove_tree_handles_regular_nested_content_and_rejects_symlink(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    nested = root / "nested"
    nested.mkdir(parents=True)
    (root / "file.json").write_text("{}", encoding="utf-8")
    (nested / "child.json").write_text("{}", encoding="utf-8")

    artifacts._safe_remove_tree_windows(root)
    assert not root.exists()

    root.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("safe", encoding="utf-8")
    link = root / "link"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(OSError, match="symlink or reparse"):
        artifacts._safe_remove_tree_windows(root)


def test_portable_windows_branches_use_handle_based_operations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.tmp"
    destination = tmp_path / "destination.json"
    source.write_text("replacement", encoding="utf-8")
    move = _WindowsApiFunction(lambda *_args: True)
    kernel32 = SimpleNamespace(
        MoveFileExW=move,
        CreateFileW=_WindowsApiFunction(lambda *_args: 21),
        FlushFileBuffers=_WindowsApiFunction(lambda _handle: True),
        CloseHandle=_WindowsApiFunction(lambda _handle: True),
    )
    monkeypatch.setattr(ctypes, "WinDLL", lambda *_args, **_kwargs: kernel32, raising=False)
    monkeypatch.setattr(ctypes, "WinError", lambda code: OSError(code), raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 5, raising=False)
    monkeypatch.setattr(artifacts.os, "name", "nt")

    artifacts._durable_replace(source, destination)
    artifacts._fsync_directory(tmp_path)

    assert move.argtypes is not None
    assert move.restype is not None
