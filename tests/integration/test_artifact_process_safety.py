"""Cross-process artifact lock and hard-exit recovery tests."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import pytest

from survey_scribe.errors import ArtifactCollisionError
from survey_scribe.models import DataType, SurveySVIS, SurveyVariable
from survey_scribe.results import ArtifactKind, ExtractionResult

_CHILD_PROGRAM = r"""
import os
import sys
import time
from datetime import date
from pathlib import Path

from survey_scribe.models import DataType, SurveySVIS, SurveyVariable
from survey_scribe.results import ExtractionResult
from survey_scribe.serialization import artifacts

output_dir = Path(sys.argv[1])
run_id = sys.argv[2]
checkpoint = sys.argv[3]
marker = Path(sys.argv[4]) if sys.argv[4] else None

survey = SurveySVIS(
    survey_id="TST_2024_SYNTH",
    country_code="TST",
    year=2024,
    survey_name=f"Synthetic Survey {run_id}",
    variables=[
        SurveyVariable(
            raw_name="q1",
            data_type=DataType.text,
            extraction_confidence=1.0,
        )
    ],
    source_file="questionnaire.pdf",
    source_format="pdf",
    extraction_date=date(2024, 6, 1),
)

def stop_at(stage):
    if stage != checkpoint:
        return
    if marker is not None:
        marker.write_text("locked", encoding="ascii")
        time.sleep(60)
    os._exit(86)

artifacts._publication_checkpoint = stop_at
ExtractionResult(output=survey, run_id=run_id).write(output_dir, overwrite=True)
"""


def _result(run_id: str) -> ExtractionResult[SurveySVIS]:
    return ExtractionResult(
        output=SurveySVIS(
            survey_id="TST_2024_SYNTH",
            country_code="TST",
            year=2024,
            survey_name=f"Synthetic Survey {run_id}",
            variables=[
                SurveyVariable(
                    raw_name="q1",
                    data_type=DataType.text,
                    extraction_confidence=1.0,
                )
            ],
            source_file="questionnaire.pdf",
            source_format="pdf",
            extraction_date=date(2024, 6, 1),
        ),
        run_id=run_id,
    )


def _active_path(result: ExtractionResult[SurveySVIS]) -> Path:
    return next(
        reference.path
        for reference in result.artifacts
        if reference.kind == ArtifactKind.active_pointer
    )


def _wait_for_marker(process: subprocess.Popen[str], marker: Path) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if marker.exists():
            return
        if process.poll() is not None:
            pytest.fail(f"lock holder exited early with code {process.returncode}")
        time.sleep(0.02)
    pytest.fail("timed out waiting for child process to hold the artifact lock")


def _write_after_crash_release(tmp_path: Path) -> ExtractionResult[SurveySVIS]:
    deadline = time.monotonic() + 5
    while True:
        try:
            return _result("after-crash").write(tmp_path)
        except ArtifactCollisionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.02)


def test_process_owned_lock_blocks_a_writer_and_releases_after_crash(tmp_path: Path) -> None:
    marker = tmp_path / "lock-held"
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            _CHILD_PROGRAM,
            str(tmp_path),
            "child",
            "before_generation_commit",
            str(marker),
        ],
        text=True,
    )
    try:
        _wait_for_marker(process, marker)
        with pytest.raises(ArtifactCollisionError):
            _result("contender").write(tmp_path)
    finally:
        process.kill()
        process.wait(timeout=10)

    written = _write_after_crash_release(tmp_path)
    assert written.artifacts


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX hostile pathname replacement")
def test_replacing_lock_path_cannot_admit_a_second_process_writer(tmp_path: Path) -> None:
    marker = tmp_path / "lock-held"
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            _CHILD_PROGRAM,
            str(tmp_path),
            "child",
            "before_generation_commit",
            str(marker),
        ],
        text=True,
    )
    try:
        _wait_for_marker(process, marker)
        lock_path = next((tmp_path / ".survey-scribe" / "aliases").glob("*.lock"))
        lock_path.unlink()
        lock_path.write_bytes(b"hostile replacement")

        with pytest.raises(ArtifactCollisionError):
            _result("contender").write(tmp_path)
    finally:
        process.kill()
        process.wait(timeout=10)

    assert _write_after_crash_release(tmp_path).artifacts


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX hostile directory replacement")
def test_replacing_aliases_directory_cannot_admit_a_second_process_writer(tmp_path: Path) -> None:
    marker = tmp_path / "lock-held"
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            _CHILD_PROGRAM,
            str(tmp_path),
            "child",
            "before_generation_commit",
            str(marker),
        ],
        text=True,
    )
    aliases = tmp_path / ".survey-scribe" / "aliases"
    retained = aliases.with_name("retained-aliases")
    try:
        _wait_for_marker(process, marker)
        aliases.rename(retained)
        aliases.mkdir()

        with pytest.raises(ArtifactCollisionError):
            _result("contender").write(tmp_path)
    finally:
        process.kill()
        process.wait(timeout=10)
        if aliases.exists():
            aliases.rmdir()
        if retained.exists():
            retained.rename(aliases)

    assert _write_after_crash_release(tmp_path).artifacts


@pytest.mark.parametrize(
    ("checkpoint", "immediate_run_id", "expected_run_id"),
    [
        ("before_generation_commit", "prior", "prior"),
        ("after_generation_commit", "prior", "prior"),
        ("before_projection", "prior", "replacement"),
        ("after_commit_marker_clear", None, "replacement"),
        ("after_projection", None, "replacement"),
        ("before_pointer", None, "replacement"),
        ("after_pointer", "replacement", "replacement"),
    ],
)
def test_hard_exit_recovery_is_idempotent_and_keeps_projection_with_pointer(
    tmp_path: Path,
    checkpoint: str,
    immediate_run_id: str | None,
    expected_run_id: str,
) -> None:
    prior = _result("prior").write(tmp_path)
    active_path = _active_path(prior)

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            _CHILD_PROGRAM,
            str(tmp_path),
            "replacement",
            checkpoint,
            "",
        ],
        check=False,
        text=True,
    )
    assert completed.returncode == 86

    if immediate_run_id is None:
        assert not active_path.exists()
        assert (active_path.parent / "transaction").is_dir()
    else:
        immediate_pointer = json.loads(active_path.read_text(encoding="utf-8"))
        immediate_generation = active_path.parent / immediate_pointer["path"]
        immediate_manifest = json.loads(
            (immediate_generation / "manifest.json").read_text(encoding="utf-8")
        )
        immediate_main_name = next(
            item["path"] for item in immediate_manifest["files"] if item["kind"] == "main"
        )
        immediate_projection = tmp_path / "TST_2024_SYNTH_svis.json"
        assert (
            immediate_projection.read_bytes()
            == (immediate_generation / immediate_main_name).read_bytes()
        )
        assert immediate_pointer["run_id"] == immediate_run_id

    with pytest.raises(ArtifactCollisionError):
        _result("recovery-probe").write(tmp_path)
    with pytest.raises(ArtifactCollisionError):
        _result("second-recovery-probe").write(tmp_path)

    pointer = json.loads(active_path.read_text(encoding="utf-8"))
    generation = active_path.parent / pointer["path"]
    manifest = json.loads((generation / "manifest.json").read_text(encoding="utf-8"))
    main_name = next(item["path"] for item in manifest["files"] if item["kind"] == "main")
    projection = tmp_path / "TST_2024_SYNTH_svis.json"
    assert projection.read_bytes() == (generation / main_name).read_bytes()
    assert pointer["run_id"] == expected_run_id
    assert not (active_path.parent / "transaction").exists()
    assert not any(path.name.endswith(".staging") for path in active_path.parent.rglob("*"))
