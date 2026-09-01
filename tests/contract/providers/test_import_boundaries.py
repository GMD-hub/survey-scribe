"""Provider SDKs remain behind the optional adapter boundary."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "relative_path",
    (
        "src/survey_scribe/providers/base.py",
        "src/survey_scribe/providers/capabilities.py",
        "src/survey_scribe/routing/extraction.py",
        "src/survey_scribe/routing/review.py",
    ),
)
def test_core_modules_do_not_import_optional_provider_sdks(
    repository_root: Path,
    relative_path: str,
) -> None:
    source = (repository_root / relative_path).read_text(encoding="utf-8")
    imported = {
        alias.name.split(".", maxsplit=1)[0]
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported.update(
        node.module.split(".", maxsplit=1)[0]
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom) and node.module is not None
    )
    assert imported.isdisjoint({"openai", "instructor", "tenacity", "tiktoken", "itsai"})


def test_routing_uses_provider_port_without_defining_a_duplicate_protocol(
    repository_root: Path,
) -> None:
    extraction = (repository_root / "src/survey_scribe/routing/extraction.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(extraction)
    class_names = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}

    assert "StructuredProvider" not in class_names
    assert "GeneratorProtocol" not in class_names
    assert "from survey_scribe.providers.base import" in extraction


def test_optional_live_schema_smoke_is_absent_without_explicit_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SURVEY_SCRIBE_LIVE_PROVIDER", raising=False)
    pytest.skip("protected live provider schema smoke requires explicit authorization")
