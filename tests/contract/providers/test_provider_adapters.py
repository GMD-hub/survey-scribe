"""Azure, Anthropic, and named OpenAI-compatible adapter contracts."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ConfigDict

from survey_scribe.config import GenerationConfig, RetryConfig
from survey_scribe.providers import anthropic as anthropic_module
from survey_scribe.providers import azure as azure_module
from survey_scribe.providers.anthropic import InstructorAnthropicProvider
from survey_scribe.providers.azure import AzureOpenAIProvider
from survey_scribe.providers.base import ConcurrencyLimiter, ProviderMessage
from survey_scribe.providers.capabilities import CapabilityEvidence, ModelCapabilities
from survey_scribe.providers.openai_compatible import (
    InstructorOpenAIProvider,
    OpenAICompatiblePreset,
)


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: int


def _capabilities(
    provider: str,
    model: str,
    *,
    settings: frozenset[str] | None = None,
) -> ModelCapabilities:
    return ModelCapabilities(
        provider=provider,
        model=model,
        structured_output=True,
        strict_schema=True,
        max_input_tokens=32_768,
        max_output_tokens=4_096,
        supported_generation_settings=(
            settings
            if settings is not None
            else frozenset({"temperature", "max_output_tokens", "seed"})
        ),
        evidence=CapabilityEvidence.configuration_only,
        tested_sdk_version="contract-fixture",
    )


async def _generate(provider: object) -> Answer:
    response = await provider.generate(  # type: ignore[attr-defined]
        messages=(ProviderMessage(role="user", content="questionnaire"),),
        response_model=Answer,
        generation=GenerationConfig(),
        retry=RetryConfig(max_attempts=1),
        limiter=ConcurrencyLimiter(1),
    )
    return response.output


def test_openai_compatible_presets_set_only_reviewed_endpoints_and_headers() -> None:
    openai = InstructorOpenAIProvider.from_preset(
        OpenAICompatiblePreset.openai,
        model="configured-model",
        api_key="not-a-real-key",
        capabilities=_capabilities("openai", "configured-model"),
    )
    assert openai.base_url == "https://api.openai.com/v1"

    openrouter = InstructorOpenAIProvider.from_preset(
        OpenAICompatiblePreset.openrouter,
        model="configured-model",
        api_key="not-a-real-key",
        capabilities=_capabilities("openrouter", "configured-model"),
        default_headers={"HTTP-Referer": "https://example.test", "X-Title": "Survey Scribe"},
    )
    assert openrouter.base_url == "https://openrouter.ai/api/v1"

    vercel = InstructorOpenAIProvider.from_preset(
        OpenAICompatiblePreset.vercel,
        model="configured-model",
        api_key="not-a-real-key",
        capabilities=_capabilities("vercel", "configured-model"),
    )
    assert vercel.base_url == "https://ai-gateway.vercel.sh/v1"

    custom = InstructorOpenAIProvider.from_preset(
        OpenAICompatiblePreset.custom,
        model="configured-model",
        api_key="not-a-real-key",
        base_url="https://gateway.example/v1",
        capabilities=_capabilities("custom", "configured-model"),
    )
    assert custom.base_url == "https://gateway.example/v1"

    with pytest.raises(ValueError, match="header"):
        InstructorOpenAIProvider.from_preset(
            OpenAICompatiblePreset.openrouter,
            model="configured-model",
            capabilities=_capabilities("openrouter", "configured-model"),
            default_headers={"Authorization": "private"},
        )
    with pytest.raises(ValueError, match="base_url"):
        InstructorOpenAIProvider.from_preset(
            OpenAICompatiblePreset.custom,
            model="configured-model",
            capabilities=_capabilities("custom", "configured-model"),
        )
    with pytest.raises(ValueError, match="HTTPS"):
        InstructorOpenAIProvider.from_preset(
            OpenAICompatiblePreset.custom,
            model="configured-model",
            base_url="http://gateway.example/v1",
            capabilities=_capabilities("custom", "configured-model"),
        )


@pytest.mark.asyncio
async def test_azure_adapter_passes_refreshable_token_callback_lazily(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_kwargs: dict[str, object] = {}

    class FakeAsyncAzureOpenAI:
        def __init__(self, **kwargs: object) -> None:
            client_kwargs.update(kwargs)

    class FakeCompletions:
        async def create_with_completion(self, **_kwargs: object) -> tuple[Answer, object]:
            return Answer(value=3), SimpleNamespace(choices=[], usage=None, id="azure-response")

    patched = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    modules = {
        "openai": SimpleNamespace(AsyncAzureOpenAI=FakeAsyncAzureOpenAI),
        "instructor": SimpleNamespace(
            Mode=SimpleNamespace(TOOLS_STRICT=object()),
            from_openai=lambda _client, *, mode: patched,
        ),
    }
    monkeypatch.setattr(azure_module, "import_module", modules.__getitem__)
    issued = iter(("token-one", "token-two"))

    def callback() -> str:
        return next(issued)

    provider = AzureOpenAIProvider(
        deployment="deployment-a",
        azure_endpoint="https://example.openai.azure.com",
        api_version="2025-01-01-preview",
        token_callback=callback,
        capabilities=_capabilities("azure_openai", "deployment-a"),
    )

    assert await _generate(provider) == Answer(value=3)
    installed_callback = client_kwargs["azure_ad_token_provider"]
    assert callable(installed_callback)
    assert installed_callback() == "token-one"
    assert installed_callback() == "token-two"
    assert "api_key" not in client_kwargs
    assert client_kwargs["max_retries"] == 0

    key_provider = AzureOpenAIProvider(
        deployment="deployment-a",
        azure_endpoint="https://example.openai.azure.com",
        api_version="2025-01-01-preview",
        api_key="not-a-real-key",
        capabilities=_capabilities("azure_openai", "deployment-a"),
        completion=lambda **_kwargs: Answer(value=4),
    )
    assert await _generate(key_provider) == Answer(value=4)

    with pytest.raises(ValueError, match="credential"):
        AzureOpenAIProvider(
            deployment="deployment-a",
            azure_endpoint="https://example.openai.azure.com",
            api_version="2025-01-01-preview",
            api_key="key",
            token_callback=lambda: "token",
            capabilities=_capabilities("azure_openai", "deployment-a"),
        )
    for changes, message in (
        ({"azure_endpoint": "http://invalid"}, "HTTPS"),
        ({"api_version": " "}, "must not be empty"),
        ({"capabilities": _capabilities("openai", "deployment-a")}, "identify Azure"),
    ):
        values: dict[str, object] = {
            "deployment": "deployment-a",
            "azure_endpoint": "https://example.openai.azure.com",
            "api_version": "2025-01-01-preview",
            "api_key": "key",
            "capabilities": _capabilities("azure_openai", "deployment-a"),
        }
        values.update(changes)
        with pytest.raises(ValueError, match=message):
            AzureOpenAIProvider(**values)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_anthropic_adapter_is_lazy_and_normalizes_completion_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_kwargs: dict[str, object] = {}
    request_kwargs: dict[str, object] = {}

    class FakeAsyncAnthropic:
        def __init__(self, **kwargs: object) -> None:
            client_kwargs.update(kwargs)

    class FakeMessages:
        async def create_with_completion(self, **kwargs: object) -> tuple[Answer, object]:
            request_kwargs.update(kwargs)
            return Answer(value=5), SimpleNamespace(
                stop_reason="end_turn",
                id="anthropic-response",
                usage=SimpleNamespace(input_tokens=9, output_tokens=2),
            )

    patched = SimpleNamespace(messages=FakeMessages())
    modules = {
        "anthropic": SimpleNamespace(AsyncAnthropic=FakeAsyncAnthropic),
        "instructor": SimpleNamespace(
            Mode=SimpleNamespace(ANTHROPIC_TOOLS=object()),
            from_anthropic=lambda _client, *, mode: patched,
        ),
    }
    monkeypatch.setattr(anthropic_module, "import_module", modules.__getitem__)
    provider = InstructorAnthropicProvider(
        model="claude-configured",
        api_key="not-a-real-key",
        capabilities=_capabilities(
            "anthropic",
            "claude-configured",
            settings=frozenset({"temperature", "max_output_tokens"}),
        ),
    )

    assert await _generate(provider) == Answer(value=5)
    assert client_kwargs == {"api_key": "not-a-real-key", "max_retries": 0}
    assert request_kwargs["max_retries"] == 0
    assert request_kwargs["max_tokens"] == 4096

    with pytest.raises(ValueError, match="must not advertise seed"):
        InstructorAnthropicProvider(
            model="claude-configured",
            capabilities=_capabilities("anthropic", "claude-configured"),
        )
    with pytest.raises(ValueError, match="identify Anthropic"):
        InstructorAnthropicProvider(
            model="claude-configured",
            capabilities=_capabilities(
                "openai",
                "claude-configured",
                settings=frozenset({"temperature", "max_output_tokens"}),
            ),
        )
