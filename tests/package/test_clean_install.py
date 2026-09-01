"""Install the built wheel offline and verify import plus CLI help."""

from __future__ import annotations

import os
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path


def _run(command: list[str], *, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def test_clean_wheel_install_offline(repository_root: Path, tmp_path: Path) -> None:
    environment = os.environ.copy()
    environment.pop("UV_INDEX", None)
    environment.pop("UV_INDEX_URL", None)
    environment.pop("UV_EXTRA_INDEX_URL", None)
    for name in tuple(environment):
        if name.startswith(("OPENAI_", "ANTHROPIC_", "AZURE_OPENAI_", "SURVEY_SCRIBE_")):
            environment.pop(name)
    environment["UV_NO_CONFIG"] = "1"
    environment["UV_OFFLINE"] = "1"
    environment["UV_CACHE_DIR"] = str(tmp_path / "empty-uv-cache")
    build_directory = tmp_path / "current-tree-dist"
    _run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--no-isolation",
            "--outdir",
            str(build_directory),
            str(repository_root),
        ],
        env=environment,
    )
    wheels = sorted(build_directory.glob(f"survey_scribe-{version('survey-scribe')}-*.whl"))
    assert len(wheels) == 1, "Build exactly one wheel from the current checkout."
    wheel = wheels[0]
    virtual_environment = tmp_path / "venv"
    wheelhouse = repository_root / ".cache/wheelhouse"
    assert wheelhouse.is_dir(), "Prepare the locked test wheelhouse before package tests."

    _run(
        ["uv", "venv", "--python", sys.executable, str(virtual_environment)],
        env=environment,
    )
    python = virtual_environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    _run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            "--no-index",
            "--find-links",
            str(wheelhouse),
            "--constraint",
            str(repository_root / "tests/fixtures/package/constraints.txt"),
            f"{wheel}[tabular]",
        ],
        env=environment,
    )
    guarded_import = """
import socket

def deny_network(*args, **kwargs):
    raise RuntimeError("network access denied during package smoke test")

socket.create_connection = deny_network
socket.socket.connect = deny_network
import survey_scribe
import schemas.svis
import tempfile
from datetime import date
from pathlib import Path
from importlib.metadata import version
from openpyxl import Workbook
from survey_scribe import QuestionnaireRouter, RoutedSurveySVIS
from survey_scribe.cli import main
from survey_scribe.config import SurveyScribeConfig
from survey_scribe.models import DataType, SurveySVIS, SurveyVariable
from survey_scribe.results import ExtractionResult, ResultStatus
from survey_scribe.serialization.artifacts import write_result
from survey_scribe.serialization import legacy_payload
from survey_scribe.serialization.routing import ArtifactManifestV2, parse_artifact_manifest
from survey_scribe.sources import SourceLimits
from survey_scribe.sources.chunking import ConservativeTokenEstimator
from survey_scribe.sources.ocr import APPROVED_OCR_ARTIFACTS
from survey_scribe.sources.registry import SourceRegistry
assert survey_scribe.__version__ == version("survey-scribe")
assert schemas.svis.SurveySVIS is survey_scribe.SurveySVIS
assert SurveyScribeConfig().provider == "openai"
assert ExtractionResult is not None
assert write_result is not None
assert legacy_payload({"safe": True}) == {"safe": True}
assert SourceLimits().max_pages == 2000
assert ConservativeTokenEstimator().estimate("abc") == 3
assert len(APPROVED_OCR_ARTIFACTS) == 2
with tempfile.TemporaryDirectory() as temporary_directory:
    output_directory = Path(temporary_directory)
    source = output_directory / "questionnaire.xlsx"
    workbook = Workbook()
    survey = workbook.active
    survey.title = "survey"
    survey.append(["type", "name", "label", "relevant"])
    survey.append(["select_one yes_no", "consent", "Consent?", ""])
    survey.append(["integer", "age", "Age", "${consent} = 'yes'"])
    choices = workbook.create_sheet("choices")
    choices.append(["list_name", "name", "label"])
    choices.append(["yes_no", "yes", "Yes"])
    choices.append(["yes_no", "no", "No"])
    settings = workbook.create_sheet("settings")
    settings.append(["form_title", "form_id"])
    settings.append(["Package Smoke", "package_smoke"])
    workbook.save(source)
    svis = SurveySVIS(
        survey_id="TST_2026_WHEEL",
        country_code="TST",
        year=2026,
        survey_name="Wheel smoke",
        variables=[
            SurveyVariable(raw_name="consent", data_type=DataType.categorical_single, extraction_confidence=1.0),
            SurveyVariable(raw_name="age", data_type=DataType.numeric, extraction_confidence=1.0),
        ],
        source_file=source.name,
        source_format="xlsx",
        extraction_date=date(2026, 9, 1),
    )
    registry = SourceRegistry.default()
    binding = registry.convert_with_native(source, svis).source_binding
    routed = QuestionnaireRouter(None, sources=registry).route(
        source,
        svis,
        source_binding=binding,
    )
    assert routed.status is ResultStatus.success
    assert isinstance(routed.output, RoutedSurveySVIS)
    assert all(variable.routing_node_id is not None for variable in routed.output.variables)
    written = routed.write(output_directory)
    manifest_path = next(item.path for item in written.artifacts if item.kind == "manifest")
    assert isinstance(parse_artifact_manifest(manifest_path.read_bytes()), ArtifactManifestV2)
    legacy_path = output_directory / "TST_2026_WHEEL_svis.json"
    SurveySVIS.model_validate_json(legacy_path.read_text(encoding="utf-8"))
try:
    main(["--help"])
except SystemExit as exc:
    assert exc.code == 0
"""
    imported = _run(
        [str(python), "-I", "-c", guarded_import],
        env=environment,
    )
    executable = virtual_environment / (
        "Scripts/survey-scribe.exe" if os.name == "nt" else "bin/survey-scribe"
    )
    help_result = _run(
        [str(executable), "--help"],
        env=environment,
    )
    assert imported.returncode == 0
    assert "survey-scribe" in help_result.stdout
