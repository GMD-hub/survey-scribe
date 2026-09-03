# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = []
# ///
"""Select and optionally run deterministic local PR preflight commands."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import cast


@dataclass(frozen=True, slots=True)
class SelectedCommand:
    """One stable native command selected from repository-relative changes."""

    command_id: str
    argv: tuple[str, ...]

    def to_json(self) -> dict[str, object]:
        return {"id": self.command_id, "argv": self.argv}


def normalize_changed_files(values: Sequence[str]) -> tuple[str, ...]:
    """Validate, normalize, and de-duplicate repository-relative paths."""
    normalized: list[str] = []
    for value in values:
        if "\\" in value:
            raise ValueError("changed files must use repository-relative forward slashes")
        path = PurePosixPath(value)
        if not value or path.is_absolute() or "." in path.parts or ".." in path.parts:
            raise ValueError("changed files must be confined repository-relative paths")
        normalized.append(path.as_posix())
    return tuple(dict.fromkeys(normalized))


def select_commands(changed_files: Sequence[str]) -> tuple[SelectedCommand, ...]:
    """Select bounded project gates from the exact changed-file set."""
    changed = normalize_changed_files(changed_files)
    selected = [
        SelectedCommand("ruff-check", ("uv", "run", "ruff", "check", ".")),
        SelectedCommand("ruff-format", ("uv", "run", "ruff", "format", "--check", ".")),
        SelectedCommand("pyright", ("uv", "run", "pyright")),
    ]
    has_python_scope = any(
        path.endswith((".py", ".toml", ".yml", ".yaml"))
        or path.startswith(("src/", "tests/", "scripts/", ".github/"))
        for path in changed
    )
    if has_python_scope:
        selected.append(
            SelectedCommand(
                "pytest-non-package",
                ("uv", "run", "pytest", "tests", "--ignore=tests/package"),
            )
        )
    if any(path.startswith("docs/") or path == "mkdocs.yml" for path in changed):
        selected.append(
            SelectedCommand("mkdocs-strict", ("uv", "run", "mkdocs", "build", "--strict"))
        )
    if any(
        path == "pyproject.toml"
        or path.startswith("tests/package/")
        or path.startswith("tests/fixtures/package/")
        for path in changed
    ):
        selected.extend(
            (
                SelectedCommand("build", ("uv", "build")),
                SelectedCommand("package-tests", ("uv", "run", "pytest", "tests/package")),
            )
        )
    return tuple(selected)


def selection_payload(base: str, changed_files: Sequence[str]) -> dict[str, object]:
    """Build the complete selection response consumed by `/cg-verify-pr`."""
    if not base.strip():
        raise ValueError("base branch must be nonempty")
    changed = normalize_changed_files(changed_files)
    if not changed:
        raise ValueError("at least one exact changed file is required")
    return {
        "phase": "prepare",
        "base": base,
        "changed_files": changed,
        "selected_commands": tuple(command.to_json() for command in select_commands(changed)),
        "pester_files": (),
        "selection_error": None,
        "kilo_capability": {
            "status": "generic-not-applicable",
            "certified_ready": False,
            "reason": "No certified Kilo host adapter is required for this Python project preflight.",
        },
    }


def run_selected_commands(
    payload: dict[str, object],
    *,
    repository_root: Path,
) -> tuple[dict[str, object], int]:
    """Run selected commands in order and stop at the first failure."""
    results: list[dict[str, object]] = []
    exit_code = 0
    commands = cast(tuple[dict[str, object], ...], payload["selected_commands"])
    for command_data in commands:
        argv = tuple(cast(Sequence[str], command_data["argv"]))
        completed = subprocess.run(
            argv,
            cwd=repository_root,
            check=False,
            capture_output=True,
            text=True,
        )
        results.append(
            {
                "id": command_data["id"],
                "argv": argv,
                "exit_code": completed.returncode,
                "stdout": completed.stdout[-4000:],
                "stderr": completed.stderr[-4000:],
            }
        )
        if completed.returncode != 0:
            exit_code = completed.returncode
            break
    output = dict(payload)
    output["native_results"] = tuple(results)
    output["native_exit_code"] = exit_code
    return output, exit_code


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("prepare",), required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--changed-file", action="append", default=[])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--selection-only", action="store_true")
    mode.add_argument("--run-native-target", action="store_true")
    parser.add_argument("--format", choices=("json",), required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the preflight selector CLI with stable JSON output."""
    arguments = _parser().parse_args(argv)
    try:
        payload = selection_payload(arguments.base, arguments.changed_file)
        exit_code = 0
        if arguments.run_native_target:
            payload, exit_code = run_selected_commands(
                payload,
                repository_root=Path(__file__).resolve().parents[1],
            )
    except ValueError as error:
        payload = {
            "phase": "prepare",
            "base": arguments.base,
            "changed_files": (),
            "selected_commands": (),
            "pester_files": (),
            "selection_error": str(error),
            "kilo_capability": {"status": "generic-not-applicable", "certified_ready": False},
        }
        exit_code = 2
    sys.stdout.write(json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
