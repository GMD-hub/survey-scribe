"""Characterize legacy metadata reconciliation without loading private clients."""

from __future__ import annotations

import importlib
import sys
from types import ModuleType
from typing import Any

import pytest


def _module(name: str, **attributes: Any) -> ModuleType:
    module = ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    return module


def _load_agent(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    class DesktopToken:
        def get_token(self, **_kwargs: Any) -> str:
            return "unused-test-token"

    class Client:
        def __init__(self, **_kwargs: Any) -> None:
            self.chat = _module(
                "chat", completions=_module("completions", create=lambda **_k: None)
            )

    class RateLimitError(Exception):
        pass

    class LanguageDetectorBuilder:
        @classmethod
        def from_all_languages(cls) -> Any:
            return _module("builder", build=lambda: None)

    def retry(**_kwargs: Any) -> Any:
        return lambda function: function

    stubs = {
        "instructor": _module("instructor", from_openai=lambda client: client),
        "itsai": _module("itsai"),
        "itsai.platform": _module("itsai.platform"),
        "itsai.platform.authentication": _module(
            "itsai.platform.authentication", DesktopToken=DesktopToken
        ),
        "lingua": _module("lingua", LanguageDetectorBuilder=LanguageDetectorBuilder),
        "openai": _module("openai", AzureOpenAI=Client, RateLimitError=RateLimitError),
        "tenacity": _module(
            "tenacity",
            retry=retry,
            retry_if_exception_type=lambda _error: None,
            stop_after_attempt=lambda _attempts: None,
            wait_random_exponential=lambda **_kwargs: None,
        ),
        "extractors.docling_pdf": _module("extractors.docling_pdf", DocumentChunk=object),
    }
    for name, module in stubs.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.delitem(sys.modules, "agents.svis_agent", raising=False)
    return importlib.import_module("agents.svis_agent")


@pytest.mark.parametrize(
    "meta_year,survey_name,source_file,expected",
    [
        (0, "Household Survey 2014", "survey_2020.pdf", 2014),
        (0, "Household Survey", "survey_2020.pdf", 2020),
        (2022, "Household Survey", "survey.pdf", 2022),
    ],
)
def test_year_precedence(
    monkeypatch: pytest.MonkeyPatch,
    meta_year: int,
    survey_name: str,
    source_file: str,
    expected: int,
) -> None:
    agent = _load_agent(monkeypatch)
    assert agent._resolve_year(meta_year, survey_name, source_file) == expected


def test_survey_id_reconciliation(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = _load_agent(monkeypatch)
    assert agent._resolve_survey_id("ALB_0000_HBSA", "ALB", 2014) == "ALB_2014_HBSA"
    assert agent._resolve_survey_id("OTHER_2020_NAME", "ALB", 2014) == "OTHER_2014_NAME"
    assert agent._resolve_survey_id("NO_YEAR", "ALB", 2014) == "NO_YEAR"
