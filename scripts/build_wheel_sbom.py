"""Build and validate a CycloneDX SBOM from one isolated exact-wheel install."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from email.parser import BytesParser
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from cyclonedx.schema import SchemaVersion
from cyclonedx.validation.json import JsonStrictValidator
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT_NAME = "survey-scribe"
SPEC_VERSION = "1.6"


def _wheel_metadata(wheel: Path) -> tuple[str, str, set[str]]:
    with ZipFile(wheel) as archive:
        metadata_name = next(
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        )
        metadata = BytesParser().parsebytes(archive.read(metadata_name))
    name = str(canonicalize_name(str(metadata["Name"])))
    version = str(metadata["Version"])
    dependencies = {
        str(canonicalize_name(Requirement(value).name))
        for value in metadata.get_all("Requires-Dist", [])
        if Requirement(value).marker is None
    }
    return name, version, dependencies


def validate_sbom(sbom: dict[str, Any], wheel: Path) -> None:
    """Validate the schema, root component, dependencies, and wheel digest."""
    validation_error = JsonStrictValidator(SchemaVersion.V1_6).validate_str(json.dumps(sbom))
    if validation_error is not None:
        raise ValueError(f"CycloneDX schema validation failed: {validation_error}")
    name, version, expected_dependencies = _wheel_metadata(wheel)
    if name != ROOT_NAME:
        raise ValueError("SBOM wheel is not the survey-scribe distribution")
    if sbom.get("bomFormat") != "CycloneDX" or sbom.get("specVersion") != SPEC_VERSION:
        raise ValueError("SBOM format or specification version is invalid")
    metadata = sbom.get("metadata")
    root = metadata.get("component") if isinstance(metadata, dict) else None
    if not isinstance(root, dict):
        raise ValueError("SBOM root component is missing")
    if canonicalize_name(str(root.get("name"))) != name or root.get("version") != version:
        raise ValueError("SBOM root component does not match the wheel")
    hashes = root.get("hashes")
    expected_digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    if hashes != [{"alg": "SHA-256", "content": expected_digest}]:
        raise ValueError("SBOM root component is not bound to the exact wheel digest")
    root_ref = root.get("bom-ref")
    dependencies = sbom.get("dependencies")
    root_dependency = (
        next(
            (
                item
                for item in dependencies
                if isinstance(item, dict) and item.get("ref") == root_ref
            ),
            None,
        )
        if isinstance(dependencies, list)
        else None
    )
    if not isinstance(root_dependency, dict) or not isinstance(
        root_dependency.get("dependsOn"), list
    ):
        raise ValueError("SBOM root dependency graph is missing")
    direct_names = {
        canonicalize_name(reference.split("==", maxsplit=1)[0])
        for reference in root_dependency["dependsOn"]
        if isinstance(reference, str)
    }
    if direct_names != expected_dependencies:
        raise ValueError("SBOM root dependencies do not match wheel metadata")
    components = sbom.get("components")
    if not isinstance(components, list) or any(
        not isinstance(component, dict) or not isinstance(component.get("bom-ref"), str)
        for component in components
    ):
        raise ValueError("SBOM component inventory is invalid")
    assert isinstance(dependencies, list)
    component_refs = {component["bom-ref"] for component in components}
    dependency_graph = {
        item["ref"]: set(item.get("dependsOn", []))
        for item in dependencies
        if isinstance(item, dict)
        and isinstance(item.get("ref"), str)
        and isinstance(item.get("dependsOn", []), list)
    }
    reachable: set[str] = set()
    pending = list(root_dependency["dependsOn"])
    while pending:
        reference = pending.pop()
        if not isinstance(reference, str) or reference in reachable:
            continue
        reachable.add(reference)
        pending.extend(dependency_graph.get(reference, ()))
    if reachable != component_refs:
        raise ValueError("SBOM components do not match the installed dependency closure")


def build_sbom(wheel: Path, wheelhouse: Path, output: Path) -> dict[str, Any]:
    """Install one wheel offline, generate its SBOM, and validate the result."""
    wheel = wheel.resolve(strict=True)
    wheelhouse = wheelhouse.resolve(strict=True)
    output = output.resolve()
    if wheel.suffix != ".whl" or not wheel.is_file():
        raise ValueError("wheel must identify one regular .whl file")
    if not wheelhouse.is_dir() or output.suffix != ".json" or output.is_symlink():
        raise ValueError("wheelhouse and output paths are invalid")
    output.parent.mkdir(parents=True, exist_ok=True)
    environment = {
        name: os.environ[name]
        for name in (
            "COMSPEC",
            "HOME",
            "LANG",
            "PATH",
            "PATHEXT",
            "SYSTEMROOT",
            "TEMP",
            "TMP",
            "TMPDIR",
            "WINDIR",
        )
        if name in os.environ
    }
    environment.update({"UV_NO_CONFIG": "1", "UV_OFFLINE": "1"})
    with tempfile.TemporaryDirectory(prefix="survey-scribe-sbom-") as directory:
        temporary = Path(directory)
        environment["HOME"] = str(temporary / "home")
        environment["UV_CACHE_DIR"] = str(temporary / "uv-cache")
        virtual_environment = temporary / "venv"
        raw_sbom = temporary / "sbom.json"
        subprocess.run(
            ["uv", "venv", "--python", sys.executable, str(virtual_environment)],
            check=True,
            env=environment,
            timeout=60,
        )
        python = virtual_environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(python),
                "--no-index",
                "--find-links",
                str(wheelhouse),
                "--constraint",
                str(Path(__file__).resolve().parents[1] / "tests/fixtures/package/constraints.txt"),
                str(wheel),
            ],
            check=True,
            env=environment,
            timeout=120,
        )
        subprocess.run(
            [
                sys.executable,
                "-m",
                "cyclonedx_py",
                "environment",
                str(python),
                "--pyproject",
                str(Path(__file__).resolve().parents[1] / "pyproject.toml"),
                "--mc-type",
                "library",
                "--spec-version",
                SPEC_VERSION,
                "--output-reproducible",
                "--output-file",
                str(raw_sbom),
            ],
            check=True,
            env=environment,
            timeout=120,
        )
        sbom = json.loads(raw_sbom.read_text(encoding="utf-8"))
    root = sbom["metadata"]["component"]
    root["hashes"] = [{"alg": "SHA-256", "content": hashlib.sha256(wheel.read_bytes()).hexdigest()}]
    validate_sbom(sbom, wheel)
    output.write_text(json.dumps(sbom, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return sbom


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build_sbom(args.wheel, args.wheelhouse, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
