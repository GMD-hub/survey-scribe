"""Keep automation inside the approved Pages-only publication boundary."""

from __future__ import annotations

from pathlib import Path


def test_workflows_enforce_publication_boundary(repository_root: Path) -> None:
    workflows = sorted((repository_root / ".github/workflows").glob("*.yml"))
    assert {workflow.name for workflow in workflows} == {
        "ci.yml",
        "deploy-docs.yml",
        "docs.yml",
    }

    combined = "\n".join(workflow.read_text(encoding="utf-8") for workflow in workflows)
    prohibited = [
        "tags:",
        "gh-action-pypi-publish",
    ]

    assert all(value not in combined for value in prohibited)
    assert "uv run --no-sync twine check --strict dist/*.whl dist/*.tar.gz" in combined
    assert "uv run mkdocs build --strict" in combined

    deployment = (repository_root / ".github/workflows/deploy-docs.yml").read_text(encoding="utf-8")
    assert "pages: write" in deployment
    assert "id-token: write" in deployment
    assert "uv sync --locked --python 3.11" in deployment
    assert "actions/upload-artifact@bbbca2ddaa5d8feaa63e36b76fdaad77386f024f" in deployment
    assert "actions/deploy-pages@cd2ce8fcbc39b97be8ca5fce6e763baed58fa128" in deployment

    action_lines = [line.strip() for line in deployment.splitlines() if "uses:" in line]
    for line in action_lines:
        revision = line.split("@", maxsplit=1)[1].split(maxsplit=1)[0]
        assert len(revision) == 40
        assert set(revision) <= set("0123456789abcdef")
