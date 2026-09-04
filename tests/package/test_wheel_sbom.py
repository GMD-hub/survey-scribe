"""Validate exact-wheel CycloneDX evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.build_wheel_sbom import validate_sbom


def _valid_sbom(wheel: Path) -> dict[str, object]:
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    return {
        "$schema": "http://cyclonedx.org/schema/bom-1.6.schema.json",
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": "urn:uuid:00000000-0000-4000-8000-000000000001",
        "version": 1,
        "metadata": {
            "timestamp": "2026-09-04T00:00:00Z",
            "component": {
                "type": "library",
                "bom-ref": "root-component",
                "name": "survey-scribe",
                "version": "0.1.0",
                "hashes": [{"alg": "SHA-256", "content": digest}],
            },
        },
        "components": [
            {
                "type": "library",
                "bom-ref": "defusedxml==0.7.1",
                "name": "defusedxml",
                "version": "0.7.1",
            },
            {
                "type": "library",
                "bom-ref": "pydantic==2.11.7",
                "name": "pydantic",
                "version": "2.11.7",
            },
        ],
        "dependencies": [
            {
                "ref": "root-component",
                "dependsOn": ["defusedxml==0.7.1", "pydantic==2.11.7"],
            },
            {"ref": "defusedxml==0.7.1"},
            {"ref": "pydantic==2.11.7"},
        ],
    }


def test_sbom_validation_binds_schema_root_dependencies_and_wheel_digest(
    repository_root: Path,
) -> None:
    wheels = sorted((repository_root / "dist").glob("survey_scribe-0.1.0-*.whl"))
    if len(wheels) != 1:
        pytest.skip("build exactly one current wheel before package tests")

    validate_sbom(_valid_sbom(wheels[0]), wheels[0])


def test_generated_sbom_is_bound_to_the_built_wheel(repository_root: Path) -> None:
    wheels = sorted((repository_root / "dist").glob("survey_scribe-0.1.0-*.whl"))
    sbom_path = repository_root / "dist/sbom.cdx.json"
    if len(wheels) != 1 or not sbom_path.is_file():
        pytest.skip("build the exact-wheel SBOM before package tests")

    validate_sbom(json.loads(sbom_path.read_text(encoding="utf-8")), wheels[0])


@pytest.mark.parametrize("mutation", ("version", "dependency", "digest"))
def test_sbom_validation_rejects_unbound_evidence(
    repository_root: Path,
    mutation: str,
) -> None:
    wheels = sorted((repository_root / "dist").glob("survey_scribe-0.1.0-*.whl"))
    if len(wheels) != 1:
        pytest.skip("build exactly one current wheel before package tests")
    sbom = _valid_sbom(wheels[0])
    if mutation == "version":
        sbom["metadata"]["component"]["version"] = "9.9.9"  # type: ignore[index]
    elif mutation == "dependency":
        sbom["dependencies"][0]["dependsOn"] = ["pydantic==2.11.7"]  # type: ignore[index]
    else:
        sbom["metadata"]["component"]["hashes"][0]["content"] = "0" * 64  # type: ignore[index]

    with pytest.raises(ValueError):
        validate_sbom(sbom, wheels[0])  # type: ignore[arg-type]


def test_sbom_validation_rejects_an_unreachable_component(repository_root: Path) -> None:
    wheels = sorted((repository_root / "dist").glob("survey_scribe-0.1.0-*.whl"))
    if len(wheels) != 1:
        pytest.skip("build exactly one current wheel before package tests")
    sbom = _valid_sbom(wheels[0])
    sbom["components"].append(  # type: ignore[union-attr]
        {"type": "library", "bom-ref": "unrelated==1", "name": "unrelated", "version": "1"}
    )

    with pytest.raises(ValueError, match="dependency closure"):
        validate_sbom(sbom, wheels[0])  # type: ignore[arg-type]
