"""End-to-end command contracts with deterministic public result fakes."""

from __future__ import annotations

import json
import multiprocessing
from pathlib import Path
from typing import Any

import pytest

from survey_scribe import (
    ArtifactWriteError,
    Diagnostic,
    ExtractionResult,
    FailedBlock,
    cli,
)
from survey_scribe.results import DiagnosticSeverity

from .conftest import FakeClient, make_svis


def _reserve_manifest_worker(
    output_dir: str,
    overwrite: bool,
    acquired: Any,
    release: Any,
    outcomes: Any,
) -> None:
    try:
        with cli._reserve_batch_manifest(Path(output_dir), overwrite=overwrite):
            outcomes.put("acquired")
            acquired.set()
            release.wait(timeout=10)
    except Exception as error:
        outcomes.put(getattr(error, "code", type(error).__name__))


def _partial(survey_id: str = "TST_2026_PARTIAL") -> ExtractionResult[Any]:
    return ExtractionResult(
        output=make_svis(survey_id),
        diagnostics=(
            Diagnostic(
                code="BLOCK_FAILED",
                message="Private source text omitted.",
                severity=DiagnosticSeverity.error,
            ),
        ),
        failed_blocks=(FailedBlock(block_id="private-block", message="Private text"),),
    )


def _failed(code: str = "SOURCE_INPUT_INVALID") -> ExtractionResult[Any]:
    return ExtractionResult(
        output=None,
        diagnostics=(
            Diagnostic(
                code=code,
                message="Private source text omitted.",
                severity=DiagnosticSeverity.error,
            ),
        ),
    )


def test_convert_success_writes_default_artifact_set(
    tmp_path: Path,
    cli_environment: None,
    fake_client_factory: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del cli_environment
    source = tmp_path / "questionnaire.txt"
    source.write_text("private questionnaire text", encoding="utf-8")
    output = tmp_path / "output"
    client: FakeClient = fake_client_factory(ExtractionResult(output=make_svis()))

    assert cli.main(["convert", str(source), "-o", str(output)]) == 0

    captured = capsys.readouterr()
    assert client.converted == [source]
    assert "status=success" in captured.out
    assert "failed_blocks=0" in captured.out
    assert "artifact main=" in captured.out
    assert "artifact sidecar=" in captured.out
    assert "artifact manifest=" in captured.out
    assert (output / "TST_2026_CLI_svis.json").is_file()


def test_convert_partial_default_succeeds_and_strict_fails(
    tmp_path: Path,
    cli_environment: None,
    fake_client_factory: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del cli_environment
    output = tmp_path / "output"
    fake_client_factory(_partial())
    assert cli.main(["convert", "input.txt", "-o", str(output)]) == 0
    assert "status=partial" in capsys.readouterr().out

    fake_client_factory(_partial("TST_2026_STRICT"))
    assert cli.main(["convert", "input.txt", "-o", str(output), "--strict"]) == 1
    assert "status=partial" in capsys.readouterr().err


def test_convert_failed_is_nonzero_and_does_not_write(
    tmp_path: Path,
    cli_environment: None,
    fake_client_factory: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del cli_environment
    output = tmp_path / "output"
    fake_client_factory(_failed())

    assert cli.main(["convert", "missing.txt", "-o", str(output)]) == 1

    captured = capsys.readouterr()
    assert "status=failed" in captured.err
    assert "SOURCE_INPUT_INVALID" in captured.err
    assert not output.exists()


def test_convert_rejects_partial_without_sidecar_before_write(
    tmp_path: Path,
    cli_environment: None,
    fake_client_factory: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del cli_environment
    output = tmp_path / "output"
    fake_client_factory(_partial())

    assert cli.main(["convert", "input.txt", "-o", str(output), "--no-sidecar"]) == 1

    assert "PARTIAL_REQUIRES_SIDECAR" in capsys.readouterr().err
    assert not output.exists()


def test_convert_success_allows_no_sidecar(
    tmp_path: Path,
    cli_environment: None,
    fake_client_factory: Any,
) -> None:
    del cli_environment
    output = tmp_path / "output"
    fake_client_factory(ExtractionResult(output=make_svis()))

    assert cli.main(["convert", "input.txt", "-o", str(output), "--no-sidecar"]) == 0

    manifest_paths = tuple(output.glob(".survey-scribe/surveys/*/generations/*/manifest.json"))
    assert len(manifest_paths) == 1
    generation = json.loads(manifest_paths[0].read_text(encoding="utf-8"))
    assert all(record["kind"] != "sidecar" for record in generation["files"])


def test_convert_reports_collision_and_overwrite_replaces_projection(
    tmp_path: Path,
    cli_environment: None,
    fake_client_factory: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del cli_environment
    output = tmp_path / "output"
    fake_client_factory(ExtractionResult(output=make_svis()))
    assert cli.main(["convert", "input.txt", "-o", str(output)]) == 0
    capsys.readouterr()

    fake_client_factory(ExtractionResult(output=make_svis()))
    assert cli.main(["convert", "input.txt", "-o", str(output)]) == 1
    assert "ARTIFACT_COLLISION" in capsys.readouterr().err

    fake_client_factory(ExtractionResult(output=make_svis()))
    assert cli.main(["convert", "input.txt", "-o", str(output), "--overwrite"]) == 0


def test_convert_write_failure_is_nonzero_and_redacted(
    tmp_path: Path,
    cli_environment: None,
    fake_client_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del cli_environment
    result = ExtractionResult(output=make_svis())
    fake_client_factory(result)

    def fail_write(*_args: object, **_kwargs: object) -> ExtractionResult[Any]:
        raise ArtifactWriteError("projection", "api_key=cli-secret")

    monkeypatch.setattr(ExtractionResult, "write", fail_write)
    assert cli.main(["convert", "input.txt", "-o", str(tmp_path)]) == 1

    captured = capsys.readouterr()
    assert "ARTIFACT_WRITE_FAILED" in captured.err
    assert "cli-secret" not in captured.out + captured.err
    assert "[REDACTED]" in captured.err


@pytest.mark.parametrize(
    ("statuses", "strict", "expected"),
    [
        (("success", "partial"), False, 0),
        (("success", "failed"), False, 1),
        (("success", "partial"), True, 1),
        (("success", "success"), True, 0),
    ],
)
def test_batch_aggregate_exit_and_shared_manifest(
    tmp_path: Path,
    cli_environment: None,
    fake_client_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    statuses: tuple[str, str],
    strict: bool,
    expected: int,
) -> None:
    del cli_environment
    results = []
    for index, status in enumerate(statuses):
        if status == "success":
            results.append(ExtractionResult(output=make_svis(f"TST_2026_S{index}")))
        elif status == "partial":
            results.append(_partial(f"TST_2026_P{index}"))
        else:
            results.append(_failed())
    fake_client_factory(*results)
    monkeypatch.setattr(cli, "_new_batch_run_id", lambda: "batch-run")
    output = tmp_path / "output"
    arguments = ["batch", "one.txt", "two.txt", "-o", str(output)]
    if strict:
        arguments.append("--strict")

    assert cli.main(arguments) == expected

    manifest = json.loads((output / "batch_manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_id"] == "batch-run"
    assert [item["index"] for item in manifest["inputs"]] == [0, 1]
    assert [item["source_name"] for item in manifest["inputs"]] == ["one.txt", "two.txt"]
    assert [item["status"] for item in manifest["inputs"]] == list(statuses)
    rendered = json.dumps(manifest)
    assert "PRIVATE QUESTIONNAIRE TEXT" not in rendered
    assert "cli-secret" not in rendered


def test_batch_write_failure_and_manifest_collision_are_nonzero(
    tmp_path: Path,
    cli_environment: None,
    fake_client_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del cli_environment
    output = tmp_path / "output"
    result = ExtractionResult(output=make_svis())
    fake_client_factory(result)

    def fail_write(*_args: object, **_kwargs: object) -> ExtractionResult[Any]:
        raise ArtifactWriteError("manifest", "write denied")

    monkeypatch.setattr(ExtractionResult, "write", fail_write)
    assert cli.main(["batch", "one.txt", "-o", str(output)]) == 1
    manifest = json.loads((output / "batch_manifest.json").read_text(encoding="utf-8"))
    assert manifest["inputs"][0]["write_error"]["code"] == "ARTIFACT_WRITE_FAILED"

    replacement = fake_client_factory(_failed())
    assert cli.main(["batch", "two.txt", "-o", str(output)]) == 1
    assert replacement.converted == []


def test_batch_partial_without_sidecar_records_policy_failure(
    tmp_path: Path,
    cli_environment: None,
    fake_client_factory: Any,
) -> None:
    del cli_environment
    output = tmp_path / "output"
    fake_client_factory(_partial())

    assert cli.main(["batch", "one.txt", "-o", str(output), "--no-sidecar"]) == 1

    manifest = json.loads((output / "batch_manifest.json").read_text(encoding="utf-8"))
    assert manifest["inputs"][0]["write_error"]["code"] == "PARTIAL_REQUIRES_SIDECAR"


def test_batch_holds_manifest_reservation_through_conversion_and_publication(
    tmp_path: Path,
    cli_environment: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del cli_environment
    output = tmp_path / "output"
    reservation = output / ".batch_manifest.json.lock"

    class ReservedClient(FakeClient):
        def convert_many(self, sources: Any) -> list[ExtractionResult[Any]]:
            assert reservation.is_file()
            return super().convert_many(sources)

    client = ReservedClient([ExtractionResult(output=make_svis())])
    monkeypatch.setattr(cli, "_create_client", lambda _config: client)
    write_manifest = cli._write_batch_manifest

    def assert_reserved(*args: Any, **kwargs: Any) -> Path:
        assert reservation.is_file()
        return write_manifest(*args, **kwargs)

    monkeypatch.setattr(cli, "_write_batch_manifest", assert_reserved)

    assert cli.main(["batch", "one.txt", "-o", str(output)]) == 0
    assert not reservation.exists()


@pytest.mark.parametrize("overwrite", [False, True])
def test_batch_manifest_reservation_is_exclusive_across_processes(
    tmp_path: Path,
    overwrite: bool,
) -> None:
    context = multiprocessing.get_context("spawn")
    acquired = context.Event()
    release = context.Event()
    outcomes = context.Queue()
    output = tmp_path / "output"
    first = context.Process(
        target=_reserve_manifest_worker,
        args=(str(output), overwrite, acquired, release, outcomes),
    )
    second_acquired = context.Event()
    second = context.Process(
        target=_reserve_manifest_worker,
        args=(str(output), overwrite, second_acquired, release, outcomes),
    )
    try:
        first.start()
        assert acquired.wait(timeout=10)
        assert outcomes.get(timeout=10) == "acquired"
        second.start()
        assert outcomes.get(timeout=10) == "ARTIFACT_COLLISION"
    finally:
        release.set()
        for process in (first, second):
            process.join(timeout=10)
            if process.is_alive():
                process.terminate()
                process.join(timeout=10)

    assert first.exitcode == 0
    assert second.exitcode == 0
    assert not (output / ".batch_manifest.json.lock").exists()


def test_providers_reports_presets_without_false_verified_claim(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["providers"]) == 0

    output = capsys.readouterr().out
    assert "openai\tpreset\tconfiguration-only" in output
    assert "custom\texplicit\tconfiguration-only" in output
    assert "azure/azure_openai\tadapter\tconfiguration-only" in output
    assert "verified model rows: none" in output


def test_schema_export_remains_exact(capsys: pytest.CaptureFixture[str]) -> None:
    from survey_scribe.models.routing import canonical_routing_schema_json

    assert cli.main(["schema", "export", "routing"]) == 0
    captured = capsys.readouterr()
    assert captured.out == canonical_routing_schema_json()
    assert captured.err == ""
