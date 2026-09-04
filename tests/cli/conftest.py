"""Fixtures for installed CLI behavior."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from survey_scribe import ExtractionResult, SurveySVIS


def make_svis(survey_id: str = "TST_2026_CLI") -> SurveySVIS:
    return SurveySVIS(
        survey_id=survey_id,
        country_code="TST",
        year=2026,
        survey_name="Synthetic CLI survey",
        variables=[],
        source_file="questionnaire.txt",
        source_format="txt",
        extraction_date=date(2026, 9, 3),
        extraction_notes="PRIVATE QUESTIONNAIRE TEXT MUST NOT ENTER THE BATCH MANIFEST",
    )


class FakeClient:
    def __init__(self, results: Iterable[ExtractionResult[SurveySVIS]]) -> None:
        self._results = list(results)
        self.converted: list[Path] = []

    def __enter__(self) -> FakeClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def convert(self, source: Path) -> ExtractionResult[SurveySVIS]:
        self.converted.append(source)
        return self._results[0]

    def convert_many(self, sources: Iterable[Path]) -> list[ExtractionResult[SurveySVIS]]:
        self.converted.extend(sources)
        return self._results


@pytest.fixture
def cli_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in tuple(
        key
        for key in __import__("os").environ
        if key.startswith("SURVEY_SCRIBE_")
        or key
        in {
            "AI_GATEWAY_API_KEY",
            "ANTHROPIC_API_KEY",
            "AZURE_OPENAI_API_KEY",
            "AZURE_OPENAI_API_VERSION",
            "AZURE_OPENAI_DEPLOYMENT",
            "AZURE_OPENAI_ENDPOINT",
            "OPENAI_API_KEY",
            "OPENAI_BASE_URL",
            "OPENROUTER_API_KEY",
        }
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SURVEY_SCRIBE_MODEL", "cli-model")
    monkeypatch.setenv("SURVEY_SCRIBE_API_KEY", "cli-secret")


@pytest.fixture
def fake_client_factory(monkeypatch: pytest.MonkeyPatch) -> Any:
    from survey_scribe import cli

    clients: list[FakeClient] = []

    def install(*results: ExtractionResult[SurveySVIS]) -> FakeClient:
        client = FakeClient(results)
        clients.append(client)
        monkeypatch.setattr(cli, "_create_client", lambda _config: client)
        return client

    return install
