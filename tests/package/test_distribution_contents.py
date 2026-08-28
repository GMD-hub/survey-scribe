"""Verify built distributions contain only the approved package surface."""

from __future__ import annotations

import tarfile
import zipfile
from email.parser import BytesParser
from importlib.metadata import version
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
    assert "survey_scribe/py.typed" in members


def test_wheel_metadata_is_publishable(repository_root: Path) -> None:
    wheel = _artifact(repository_root, "survey_scribe-*.whl")
    with zipfile.ZipFile(wheel) as archive:
        metadata_name = next(
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        )
        metadata = BytesParser().parsebytes(archive.read(metadata_name))

    assert metadata["Name"] == "survey-scribe"
    assert metadata["Version"] == version("survey-scribe")
    assert metadata["License-Expression"] == "MIT"
    assert metadata["Requires-Python"] == "<3.14,>=3.11"
    assert "pydantic<3,>=2.11.7" in metadata.get_all("Requires-Dist", [])
    assert "Typing :: Typed" in metadata.get_all("Classifier", [])
    assert any(
        value.startswith("Documentation, https://gmd-hub.github.io/survey-scribe/")
        for value in metadata.get_all("Project-URL", [])
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
        "CHANGELOG.md",
        "LICENSE",
        "README.md",
        "PKG-INFO",
        "pyproject.toml",
        "schemas",
        "src",
        "uv.lock",
    }
    assert relative_members
    assert all(member.parts[0] in allowed_roots for member in relative_members)
    assert PurePosixPath("LICENSE") in relative_members
