"""Legacy root command compatibility beside the installed CLI."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from shutil import which


def test_installed_invocation_exposes_complete_command_surface(repository_root: Path) -> None:
    executable = which("survey-scribe")
    assert executable is not None
    completed = subprocess.run(
        [executable, "--help"],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    for command in ("convert", "batch", "providers", "config", "schema"):
        assert command in completed.stdout


def test_legacy_invocation_keeps_missing_input_exit_contract(repository_root: Path) -> None:
    completed = subprocess.run(
        [sys.executable, "docling_pipeline.py", "missing.pdf"],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    assert completed.stderr == "Error: file not found: missing.pdf\n"
