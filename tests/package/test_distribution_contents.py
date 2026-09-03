"""Verify built distributions contain only the approved package surface."""

from __future__ import annotations

import tarfile
import zipfile
from email.parser import BytesParser
from importlib.metadata import version
from pathlib import Path, PurePosixPath

PACKAGE_FILES = frozenset(
    {
        "schemas/__init__.py",
        "schemas/svis.py",
        "survey_scribe/__init__.py",
        "survey_scribe/cli.py",
        "survey_scribe/config.py",
        "survey_scribe/errors.py",
        "survey_scribe/models/__init__.py",
        "survey_scribe/models/routing.py",
        "survey_scribe/models/svis.py",
        "survey_scribe/providers/__init__.py",
        "survey_scribe/providers/anthropic.py",
        "survey_scribe/providers/azure.py",
        "survey_scribe/providers/base.py",
        "survey_scribe/providers/capabilities.py",
        "survey_scribe/providers/openai_compatible.py",
        "survey_scribe/providers/testing.py",
        "survey_scribe/pipeline.py",
        "survey_scribe/py.typed",
        "survey_scribe/results.py",
        "survey_scribe/routing/__init__.py",
        "survey_scribe/routing/algorithms.py",
        "survey_scribe/routing/config.py",
        "survey_scribe/routing/contracts.py",
        "survey_scribe/routing/diagnostics.py",
        "survey_scribe/routing/extraction.py",
        "survey_scribe/routing/identity.py",
        "survey_scribe/routing/inventory.py",
        "survey_scribe/routing/native.py",
        "survey_scribe/routing/normalization.py",
        "survey_scribe/routing/pipeline.py",
        "survey_scribe/routing/prompts.py",
        "survey_scribe/routing/reconcile.py",
        "survey_scribe/routing/review.py",
        "survey_scribe/routing/validate.py",
        "survey_scribe/serialization/__init__.py",
        "survey_scribe/serialization/artifacts.py",
        "survey_scribe/serialization/legacy.py",
        "survey_scribe/serialization/routing.py",
        "survey_scribe/sources/__init__.py",
        "survey_scribe/sources/base.py",
        "survey_scribe/sources/chunking.py",
        "survey_scribe/sources/docling.py",
        "survey_scribe/sources/ocr.py",
        "survey_scribe/sources/registry.py",
        "survey_scribe/sources/tabular.py",
        "survey_scribe/sources/xlsform.py",
    }
)
SDIST_ROOT_FILES = frozenset(
    {
        ".gitignore",
        "CHANGELOG.md",
        "LICENSE",
        "PKG-INFO",
        "README.md",
        "pyproject.toml",
        "uv.lock",
    }
)


def _artifact(repository_root: Path, pattern: str) -> Path:
    artifacts = sorted((repository_root / "dist").glob(pattern))
    assert len(artifacts) == 1, f"Expected one current build artifact matching {pattern}."
    return artifacts[0]


def test_wheel_contents_are_bounded(repository_root: Path) -> None:
    wheel = _artifact(repository_root, "survey_scribe-*.whl")
    with zipfile.ZipFile(wheel) as archive:
        infos = archive.infolist()
    members = [info.filename for info in infos]
    distribution = f"survey_scribe-{version('survey-scribe')}.dist-info"
    expected = PACKAGE_FILES | {
        f"{distribution}/METADATA",
        f"{distribution}/RECORD",
        f"{distribution}/WHEEL",
        f"{distribution}/entry_points.txt",
        f"{distribution}/licenses/LICENSE",
    }
    assert len(members) == len(set(members))
    assert all(not info.is_dir() for info in infos)
    assert all("." not in PurePosixPath(member).parts for member in members)
    assert set(members) == expected


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
        file_members = [member for member in archive.getmembers() if member.isfile()]
        assert all(not member.issym() and not member.islnk() for member in archive.getmembers())
        relative_members = [
            PurePosixPath(*PurePosixPath(member.name).parts[1:])
            for member in file_members
            if len(PurePosixPath(member.name).parts) > 1
        ]
    expected = {PurePosixPath(path) for path in SDIST_ROOT_FILES}
    expected.update(
        PurePosixPath("src") / path if path.startswith("survey_scribe/") else PurePosixPath(path)
        for path in PACKAGE_FILES
    )
    assert len(relative_members) == len(set(relative_members))
    assert all("." not in member.parts and ".." not in member.parts for member in relative_members)
    assert set(relative_members) == expected


def test_wheel_runtime_files_match_current_checkout(repository_root: Path) -> None:
    wheel = _artifact(repository_root, "survey_scribe-*.whl")
    with zipfile.ZipFile(wheel) as archive:
        for member in PACKAGE_FILES:
            source = (
                repository_root / "src" / member
                if member.startswith("survey_scribe/")
                else repository_root / member
            )
            assert archive.read(member) == source.read_bytes(), member


def test_sdist_contains_exact_current_runtime_files(repository_root: Path) -> None:
    source_distribution = _artifact(repository_root, "survey_scribe-*.tar.gz")
    prefix = f"survey_scribe-{version('survey-scribe')}"
    with tarfile.open(source_distribution, mode="r:gz") as archive:
        for member in PACKAGE_FILES:
            relative = f"src/{member}" if member.startswith("survey_scribe/") else member
            extracted = archive.extractfile(f"{prefix}/{relative}")
            assert extracted is not None
            source = (
                repository_root / "src" / member
                if member.startswith("survey_scribe/")
                else repository_root / member
            )
            assert extracted.read() == source.read_bytes(), member
