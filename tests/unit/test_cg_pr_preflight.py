"""Deterministic PR preflight selection and native-runner tests."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import cg_pr_preflight


def test_selection_payload_is_deterministic_and_complete() -> None:
    changed = (
        "src/survey_scribe/routing/pipeline.py",
        "docs/guides/sources.md",
        "pyproject.toml",
        "src/survey_scribe/routing/pipeline.py",
    )

    payload = cg_pr_preflight.selection_payload("main", changed)

    assert payload["changed_files"] == changed[:3]
    assert [item["id"] for item in payload["selected_commands"]] == [  # type: ignore[index]
        "ruff-check",
        "ruff-format",
        "pyright",
        "pytest-non-package",
        "mkdocs-strict",
        "build",
        "package-tests",
    ]
    assert payload["pester_files"] == ()
    assert payload["selection_error"] is None
    assert payload["kilo_capability"]["status"] == "generic-not-applicable"  # type: ignore[index]


@pytest.mark.parametrize("path", ("../escape.py", "/absolute.py", r"src\wrong.py", ""))
def test_changed_files_must_be_confined(path: str) -> None:
    with pytest.raises(ValueError, match="changed files"):
        cg_pr_preflight.normalize_changed_files((path,))


def test_selection_only_cli_emits_json_without_running_commands(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cg_pr_preflight,
        "run_selected_commands",
        lambda *_args, **_kwargs: pytest.fail("selection-only mode ran commands"),
    )

    exit_code = cg_pr_preflight.main(
        (
            "--phase",
            "prepare",
            "--base",
            "main",
            "--changed-file",
            "src/survey_scribe/results.py",
            "--selection-only",
            "--format",
            "json",
        )
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["selection_error"] is None
    assert payload["changed_files"] == ["src/survey_scribe/results.py"]


def test_native_runner_stops_after_first_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload: dict[str, object] = {
        "selected_commands": (
            {"id": "pass", "argv": ("pass",)},
            {"id": "fail", "argv": ("fail",)},
            {"id": "not-run", "argv": ("not-run",)},
        )
    }
    calls: list[tuple[str, ...]] = []

    def run(argv: tuple[str, ...], **_kwargs: object) -> object:
        calls.append(argv)
        return SimpleNamespace(
            returncode=1 if argv == ("fail",) else 0,
            stdout="stdout",
            stderr="stderr",
        )

    monkeypatch.setattr(cg_pr_preflight.subprocess, "run", run)

    result, exit_code = cg_pr_preflight.run_selected_commands(
        payload,
        repository_root=tmp_path,
    )

    assert exit_code == 1
    assert calls == [("pass",), ("fail",)]
    assert [item["id"] for item in result["native_results"]] == ["pass", "fail"]  # type: ignore[index]
