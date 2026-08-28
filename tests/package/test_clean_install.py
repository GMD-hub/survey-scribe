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
    wheels = sorted(
        (repository_root / "dist").glob(f"survey_scribe-{version('survey-scribe')}-*.whl")
    )
    assert len(wheels) == 1, "Build exactly one wheel for the current package version."
    wheel = wheels[0]
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
            str(wheel),
        ],
        env=environment,
    )
    guarded_import = """
import socket

def deny_network(*args, **kwargs):
    raise RuntimeError("network access denied during package smoke test")

socket.socket = deny_network
socket.create_connection = deny_network
import survey_scribe
import schemas.svis
from importlib.metadata import version
from survey_scribe.cli import main
assert survey_scribe.__version__ == version("survey-scribe")
assert schemas.svis.SurveySVIS is survey_scribe.SurveySVIS
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
