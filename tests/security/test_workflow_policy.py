"""Workflow policy tests for actions, permissions, triggers, and publication."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_workflow_policy import APPROVED_ACTIONS, check_workflow, check_workflows

HEADER = """name: Test
on:
  pull_request:
permissions:
  contents: read
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
"""


def _workflow(tmp_path: Path, content: str, *, name: str = "ci.yml") -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_repository_workflows_pass_and_use_reviewed_action_pins(repository_root: Path) -> None:
    workflows = repository_root / ".github/workflows"

    assert check_workflows(workflows) == []
    combined = "\n".join(path.read_text(encoding="utf-8") for path in workflows.glob("*.yml"))
    for action, revision in APPROVED_ACTIONS.items():
        assert f"{action}@{revision}" in combined


def test_ci_network_guard_allows_only_cross_platform_event_loop_transports(
    repository_root: Path,
) -> None:
    workflow = (repository_root / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "pytest --allow-hosts=127.0.0.1,::1 --allow-unix-socket tests" in workflow
    assert "pytest --disable-socket" not in workflow


def test_mutable_action_tag_is_rejected(tmp_path: Path) -> None:
    path = _workflow(tmp_path, HEADER + "      - uses: actions/checkout@v7\n")

    assert any("mutable action revision" in error for error in check_workflow(path))


@pytest.mark.parametrize(
    ("fragment", "message"),
    [
        ("on:\n  push:\n    tags: ['v*']\n", "tag triggers"),
        ("permissions: write-all\n", "top-level permissions"),
        ("      id-token: write\n", "unauthorized write permission"),
        ("      pages: write\n", "unauthorized write permission"),
        ("      - run: uv publish\n", "package publication"),
    ],
)
def test_prohibited_triggers_permissions_and_publication(
    tmp_path: Path, fragment: str, message: str
) -> None:
    if fragment.startswith("on:"):
        content = HEADER.replace("on:\n  pull_request:\n", fragment)
    elif fragment.startswith("permissions:"):
        content = HEADER.replace("permissions:\n  contents: read\n", fragment)
    elif fragment.lstrip().startswith(("id-token", "pages")):
        content = HEADER.replace(
            "    runs-on: ubuntu-latest\n",
            "    runs-on: ubuntu-latest\n    permissions:\n" + fragment,
        )
    else:
        content = HEADER + fragment
    path = _workflow(tmp_path, content)

    assert any(message in error for error in check_workflow(path))


def test_approved_pages_exception_is_narrowly_accepted(repository_root: Path) -> None:
    path = repository_root / ".github/workflows/deploy-docs.yml"

    assert check_workflow(path) == []

    content = path.read_text(encoding="utf-8").replace("name: github-pages", "name: unprotected")
    changed = _workflow(repository_root / ".cache", content, name="deploy-docs.yml")
    assert any(
        "unauthorized write permission id-token" in error for error in check_workflow(changed)
    )


@pytest.mark.parametrize(
    "expression",
    ("${{ secrets.PYPI_TOKEN }}", "${{ secrets ['PYPI_TOKEN'] }}"),
)
def test_secret_contexts_are_rejected_fail_closed(tmp_path: Path, expression: str) -> None:
    path = _workflow(
        tmp_path,
        HEADER + f"      - run: command\n        env:\n          TOKEN: {expression}\n",
    )

    assert any("secret contexts are prohibited" in error for error in check_workflow(path))


@pytest.mark.parametrize("action", ("./.github/actions/publish", "../shared/action"))
def test_unreviewed_local_actions_are_rejected_fail_closed(tmp_path: Path, action: str) -> None:
    path = _workflow(tmp_path, HEADER + f"      - uses: {action}\n")

    assert any("local action is not reviewed" in error for error in check_workflow(path))
