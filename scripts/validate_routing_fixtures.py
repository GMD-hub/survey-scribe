# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = [
#   "loguru==0.7.3",
# ]
# ///
"""Validate the source-only routing fixture corpus."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any

from loguru import logger

MANIFEST_RELATIVE = PurePosixPath("tests/fixtures/routing/manifest.toml")
DEFAULT_MANIFEST_PATH = Path(MANIFEST_RELATIVE.as_posix())
ROUTING_ROOT = PurePosixPath("tests/fixtures/routing")
SOURCE_ROOT = ROUTING_ROOT / "sources"
ROUTING_SCHEMA = ROUTING_ROOT / "schema/questionnaire-routing-graph-v1.0.json"
MINIMUM_FIXTURE_COUNT = 14
MINIMUM_SCALE_ITEM_COUNT = 1000

REQUIRED_CASES = frozenset(
    {
        "activation_without_transition",
        "answer_code_branches_default",
        "correction_return",
        "duplicate_source_ids_separate_sections",
        "garbled_target",
        "multiple_incoming_paths",
        "prompt_injection_text",
        "repeated_consumption_template",
        "roster_loop_with_exit",
        "scale_1000_items",
        "screen_out_terminal",
        "section_target",
        "skip_implicit_fallthrough",
        "unsupported_inferred_cycle",
    }
)

MANIFEST_FIELDS = {
    "benchmark_eligible",
    "corpus_status",
    "fixtures",
    "newline_policy",
    "schema_version",
    "source_only",
}
FIXTURE_FIELDS = {
    "artifact_kind",
    "benchmark_eligible",
    "creator",
    "declared_item_count",
    "expected_logical_cases",
    "id",
    "path",
    "provenance",
    "purpose",
    "restrictions",
    "rights_basis",
    "sensitivity",
    "sha256",
    "source_only",
}
TEXT_FIELDS = {
    "creator",
    "id",
    "path",
    "provenance",
    "purpose",
    "restrictions",
    "rights_basis",
    "sensitivity",
    "sha256",
}

ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ITEM_RE = re.compile(r"^ITEM[ \t]+\S+", re.MULTILINE)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(
        r"\b(?:api[_ -]?key|client[_ -]?secret|password|access[_ -]?token)"
        r"\s*[:=]\s*[\"']?(?:sk-[A-Za-z0-9_-]{16,}|[A-Za-z0-9_./+=-]{20,})",
        re.IGNORECASE,
    ),
)
RESTRICTED_PATH_PARTS = {
    ".env",
    ".git",
    ".ssh",
    "credential",
    "credentials",
    "key",
    "keys",
    "private",
    "secret",
    "secrets",
}


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _has_symlink_component(path: Path, root: Path) -> bool:
    try:
        relative = path.absolute().relative_to(root)
    except ValueError:
        return False
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            return True
    return False


def _manifest_path(path: Path, root: Path) -> tuple[Path | None, list[str]]:
    errors: list[str] = []
    candidate = path if path.is_absolute() else root / path
    candidate = candidate.absolute()
    expected = root.joinpath(*MANIFEST_RELATIVE.parts)
    if candidate != expected:
        errors.append("manifest path must be tests/fixtures/routing/manifest.toml")
        return None, errors
    if _has_symlink_component(candidate, root):
        errors.append("manifest path must not use symlinks")
        return None, errors
    return candidate, errors


def _fixture_path(value: str, root: Path, prefix: str) -> tuple[Path | None, list[str]]:
    errors: list[str] = []
    if "\\" in value:
        return None, [f"{prefix} path must use canonical forward slashes"]
    relative = PurePosixPath(value)
    if relative.is_absolute() or "." in relative.parts or ".." in relative.parts:
        return None, [f"{prefix} path must be confined to {SOURCE_ROOT.as_posix()}"]
    if not relative.is_relative_to(SOURCE_ROOT):
        return None, [f"{prefix} path must be confined to {SOURCE_ROOT.as_posix()}"]
    if relative.suffix != ".txt":
        return None, [f"{prefix} path must identify a .txt source file"]
    lowered_parts = {part.lower() for part in relative.parts}
    if lowered_parts & RESTRICTED_PATH_PARTS:
        return None, [f"{prefix} path contains a restricted component"]

    candidate = root.joinpath(*relative.parts)
    if _has_symlink_component(candidate, root):
        return None, [f"{prefix} path must not use symlinks"]
    try:
        resolved = candidate.resolve(strict=False)
    except OSError:
        return None, [f"{prefix} path cannot be resolved safely"]
    if not resolved.is_relative_to(root.joinpath(*SOURCE_ROOT.parts)):
        errors.append(f"{prefix} path must be confined to {SOURCE_ROOT.as_posix()}")
        return None, errors
    return candidate, errors


def _load_manifest(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        content = path.read_bytes()
    except OSError:
        return None, ["manifest cannot be read"]
    if b"\r" in content:
        return None, ["manifest must use LF line endings"]
    if not content.endswith(b"\n"):
        return None, ["manifest must end with LF"]
    try:
        manifest = tomllib.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None, ["manifest is not valid TOML"]
    return manifest, []


def _validate_source(
    path: Path,
    fixture: dict[str, Any],
    prefix: str,
) -> tuple[list[str], int | None]:
    errors: list[str] = []
    try:
        content = path.read_bytes()
    except OSError:
        return [f"{prefix} source file cannot be read"], None

    digest = hashlib.sha256(content).hexdigest()
    if digest != fixture.get("sha256"):
        errors.append(f"{prefix} checksum mismatch")
    if b"\r" in content:
        errors.append(f"{prefix} must use LF line endings")
    if not content.endswith(b"\n"):
        errors.append(f"{prefix} must end with LF")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        errors.append(f"{prefix} must be valid UTF-8")
        return errors, None
    if any(pattern.search(text) for pattern in SECRET_PATTERNS):
        errors.append(f"{prefix} contains a prohibited secret pattern")

    item_count = len(ITEM_RE.findall(text))
    declared_count = fixture.get("declared_item_count")
    if (
        isinstance(declared_count, int)
        and not isinstance(declared_count, bool)
        and item_count != declared_count
    ):
        errors.append(f"{prefix} declared_item_count does not match source items")
    return errors, item_count


def _validate_corpus_inventory(root: Path, declared_paths: set[str]) -> list[str]:
    routing_root = root.joinpath(*ROUTING_ROOT.parts)
    if _has_symlink_component(routing_root, root):
        return ["routing fixture corpus must not use symlinks"]
    try:
        entries = tuple(routing_root.rglob("*"))
    except OSError:
        return ["routing fixture corpus cannot be inventoried"]
    if any(entry.is_symlink() for entry in entries):
        return ["routing fixture corpus must not contain symlinks"]

    actual_files = {entry.relative_to(root).as_posix() for entry in entries if entry.is_file()}
    allowed_files = {
        MANIFEST_RELATIVE.as_posix(),
        ROUTING_SCHEMA.as_posix(),
        *declared_paths,
    }
    if actual_files != allowed_files:
        return ["routing fixture corpus contains unlisted or non-source files"]
    return []


def validate(
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    *,
    repository_root: Path | None = None,
) -> list[str]:
    """Return all source fixture policy errors without trusting manifest values."""
    root = (repository_root or Path(__file__).resolve().parents[1]).resolve()
    resolved_manifest, errors = _manifest_path(manifest_path, root)
    if resolved_manifest is None:
        return errors
    manifest, load_errors = _load_manifest(resolved_manifest)
    if manifest is None:
        return load_errors

    errors = []
    unsupported_manifest_fields = sorted(set(manifest) - MANIFEST_FIELDS)
    if unsupported_manifest_fields:
        errors.append("manifest has unsupported fields: " + ", ".join(unsupported_manifest_fields))
    if manifest.get("schema_version") != 1 or isinstance(manifest.get("schema_version"), bool):
        errors.append("manifest schema_version must equal 1")
    if manifest.get("corpus_status") != "synthetic-source-only":
        errors.append("manifest corpus_status must be synthetic-source-only")
    if manifest.get("source_only") is not True:
        errors.append("manifest must be source-only")
    if manifest.get("benchmark_eligible") is not False:
        errors.append("manifest must be ineligible for model-quality benchmarks")
    if manifest.get("newline_policy") != "lf":
        errors.append("manifest newline_policy must be lf")

    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list):
        errors.append("manifest fixtures must be a list")
        fixtures = []
    elif len(fixtures) < MINIMUM_FIXTURE_COUNT:
        errors.append(f"manifest must define at least {MINIMUM_FIXTURE_COUNT} fixtures")

    fixture_ids: set[str] = set()
    fixture_paths: set[str] = set()
    covered_cases: set[str] = set()
    case_counts: dict[str, int] = {}
    declared_paths: set[str] = set()
    scale_present = False

    for index, raw_fixture in enumerate(fixtures, start=1):
        prefix = f"fixture {index}"
        if not isinstance(raw_fixture, dict):
            errors.append(f"{prefix} must be a TOML table")
            continue
        fixture = raw_fixture
        missing = sorted(FIXTURE_FIELDS - fixture.keys())
        if missing:
            errors.append(f"{prefix} missing fields: {', '.join(missing)}")
        unsupported = sorted(fixture.keys() - FIXTURE_FIELDS)
        if unsupported:
            errors.append(f"{prefix} has unsupported fields: {', '.join(unsupported)}")

        for field in sorted(TEXT_FIELDS):
            if not _is_nonempty_string(fixture.get(field)):
                errors.append(f"{prefix} field {field} must be a nonempty string")

        fixture_id = fixture.get("id")
        if isinstance(fixture_id, str):
            if not ID_RE.fullmatch(fixture_id):
                errors.append(f"{prefix} id must use lowercase kebab-case")
            if fixture_id in fixture_ids:
                errors.append(f"{prefix} duplicates fixture id {fixture_id}")
            fixture_ids.add(fixture_id)

        path_value = fixture.get("path")
        if isinstance(path_value, str):
            if path_value in fixture_paths:
                errors.append(f"{prefix} duplicates fixture path {path_value}")
            fixture_paths.add(path_value)

        if fixture.get("artifact_kind") != "synthetic-questionnaire-source":
            errors.append(f"{prefix} must be a synthetic questionnaire source")
        if fixture.get("source_only") is not True:
            errors.append(f"{prefix} must be source-only")
        if fixture.get("benchmark_eligible") is not False:
            errors.append(f"{prefix} must be ineligible for model-quality benchmarks")
        if fixture.get("sensitivity") != "non-sensitive":
            errors.append(f"{prefix} sensitivity must be non-sensitive")
        if fixture.get("rights_basis") != "repository-synthetic":
            errors.append(f"{prefix} rights_basis must be repository-synthetic")
        checksum = fixture.get("sha256")
        if not isinstance(checksum, str) or not SHA256_RE.fullmatch(checksum):
            errors.append(f"{prefix} sha256 must be 64 lowercase hexadecimal characters")
        declared_count = fixture.get("declared_item_count")
        if (
            not isinstance(declared_count, int)
            or isinstance(declared_count, bool)
            or declared_count < 1
        ):
            errors.append(f"{prefix} declared_item_count must be a positive integer")

        expected_cases = fixture.get("expected_logical_cases")
        valid_cases: list[str] = []
        if not isinstance(expected_cases, list) or not all(
            _is_nonempty_string(case) for case in expected_cases
        ):
            errors.append(f"{prefix} expected_logical_cases must contain exactly one case")
        else:
            valid_cases = expected_cases
            if len(expected_cases) != 1:
                errors.append(f"{prefix} expected_logical_cases must contain exactly one case")
            unsupported_cases = sorted(set(valid_cases) - REQUIRED_CASES)
            if unsupported_cases:
                errors.append(
                    f"{prefix} has unsupported expected logical cases: "
                    + ", ".join(unsupported_cases)
                )
            for case in set(valid_cases) & REQUIRED_CASES:
                covered_cases.add(case)
                case_counts[case] = case_counts.get(case, 0) + 1
                if case == "scale_1000_items":
                    scale_present = True
                    if (
                        not isinstance(declared_count, int)
                        or declared_count < MINIMUM_SCALE_ITEM_COUNT
                    ):
                        errors.append(
                            f"scale fixture must declare at least {MINIMUM_SCALE_ITEM_COUNT} items"
                        )

        if not isinstance(path_value, str):
            continue
        fixture_path, path_errors = _fixture_path(path_value, root, prefix)
        errors.extend(path_errors)
        if fixture_path is None:
            continue
        declared_paths.add(PurePosixPath(path_value).as_posix())
        if not fixture_path.is_file():
            errors.append(f"{prefix} source file does not exist")
            continue
        source_errors, item_count = _validate_source(fixture_path, fixture, prefix)
        errors.extend(source_errors)
        if "scale_1000_items" in valid_cases and (
            item_count is None or item_count < MINIMUM_SCALE_ITEM_COUNT
        ):
            errors.append(f"scale fixture must contain at least {MINIMUM_SCALE_ITEM_COUNT} items")

    missing_cases = sorted(REQUIRED_CASES - covered_cases)
    if missing_cases:
        errors.append("manifest is missing required cases: " + ", ".join(missing_cases))
    duplicate_cases = sorted(case for case, count in case_counts.items() if count > 1)
    if duplicate_cases:
        errors.append("manifest duplicates required cases: " + ", ".join(duplicate_cases))
    if not scale_present:
        errors.append("manifest must define the scale_1000_items fixture")

    errors.extend(_validate_corpus_inventory(root, declared_paths))
    return errors


def main() -> int:
    """Validate the repository routing source fixture corpus."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(MANIFEST_RELATIVE.as_posix()),
    )
    args = parser.parse_args()
    logger.remove()
    logger.add(sys.stderr, format="{message}")

    try:
        errors = validate(args.manifest)
    except Exception:
        logger.exception("Routing fixture validation failed safely")
        return 1
    if errors:
        for error in errors:
            logger.error(error)
        return 1
    logger.info("Routing source fixture manifest is valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
