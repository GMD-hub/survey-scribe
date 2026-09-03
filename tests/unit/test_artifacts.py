"""Transactional artifact and redaction tests."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from threading import Event
from typing import Any

import pytest

from survey_scribe.errors import (
    ArtifactCollisionError,
    ArtifactWriteError,
    redact_data,
    redact_exception,
    redact_text,
)
from survey_scribe.models import DataType, SurveySVIS, SurveyVariable
from survey_scribe.results import Diagnostic, ExtractionResult, FailedBlock, ResultStatus
from survey_scribe.serialization import artifacts


def _result(
    *,
    survey_id: str = "TST_2024_SYNTH",
    run_id: str = "run-1",
    diagnostic_message: str = "complete",
) -> ExtractionResult[SurveySVIS]:
    survey = SurveySVIS(
        survey_id=survey_id,
        country_code="TST",
        year=2024,
        survey_name="Synthetic Survey",
        variables=[
            SurveyVariable(
                raw_name="q1",
                question_text="What is the private answer?",
                data_type=DataType.text,
                extraction_confidence=1.0,
            )
        ],
        source_file="questionnaire.pdf",
        source_format="pdf",
        extraction_date=date(2024, 6, 1),
    )
    return ExtractionResult(
        output=survey,
        run_id=run_id,
        diagnostics=(Diagnostic(code="TEST_DIAGNOSTIC", message=diagnostic_message),),
    )


def _active_pointer(output_dir: Path, survey_id: str = "TST_2024_SYNTH") -> Path:
    matches = list((output_dir / ".survey-scribe" / "surveys").glob("*/active.json"))
    matching = [
        path
        for path in matches
        if json.loads(path.read_text(encoding="utf-8"))["survey_id"] == survey_id
    ]
    assert len(matching) == 1
    return matching[0]


def test_write_creates_valid_generation_projection_and_new_frozen_result(tmp_path: Path) -> None:
    original = _result()

    written = original.write(tmp_path)

    assert written is not original
    assert original.artifacts == ()
    assert written.status is ResultStatus.success
    assert written.artifacts
    pointer = json.loads(_active_pointer(tmp_path).read_text(encoding="utf-8"))
    generation = _active_pointer(tmp_path).parent / pointer["path"]
    main_path = generation / "TST_2024_SYNTH_svis.json"
    sidecar_path = generation / "TST_2024_SYNTH_sidecar.json"
    manifest_path = generation / "manifest.json"
    legacy_path = tmp_path / "TST_2024_SYNTH_svis.json"
    assert SurveySVIS.model_validate_json(main_path.read_text(encoding="utf-8")) == original.output
    assert legacy_path.read_bytes() == main_path.read_bytes()
    assert json.loads(sidecar_path.read_text(encoding="utf-8"))["status"] == "success"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["run_id"] == "run-1"
    assert {item["kind"] for item in manifest["files"]} == {"main", "sidecar"}


def test_default_collision_and_overwrite_create_a_new_generation(tmp_path: Path) -> None:
    first = _result(run_id="run-1").write(tmp_path)
    first_pointer = json.loads(_active_pointer(tmp_path).read_text(encoding="utf-8"))

    with pytest.raises(ArtifactCollisionError):
        _result(run_id="run-2").write(tmp_path)

    second = _result(run_id="run-2").write(tmp_path, overwrite=True)
    second_pointer = json.loads(_active_pointer(tmp_path).read_text(encoding="utf-8"))
    generations = _active_pointer(tmp_path).parent / "generations"

    assert first.artifacts != second.artifacts
    assert first_pointer["generation_id"] != second_pointer["generation_id"]
    assert (generations / first_pointer["generation_id"]).is_dir()
    assert (generations / second_pointer["generation_id"]).is_dir()


def test_concurrent_same_survey_write_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered = Event()
    release = Event()
    original_write_generation = artifacts._write_generation

    def slow_write_generation(*args: Any, **kwargs: Any) -> Any:
        entered.set()
        assert release.wait(timeout=5)
        return original_write_generation(*args, **kwargs)

    monkeypatch.setattr(artifacts, "_write_generation", slow_write_generation)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(_result(run_id="run-1").write, tmp_path)
        assert entered.wait(timeout=5)
        second = executor.submit(_result(run_id="run-2").write, tmp_path)
        with pytest.raises(ArtifactCollisionError):
            second.result(timeout=5)
        release.set()
        assert first.result(timeout=5).artifacts


@pytest.mark.parametrize("stage", ["generation", "projection", "pointer"])
def test_write_failure_preserves_prior_active_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    _result(run_id="prior").write(tmp_path)
    pointer_path = _active_pointer(tmp_path)
    legacy_path = tmp_path / "TST_2024_SYNTH_svis.json"
    prior_pointer = pointer_path.read_bytes()
    prior_legacy = legacy_path.read_bytes()

    if stage == "generation":

        def fail_generation(*args: Any, **kwargs: Any) -> Any:
            raise OSError("generation failed with api_key=should-not-leak")

        monkeypatch.setattr(artifacts, "_write_generation", fail_generation)
    else:
        original_atomic_write = artifacts._atomic_write_bytes
        failed = False

        def fail_stage(path: Path, content: bytes) -> None:
            nonlocal failed
            target_stage = "pointer" if path.name == "active.json" else "projection"
            if target_stage == stage and not failed:
                failed = True
                raise OSError(f"{stage} failed with Authorization: Bearer should-not-leak")
            original_atomic_write(path, content)

        monkeypatch.setattr(artifacts, "_atomic_write_bytes", fail_stage)

    with pytest.raises(ArtifactWriteError) as error:
        _result(run_id="replacement").write(tmp_path, overwrite=True)

    assert "should-not-leak" not in str(error.value)
    assert pointer_path.read_bytes() == prior_pointer
    assert legacy_path.read_bytes() == prior_legacy


@pytest.mark.parametrize(
    "survey_id",
    ["../escape", "..\\escape", "/absolute", "C:\\absolute", ".", ".."],
)
def test_path_traversal_survey_ids_are_rejected(tmp_path: Path, survey_id: str) -> None:
    with pytest.raises(ArtifactWriteError):
        _result(survey_id=survey_id).write(tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_recursive_redaction_handles_headers_urls_values_and_nested_exceptions() -> None:
    questionnaire_text = "What is your secret income?"
    value = {
        "authorization": "Bearer visible-token",
        "nested": [
            "https://example.test/v1?api_key=url-secret&safe=yes",
            {"question_text": questionnaire_text, "safe": "kept"},
        ],
    }
    try:
        try:
            raise ValueError("endpoint?access_token=nested-secret")
        except ValueError as cause:
            raise RuntimeError(f"Failed on {questionnaire_text}") from cause
    except RuntimeError as error:
        rendered_error = redact_exception(error, sensitive_values=(questionnaire_text,))

    redacted = redact_data(value, sensitive_values=(questionnaire_text,))
    rendered = json.dumps(redacted)
    assert "visible-token" not in rendered
    assert "url-secret" not in rendered
    assert questionnaire_text not in rendered
    assert "nested-secret" not in rendered_error
    assert questionnaire_text not in rendered_error
    assert redacted["nested"][1]["safe"] == "kept"


@pytest.mark.parametrize(
    "value",
    [
        "Authorization: Basic basic-secret",
        "Authorization: ApiKey api-secret",
        "Authorization=Basic basic-secret",
        "Proxy-Authorization: Custom proxy-secret",
        "Proxy-Authorization=Custom proxy-secret",
        "bearer_token=bearer-secret",
        '{"client_secret":"json-secret"}',
        r"{\"api_key\":\"escaped-secret\"}",
        "https://user:password@example.test/v1",
        "https://example.test/v1?client_secret=query-secret",
    ],
)
def test_free_text_redacts_common_credential_forms(value: str) -> None:
    rendered = redact_text(value)

    for secret in (
        "basic-secret",
        "api-secret",
        "proxy-secret",
        "json-secret",
        "password",
        "query-secret",
        "bearer-secret",
        "escaped-secret",
    ):
        assert secret not in rendered


def test_sidecar_redacts_diagnostics_and_questionnaire_text(tmp_path: Path) -> None:
    message = (
        "Authorization: Bearer sidecar-secret while processing "
        "What is the private answer? at https://example.test?api_key=query-secret"
    )

    written = _result(diagnostic_message=message).write(tmp_path)
    sidecar = next(item.path for item in written.artifacts if item.kind == "sidecar")
    rendered = sidecar.read_text(encoding="utf-8")

    assert "sidecar-secret" not in rendered
    assert "query-secret" not in rendered
    assert "What is the private answer?" not in rendered


def test_legacy_sidecar_uses_fixed_records_for_all_operational_prose(tmp_path: Path) -> None:
    private_values = (
        "Private diagnostic code",
        "Private source label",
        "Private raw reference",
        "Private source quote",
        "Private native expression",
        "Private adapter error",
        "Private failed block identifier",
        "Private failed block message",
    )
    result = _result().model_copy(
        update={
            "diagnostics": (
                Diagnostic(
                    code=private_values[0],
                    message=private_values[1],
                    details={
                        "raw_reference": private_values[2],
                        "source_quote": private_values[3],
                        "native_expression": private_values[4],
                        "adapter_error": private_values[5],
                    },
                ),
            ),
            "failed_blocks": (
                FailedBlock(
                    block_id=private_values[6],
                    message=private_values[7],
                    source_order=4,
                ),
            ),
        }
    )

    written = result.write(tmp_path)
    sidecar = next(item.path for item in written.artifacts if item.kind == "sidecar")
    rendered = sidecar.read_text(encoding="utf-8")
    payload = json.loads(rendered)

    assert all(private not in rendered for private in private_values)
    assert payload["diagnostics"] == [
        {
            "code": "OPERATIONAL_DIAGNOSTIC",
            "details": {},
            "message": "Diagnostic content omitted from artifact sidecar.",
            "severity": "warning",
        }
    ]
    assert payload["failed_blocks"] == [
        {
            "block_id": "failed-block-000001",
            "message": "Source block content omitted from artifact sidecar.",
            "source_order": 4,
        }
    ]


def test_failed_result_cannot_write_artifacts(tmp_path: Path) -> None:
    failed = ExtractionResult[SurveySVIS](output=None, survey_id="TST_2024_SYNTH")

    with pytest.raises(ArtifactWriteError):
        failed.write(tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_required_directory_sync_failure_aborts_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_directory_sync(path: Path) -> None:
        raise OSError(f"directory sync failed for {path.name}")

    monkeypatch.setattr(artifacts, "_fsync_directory", fail_directory_sync)

    with pytest.raises(ArtifactWriteError, match="directory sync failed"):
        _result().write(tmp_path)

    assert not (tmp_path / "TST_2024_SYNTH_svis.json").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory fsync failure contract")
def test_projection_directory_sync_failure_rolls_back_prior_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _result(run_id="prior").write(tmp_path)
    pointer_path = _active_pointer(tmp_path)
    projection_path = tmp_path / "TST_2024_SYNTH_svis.json"
    prior_pointer = pointer_path.read_bytes()
    prior_projection = projection_path.read_bytes()
    original_sync = artifacts.os.fsync
    output_identity = os.stat(tmp_path)
    failed = False

    def fail_first_projection_sync(descriptor: int) -> None:
        nonlocal failed
        details = os.fstat(descriptor)
        if (details.st_dev, details.st_ino) == (
            output_identity.st_dev,
            output_identity.st_ino,
        ) and not failed:
            failed = True
            raise OSError("required projection directory sync failed")
        original_sync(descriptor)

    monkeypatch.setattr(artifacts.os, "fsync", fail_first_projection_sync)

    with pytest.raises(ArtifactWriteError, match="required projection directory sync failed"):
        _result(run_id="replacement").write(tmp_path, overwrite=True)

    assert failed is True
    assert pointer_path.read_bytes() == prior_pointer
    assert projection_path.read_bytes() == prior_projection


@pytest.mark.skipif(os.name == "nt", reason="POSIX hostile pathname replacement")
def test_lock_identity_change_stops_before_public_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replaced = False

    def replace_lock(stage: str) -> None:
        nonlocal replaced
        if stage != "before_generation_commit" or replaced:
            return
        lock_path = next((tmp_path / ".survey-scribe" / "aliases").glob("*.lock"))
        lock_path.unlink()
        lock_path.write_bytes(b"hostile replacement")
        replaced = True

    monkeypatch.setattr(artifacts, "_publication_checkpoint", replace_lock)

    with pytest.raises(ArtifactWriteError, match="lock identity changed"):
        _result().write(tmp_path)

    assert not (tmp_path / "TST_2024_SYNTH_svis.json").exists()
    assert not list((tmp_path / ".survey-scribe" / "surveys").glob("*/active.json"))
