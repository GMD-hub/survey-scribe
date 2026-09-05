"""Deterministic documentation, examples, links, and static-site policy tests."""

from __future__ import annotations

import re
import socket
from datetime import date
from pathlib import Path
from types import TracebackType
from typing import Self
from urllib.parse import unquote, urlsplit

import pytest
import yaml

from scripts.generate_docs_reference import generated_artifacts
from survey_scribe import ExtractionResult, SurveySVIS, cli

pytestmark = pytest.mark.allow_hosts(["127.0.0.1", "::1"])

_MARKDOWN_LINK = re.compile(r"!?\[[^]]*]\(([^)\s]+)(?:\s+['\"][^)]*['\"])?\)")
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_EXPLICIT_ANCHOR = re.compile(r"\{#([A-Za-z][\w:.-]*)\}")
_EXECUTABLE_BLOCK = re.compile(
    r"```python\n# docs-exec: (?P<name>[a-z0-9-]+)\n(?P<code>.*?)```",
    re.DOTALL,
)
_OBVIOUS_SECRET = re.compile(
    r"(?:-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|"
    r"AKIA[0-9A-Z]{16})"
)
_PRIVATE_GATEWAY_LABEL = re.compile(
    r"(?:worldbank(?:group)?|mAI Factory|DesktopToken|itsai|artifactory|service-now|"
    r"Ocp-Apim-Subscription-Key|\.default)",
    re.IGNORECASE,
)


def _configuration(repository_root: Path) -> dict[str, object]:
    value = yaml.safe_load((repository_root / "mkdocs.yml").read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _navigation_targets(repository_root: Path) -> tuple[str, ...]:
    targets: list[str] = []

    def collect(value: object) -> None:
        if isinstance(value, str):
            targets.append(value)
        elif isinstance(value, list):
            for item in value:
                collect(item)
        elif isinstance(value, dict):
            for item in value.values():
                collect(item)

    collect(_configuration(repository_root)["nav"])
    return tuple(targets)


def _slug(value: str) -> str:
    plain = re.sub(r"[`*_]", "", value)
    plain = re.sub(r"[^\w\s-]", "", plain, flags=re.UNICODE).strip().lower()
    return re.sub(r"[-\s]+", "-", plain)


def _anchors(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    anchors = {_slug(match.group(2)) for match in _HEADING.finditer(text)}
    anchors.update(_EXPLICIT_ANCHOR.findall(text))
    return anchors


def _deny_network(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("documentation example attempted network access")


def test_documentation_navigation_targets_exist(repository_root: Path) -> None:
    configuration = _configuration(repository_root)
    targets = _navigation_targets(repository_root)

    assert targets
    assert len(targets) == len(set(targets))
    assert all((repository_root / "docs" / target).is_file() for target in targets)
    assert configuration["theme"]["font"] is False  # type: ignore[index]
    assert configuration["extra"]["analytics"]["feedback"] is False  # type: ignore[index]


def test_generated_reference_artifacts_have_no_drift() -> None:
    artifacts = generated_artifacts()

    assert len(artifacts) == 3
    for path, expected in artifacts.items():
        assert path.read_text(encoding="utf-8") == expected, f"regenerate {path.name}"


def test_internal_document_links_and_anchors_resolve(repository_root: Path) -> None:
    docs = repository_root / "docs"
    errors: list[str] = []
    for relative in _navigation_targets(repository_root):
        source = docs / relative
        text = source.read_text(encoding="utf-8")
        for raw_target in _MARKDOWN_LINK.findall(text):
            target = unquote(raw_target.strip("<>"))
            split = urlsplit(target)
            if split.scheme or target.startswith(("mailto:", "#")):
                continue
            destination = (source.parent / split.path).resolve()
            try:
                destination.relative_to(docs.resolve())
            except ValueError:
                errors.append(f"{relative}: link escapes docs: {target}")
                continue
            if not destination.is_file():
                errors.append(f"{relative}: missing target: {target}")
                continue
            if (
                split.fragment
                and destination.suffix == ".md"
                and split.fragment not in _anchors(destination)
            ):
                errors.append(f"{relative}: missing anchor: {target}")
    assert errors == []


def test_published_docs_have_no_secrets_or_stale_claims(repository_root: Path) -> None:
    docs = repository_root / "docs"
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in docs.rglob("*")
        if path.suffix in {".css", ".js", ".json", ".md"}
    )

    assert _OBVIOUS_SECRET.search(text) is None
    assert "Survey Solutions" not in text
    for stale in (
        "No packaged function currently extracts",
        "Passing a questionnaire input file is not supported",
        "currently provides package help and version output only",
        "do not add a packaged extraction client",
        "from schemas.svis",
    ):
        assert stale not in text


def test_gateway_pages_use_only_generic_public_configuration(repository_root: Path) -> None:
    errors: list[str] = []
    pages = (
        repository_root / "docs/reference/providers.md",
        repository_root / "docs/guides/security.md",
    )
    for page in pages:
        for line_number, line in enumerate(page.read_text(encoding="utf-8").splitlines(), 1):
            if _PRIVATE_GATEWAY_LABEL.search(line):
                errors.append(f"{page.relative_to(repository_root)}:{line_number}")

    providers = pages[0].read_text(encoding="utf-8")
    security = pages[1].read_text(encoding="utf-8")
    assert errors == []
    assert "metadata_headers" in providers
    assert "sensitive_headers_callback" in providers
    assert "required_headers" in providers
    assert "X-Synthetic-" in providers
    assert "sensitive_headers_callback" in security


def test_required_user_journey_and_evidence_boundaries_are_published(
    repository_root: Path,
) -> None:
    docs = repository_root / "docs"
    corpus = "\n".join(
        (docs / relative).read_text(encoding="utf-8")
        for relative in _navigation_targets(repository_root)
    )

    for required in (
        "SurveyScribe",
        "survey-scribe convert",
        "docling_pipeline.py",
        "success",
        "partial",
        "failed",
        "--strict",
        "configuration-only",
        "verified",
        "StructuredPipeline",
        "ChunkedStructuredPipeline",
        "no telemetry",
        "quality",
    ):
        assert required in corpus


def test_tagged_python_examples_execute_with_fakes_and_no_network(
    repository_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket, "create_connection", _deny_network)
    monkeypatch.setattr(socket, "getaddrinfo", _deny_network)
    examples: list[tuple[str, str]] = []
    for relative in _navigation_targets(repository_root):
        text = (repository_root / "docs" / relative).read_text(encoding="utf-8")
        examples.extend(
            (match.group("name"), match.group("code")) for match in _EXECUTABLE_BLOCK.finditer(text)
        )

    assert {name for name, _code in examples} == {
        "structured-pipeline-fake",
        "survey-scribe-fake",
    }
    for name, code in examples:
        namespace = {"DOCS_TMP_PATH": tmp_path / name}
        namespace["DOCS_TMP_PATH"].mkdir()
        exec(compile(code, f"<docs:{name}>", "exec"), namespace)


def test_documented_safe_cli_examples_execute_without_network(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(socket, "create_connection", _deny_network)
    monkeypatch.setattr(socket, "getaddrinfo", _deny_network)

    assert cli.main(["providers"]) == 0
    providers = capsys.readouterr().out
    assert "configuration-only" in providers
    assert "verified model rows: none" in providers

    assert cli.main(["schema", "export", "routing"]) == 0
    schema = capsys.readouterr().out
    assert '"title": "QuestionnaireRoutingGraph"' in schema

    class FakeClient:
        def __enter__(self) -> Self:
            return self

        def __exit__(
            self,
            _error_type: type[BaseException] | None,
            _error: BaseException | None,
            _traceback: TracebackType | None,
        ) -> None:
            return None

        def convert(self, source: Path) -> ExtractionResult[SurveySVIS]:
            assert source == tmp_path / "questionnaire.txt"
            return ExtractionResult(
                output=SurveySVIS(
                    survey_id="SYN_2026_DOCS",
                    country_code="SYN",
                    year=2026,
                    survey_name="Synthetic documentation survey",
                    variables=[],
                    source_file=source.name,
                    source_format="txt",
                    extraction_date=date(2026, 9, 4),
                )
            )

    monkeypatch.setattr(cli, "_create_client", lambda _config: FakeClient())
    monkeypatch.setenv("SURVEY_SCRIBE_MODEL", "deterministic-fake")
    monkeypatch.setenv("SURVEY_SCRIBE_API_KEY", "synthetic-docs-credential")
    source = tmp_path / "questionnaire.txt"
    source.write_text("Synthetic questionnaire", encoding="utf-8")

    assert cli.main(["convert", str(source), "--output-dir", str(tmp_path / "output")]) == 0
    summary = capsys.readouterr().out
    assert "status=success" in summary
    assert "synthetic-docs-credential" not in summary


def test_static_playground_source_policy(repository_root: Path) -> None:
    page = (repository_root / "docs" / "playground.md").read_text(encoding="utf-8")
    script = (repository_root / "docs" / "assets" / "javascripts" / "playground.js").read_text(
        encoding="utf-8"
    )
    lowered_page = page.lower()
    lowered_script = script.lower()

    assert 'type="application/json"' in page
    assert "precomputed synthetic data" in lowered_page
    for forbidden_tag in ("<form", "<input", "<textarea", "<select"):
        assert forbidden_tag not in lowered_page
    for forbidden_source in (
        "localstorage",
        "sessionstorage",
        "document.cookie",
        "fetch(",
        "xmlhttprequest",
        "websocket",
        "eventsource",
        "serviceworker",
        "sendbeacon",
    ):
        assert forbidden_source not in lowered_script
    assert re.search(r"\b(?:src|href|action)=[\"']https?://", page, re.IGNORECASE) is None
    assert "api_key" not in lowered_page
    assert "credential entry" in lowered_page
