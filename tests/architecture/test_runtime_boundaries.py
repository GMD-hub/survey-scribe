"""Static and import-time boundaries for the Phase 4 public runtime."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path


def _runtime_files(repository_root: Path) -> tuple[Path, ...]:
    return tuple((repository_root / "src/survey_scribe").rglob("*.py")) + (
        repository_root / "docling_pipeline.py",
    )


def test_unsafe_legacy_runtime_is_removed(repository_root: Path) -> None:
    assert not tuple((repository_root / "agents").glob("*.py"))
    assert not tuple((repository_root / "extractors").glob("*.py"))
    assert not tuple((repository_root / "schemas").glob("*.py"))

    contents = "\n".join(
        path.read_text(encoding="utf-8") for path in _runtime_files(repository_root)
    )
    assert "itsai" not in contents
    assert "azapimdev.worldbank.org" not in contents


def test_runtime_does_not_print_or_directly_import_optional_sdks(repository_root: Path) -> None:
    prohibited = {"openai", "instructor", "anthropic", "docling", "itsai"}
    for path in _runtime_files(repository_root):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id != "print", path
            if isinstance(node, ast.Import):
                assert prohibited.isdisjoint(alias.name.split(".", 1)[0] for alias in node.names), (
                    path
                )
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".", 1)[0] not in prohibited, path


def test_top_level_and_shim_import_without_clients_or_credentials(repository_root: Path) -> None:
    script = """
import os
import sys
for key in tuple(os.environ):
    if key.startswith(('OPENAI_', 'ANTHROPIC_', 'AZURE_', 'SURVEY_SCRIBE_')):
        os.environ.pop(key)
import survey_scribe
import docling_pipeline
blocked = {'openai', 'instructor', 'anthropic', 'docling', 'itsai'}
assert blocked.isdisjoint(sys.modules)
assert survey_scribe.SurveyScribe.__name__ == 'SurveyScribe'
assert callable(docling_pipeline.run)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
