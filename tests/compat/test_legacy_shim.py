"""Compatibility tests for the sole deprecated root entry point."""

from __future__ import annotations

import importlib
import json
import os
import sys
import warnings
from datetime import date
from pathlib import Path
from typing import Any

import pytest

import survey_scribe
from survey_scribe import Diagnostic, DiagnosticCode, ExtractionResult, SurveySVIS


def _reload_shim() -> Any:
    sys.modules.pop("docling_pipeline", None)
    return importlib.import_module("docling_pipeline")


def test_import_is_lazy_and_warning_is_emitted_once(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("openai", "instructor", "anthropic", "docling", "itsai"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    shim = _reload_shim()

    assert all(
        name not in sys.modules
        for name in ("openai", "instructor", "anthropic", "docling", "itsai")
    )
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        shim._warn_deprecated()
        shim._warn_deprecated()
    assert len(captured) == 1
    assert issubclass(captured[0].category, DeprecationWarning)


def test_run_preserves_signature_writes_result_and_returns_none(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    shim = _reload_shim()
    source = tmp_path / "questionnaire.pdf"
    source.write_bytes(b"%PDF-synthetic")
    output = tmp_path / "output"
    written: list[tuple[Path, bool, bool]] = []
    svis = SurveySVIS(
        survey_id="TST_2026_SYN",
        country_code="TST",
        year=2026,
        survey_name="Synthetic",
        variables=[],
        source_file=source.name,
        source_format="pdf",
        extraction_date=date(2026, 9, 3),
    )

    class Result(ExtractionResult[SurveySVIS]):
        def write(
            self,
            output_dir: str | os.PathLike[str],
            *,
            sidecar: bool = True,
            overwrite: bool = False,
            serializer: object | None = None,
        ) -> ExtractionResult[SurveySVIS]:
            del serializer
            written.append((Path(output_dir), sidecar, overwrite))
            return self

    class Client:
        @classmethod
        def from_config(cls, path: object, *, resolve_environment: bool) -> Client:
            assert path is None
            assert resolve_environment
            return cls()

        def __enter__(self) -> Client:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

        def convert(self, path: Path) -> ExtractionResult[SurveySVIS]:
            assert path == source
            return Result(output=svis)

    monkeypatch.setattr(survey_scribe, "SurveyScribe", Client)

    assert shim.run(source, output) is None
    assert written == [(output, False, True)]


def test_partial_run_requires_diagnostic_sidecar(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    shim = _reload_shim()
    source = tmp_path / "questionnaire.pdf"
    source.write_bytes(b"%PDF-synthetic")
    output = tmp_path / "output"
    svis = SurveySVIS(
        survey_id="TST_2026_PARTIAL",
        country_code="TST",
        year=2026,
        survey_name="Partial",
        variables=[],
        source_file=source.name,
        source_format="pdf",
        extraction_date=date(2026, 9, 3),
    )

    result = ExtractionResult(
        output=svis,
        diagnostics=(
            Diagnostic(
                code=DiagnosticCode.metadata_incomplete,
                message="Required metadata used deterministic fallbacks.",
            ),
        ),
    )

    class Client:
        @classmethod
        def from_config(cls, path: object, *, resolve_environment: bool) -> Client:
            assert path is None
            assert resolve_environment
            return cls()

        def __enter__(self) -> Client:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

        def convert(self, path: Path) -> ExtractionResult[SurveySVIS]:
            assert path == source
            return result

    monkeypatch.setattr(survey_scribe, "SurveyScribe", Client)

    assert shim.run(source, output) is None
    assert (output / "TST_2026_PARTIAL_svis.json").is_file()
    sidecars = tuple(output.rglob("TST_2026_PARTIAL_sidecar.json"))
    assert len(sidecars) == 1
    sidecar = json.loads(sidecars[0].read_text(encoding="utf-8"))
    assert sidecar["status"] == "partial"
    assert len(sidecar["diagnostics"]) == 1


def test_cli_shape_and_explicit_config_forwarding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    shim = _reload_shim()
    source = tmp_path / "questionnaire.pdf"
    source.write_bytes(b"%PDF-synthetic")
    output = tmp_path / "output"
    config = tmp_path / "settings.toml"
    calls: list[tuple[Path, Path, Path | None]] = []
    monkeypatch.setattr(
        shim,
        "_run",
        lambda path, directory, *, config_path: calls.append((path, directory, config_path)),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "docling_pipeline.py",
            str(source),
            "--output-dir",
            str(output),
            "--config",
            str(config),
        ],
    )

    shim.main()

    assert calls == [(source, output, config)]


def test_missing_configuration_has_one_actionable_migration_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    shim = _reload_shim()
    source = tmp_path / "questionnaire.pdf"
    source.write_bytes(b"%PDF-synthetic")
    monkeypatch.chdir(tmp_path)
    for name in tuple(key for key in os.environ if key.startswith("SURVEY_SCRIBE_")):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(sys, "argv", ["docling_pipeline.py", str(source)])

    with pytest.raises(SystemExit, match="1"):
        shim.main()

    error = capsys.readouterr().err
    assert error.count("Error:") == 1
    assert "model" in error
    assert "SURVEY_SCRIBE_MODEL" in error


@pytest.mark.parametrize("suffix", [".txt", ".docx"])
def test_cli_rejects_missing_or_non_pdf_input(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    suffix: str,
) -> None:
    shim = _reload_shim()
    source = tmp_path / f"questionnaire{suffix}"
    if suffix == ".txt":
        source.write_text("content", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["docling_pipeline.py", str(source)])
    with pytest.raises(SystemExit, match="1"):
        shim.main()
