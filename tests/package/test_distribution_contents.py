"""Verify built distributions contain only the approved package surface."""

from __future__ import annotations

import tarfile
import zipfile
from pathlib import Path, PurePosixPath


def _artifact(repository_root: Path, pattern: str) -> Path:
    artifacts = sorted((repository_root / "dist").glob(pattern))
    assert len(artifacts) == 1, f"Expected one current build artifact matching {pattern}."
    return artifacts[0]


def test_wheel_contents_are_bounded(repository_root: Path) -> None:
    wheel = _artifact(repository_root, "survey_scribe-*.whl")
    with zipfile.ZipFile(wheel) as archive:
        members = archive.namelist()
    assert members
    assert all(
        member.startswith(("survey_scribe/", "schemas/", "survey_scribe-")) for member in members
    )


def test_sdist_contents_are_bounded(repository_root: Path) -> None:
    source_distribution = _artifact(repository_root, "survey_scribe-*.tar.gz")
    with tarfile.open(source_distribution, mode="r:gz") as archive:
        relative_members = [
            PurePosixPath(*PurePosixPath(member.name).parts[1:])
            for member in archive.getmembers()
            if len(PurePosixPath(member.name).parts) > 1
        ]
    allowed_roots = {
        ".gitignore",
        "README.md",
        "PKG-INFO",
        "pyproject.toml",
        "schemas",
        "src",
        "uv.lock",
    }
    assert relative_members
    assert all(member.parts[0] in allowed_roots for member in relative_members)
