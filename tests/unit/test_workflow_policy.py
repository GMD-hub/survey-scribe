"""Keep build automation inside the currently approved publication boundary."""

from __future__ import annotations

from pathlib import Path


def test_workflows_build_without_publication_permissions(repository_root: Path) -> None:
    workflows = sorted((repository_root / ".github/workflows").glob("*.yml"))
    assert {workflow.name for workflow in workflows} == {"ci.yml", "docs.yml"}

    combined = "\n".join(workflow.read_text(encoding="utf-8") for workflow in workflows)
    prohibited = [
        "tags:",
        "id-token: write",
        "pages: write",
        "gh-action-pypi-publish",
        "actions/deploy-pages",
    ]

    assert all(value not in combined for value in prohibited)
    assert "uv run twine check --strict dist/*" in combined
    assert "uv run mkdocs build --strict" in combined
