"""Enforce immutable actions and the approved Pages-only deployment boundary."""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import yaml
from loguru import logger

SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
NODE20_PATTERN = re.compile(r"node\s*20|node20", re.IGNORECASE)
NODE20_ACTION_PATTERN = re.compile(
    r"(?:actions/checkout|actions/upload-artifact)@[^\s]+\s+#\s*v4(?:\s|$)"
    r"|astral-sh/setup-uv@[^\s]+\s+#\s*v6(?:\s|$)",
    re.IGNORECASE,
)
SECRET_CONTEXT_PATTERN = re.compile(r"\$\{\{\s*secrets\s*(?:\.|\[)", re.IGNORECASE)
APPROVED_ACTIONS = {
    "actions/checkout": "3d3c42e5aac5ba805825da76410c181273ba90b1",  # v7.0.1
    "astral-sh/setup-uv": "20cfd1bf945f4377ade1205e4dbc17946fc9a30d",  # v10.0.1
    "actions/configure-pages": "45bfe0192ca1faeb007ade9deae92b16b8254a0d",  # v6.0.0
    "actions/upload-artifact": "bbbca2ddaa5d8feaa63e36b76fdaad77386f024f",  # v7.0.0
    "actions/deploy-pages": "cd2ce8fcbc39b97be8ca5fce6e763baed58fa128",  # v5.0.0
}
PAGES_WORKFLOW = "deploy-docs.yml"
PUBLICATION_PATTERNS = (
    "gh-action-pypi-publish",
    "pypa/gh-action-pypi-publish",
    "twine upload",
    "uv publish",
    "hatch publish",
    "poetry publish",
    "npm publish",
    "testpypi",
)


def _mapping(value: object) -> Mapping[object, object]:
    return value if isinstance(value, Mapping) else {}


def _walk(value: object):
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield str(key), child
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _check_action(path: Path, value: object, errors: list[str]) -> None:
    if not isinstance(value, str):
        return
    if value.strip().startswith(("./", "../")):
        errors.append(f"{path.name}: local action is not reviewed: {value}")
        return
    if "@" not in value:
        errors.append(f"{path.name}: action reference lacks an immutable revision: {value}")
        return
    action, revision = value.rsplit("@", maxsplit=1)
    if not SHA_PATTERN.fullmatch(revision):
        errors.append(f"{path.name}: mutable action revision is prohibited: {value}")
    elif APPROVED_ACTIONS.get(action) != revision:
        errors.append(f"{path.name}: action revision is not reviewed: {value}")
    if "deploy" in action.casefold() and not (
        path.name == PAGES_WORKFLOW and action == "actions/deploy-pages"
    ):
        errors.append(f"{path.name}: deployment action is not authorized: {action}")


def _check_permissions(
    path: Path,
    workflow: Mapping[str, object],
    errors: list[str],
) -> None:
    top_permissions = workflow.get("permissions")
    if top_permissions != {"contents": "read"}:
        errors.append(f"{path.name}: top-level permissions must equal contents: read")
    for job_name, job_value in _mapping(workflow.get("jobs")).items():
        job = _mapping(job_value)
        if "permissions" in job and not isinstance(job["permissions"], Mapping):
            errors.append(f"{path.name}:{job_name}: job permissions must be a mapping")
        permissions = _mapping(job.get("permissions"))
        for permission, access in permissions.items():
            if access != "write":
                if access != "read":
                    errors.append(
                        f"{path.name}:{job_name}: permission {permission} has invalid access"
                    )
                continue
            allowed_pages = (
                path.name == PAGES_WORKFLOW
                and permission == "pages"
                and job_name in {"build", "deploy"}
            )
            allowed_oidc = (
                path.name == PAGES_WORKFLOW
                and permission == "id-token"
                and job_name == "deploy"
                and _mapping(job.get("environment")).get("name") == "github-pages"
            )
            if not (allowed_pages or allowed_oidc):
                errors.append(f"{path.name}:{job_name}: unauthorized write permission {permission}")


def check_workflow(path: Path) -> list[str]:
    """Return all policy errors for one workflow file."""
    errors: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
        workflow = yaml.safe_load(text)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        return [f"{path.name}: workflow cannot be parsed: {type(exc).__name__}"]
    if not isinstance(workflow, Mapping):
        return [f"{path.name}: workflow root must be a mapping"]
    if NODE20_PATTERN.search(text) or NODE20_ACTION_PATTERN.search(text):
        errors.append(f"{path.name}: Node 20-era action pin or annotation is prohibited")
    if SECRET_CONTEXT_PATTERN.search(text):
        errors.append(f"{path.name}: secret contexts are prohibited")
    triggers = _mapping(workflow.get("on", workflow.get(True)))
    if any(key in {"tags", "tags-ignore"} for key, _value in _walk(triggers)):
        errors.append(f"{path.name}: tag triggers are prohibited")
    _check_permissions(path, workflow, errors)
    lowered = text.casefold()
    for pattern in PUBLICATION_PATTERNS:
        if pattern in lowered:
            errors.append(f"{path.name}: package publication is prohibited: {pattern}")
    for key, value in _walk(workflow):
        if key == "uses":
            _check_action(path, value, errors)
        if key == "environment" and path.name != PAGES_WORKFLOW:
            errors.append(f"{path.name}: deployment environments are not authorized")
    if path.name == PAGES_WORKFLOW:
        actions = {
            value.rsplit("@", maxsplit=1)[0]
            for key, value in _walk(workflow)
            if key == "uses" and isinstance(value, str) and "@" in value
        }
        if "actions/deploy-pages" not in actions:
            errors.append(f"{path.name}: approved Pages workflow must deploy with deploy-pages")
    return errors


def check_workflows(directory: Path) -> list[str]:
    """Return all policy errors for YAML workflows in a directory."""
    paths = sorted((*directory.glob("*.yml"), *directory.glob("*.yaml")))
    if not paths:
        return [f"{directory}: no workflows found"]
    errors: list[str] = []
    for path in paths:
        errors.extend(check_workflow(path))
    return errors


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args(argv)
    logger.remove()
    logger.add(sys.stderr, format="{message}")
    errors = check_workflows(args.directory)
    if errors:
        for error in errors:
            logger.error(error)
        return 1
    logger.info("Workflow policy passed with the approved Pages-only exception")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
