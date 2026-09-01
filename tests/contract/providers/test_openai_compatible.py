"""Instructor-backed OpenAI-compatible adapter contracts."""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ConfigDict

from survey_scribe.config import GenerationConfig, RetryConfig
from survey_scribe.providers import openai_compatible as adapter_module
from survey_scribe.providers.base import (
    ConcurrencyLimiter,
    ProviderAuthenticationError,
    ProviderDependencyError,
    ProviderMessage,
    ProviderRateLimitError,
    ProviderTransportError,
    ProviderTruncationError,
    ProviderValidationError,
)
from survey_scribe.providers.capabilities import CapabilityEvidence, ModelCapabilities
from survey_scribe.providers.openai_compatible import InstructorOpenAIProvider


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: int


def _capabilities() -> ModelCapabilities:
    return ModelCapabilities(
        provider="openai",
        model="gpt-test",
        structured_output=True,
        strict_schema=True,
        max_input_tokens=32_768,
        max_output_tokens=4_096,
        supported_generation_settings=frozenset({"temperature", "max_output_tokens", "seed"}),
        evidence=CapabilityEvidence.configuration_only,
        tested_sdk_version="1.99.9",
    )


def _generate(provider: InstructorOpenAIProvider):
    return provider.generate(
        messages=(ProviderMessage(role="user", content="private questionnaire"),),
        response_model=Answer,
        generation=GenerationConfig(),
        retry=RetryConfig(initial_delay_seconds=0.0, max_delay_seconds=0.0),
        limiter=ConcurrencyLimiter(1),
    )


def test_adapter_construction_and_schema_inspection_are_sdk_lazy() -> None:
    before = set(sys.modules)
    provider = InstructorOpenAIProvider(
        model="gpt-test",
        api_key="not-a-real-key",
        capabilities=_capabilities(),
    )

    descriptor = provider.inspect_schema(Answer)

    assert provider.model == "gpt-test"
    assert provider.adapter_identity.endswith("/v1")
    assert provider.provider_name == "openai"
    assert provider.max_input_tokens == 32_768
    assert provider.estimate_tokens((ProviderMessage(role="user", content="x"),)) > 0
    assert len(descriptor.request_schema_sha256) == 64
    assert set(sys.modules).difference(before).isdisjoint({"openai", "instructor"})


def test_adapter_rejects_empty_or_capability_mismatched_model() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        InstructorOpenAIProvider(
            model=" ",
            capabilities=_capabilities(),
        )
    with pytest.raises(ValueError, match="must match"):
        InstructorOpenAIProvider(
            model="other",
            capabilities=_capabilities(),
        )


@pytest.mark.asyncio
async def test_adapter_uses_injected_completion_without_importing_sdks() -> None:
    calls = 0

    async def completion(**_kwargs: object) -> tuple[object, object]:
        nonlocal calls
        calls += 1
        return Answer(value=4), {
            "finish_reason": "stop",
            "response_id": "response-1",
            "usage": {"input_tokens": 8, "output_tokens": 2, "total_tokens": 10},
        }

    provider = InstructorOpenAIProvider(
        model="gpt-test",
        api_key="not-a-real-key",
        capabilities=_capabilities(),
        completion=completion,
    )
    response = await _generate(provider)

    assert response.output.value == 4
    assert response.usage is not None and response.usage.total_tokens == 10
    assert response.response_id == "response-1"
    assert calls == 1


@pytest.mark.asyncio
async def test_adapter_classifies_retryable_rate_limit_and_safe_authentication() -> None:
    calls = 0

    async def retrying(**_kwargs: object) -> tuple[object, object]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ProviderRateLimitError()
        return Answer(value=2), {"finish_reason": "stop"}

    provider = InstructorOpenAIProvider(
        model="gpt-test",
        api_key="not-a-real-key",
        capabilities=_capabilities(),
        completion=retrying,
    )
    response = await _generate(provider)
    assert response.transport_attempts == 2

    async def denied(**_kwargs: object) -> tuple[object, object]:
        raise RuntimeError("401 private questionnaire bearer-secret")

    denied_provider = InstructorOpenAIProvider(
        model="gpt-test",
        api_key="not-a-real-key",
        capabilities=_capabilities(),
        completion=denied,
    )
    with pytest.raises(ProviderAuthenticationError, match="authentication failed") as error:
        await _generate(denied_provider)
    assert "private questionnaire" not in str(error.value)
    assert "bearer-secret" not in str(error.value)


@pytest.mark.asyncio
async def test_adapter_retries_generic_timeout_and_rejects_nonretryable_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    delays: list[float] = []

    async def no_wait(delay: float) -> None:
        delays.append(delay)

    async def timeout_once(**_kwargs: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("private timeout body")
        return Answer(value=6)

    monkeypatch.setattr(asyncio, "sleep", no_wait)
    provider = InstructorOpenAIProvider(
        model="gpt-test",
        capabilities=_capabilities(),
        completion=timeout_once,
    )
    response = await provider.generate(
        messages=(ProviderMessage(role="user", content="private questionnaire"),),
        response_model=Answer,
        generation=GenerationConfig(),
        retry=RetryConfig(initial_delay_seconds=0.1, max_delay_seconds=0.1),
        limiter=ConcurrencyLimiter(1),
    )
    assert response.output.value == 6
    assert response.usage is None
    assert response.finish_reason is None
    assert response.transport_attempts == 2
    assert delays == [0.1]

    async def nonretryable(**_kwargs: object) -> object:
        raise ProviderTransportError(retryable=False)

    denied = InstructorOpenAIProvider(
        model="gpt-test",
        capabilities=_capabilities(),
        completion=nonretryable,
    )
    with pytest.raises(ProviderTransportError):
        await _generate(denied)


@pytest.mark.asyncio
async def test_adapter_retries_validation_and_fails_closed_on_exhaustion_and_truncation() -> None:
    values: list[object] = [{"value": "bad"}, {"value": 8}]

    def validation_retry(**_kwargs: object) -> object:
        return values.pop(0)

    provider = InstructorOpenAIProvider(
        model="gpt-test",
        capabilities=_capabilities(),
        completion=validation_retry,
    )
    response = await _generate(provider)
    assert response.output.value == 8
    assert response.validation_attempts == 2

    invalid = InstructorOpenAIProvider(
        model="gpt-test",
        capabilities=_capabilities(),
        completion=lambda **_kwargs: {"value": "private source"},
    )
    with pytest.raises(ProviderValidationError, match="validation failed") as error:
        await invalid.generate(
            messages=(ProviderMessage(role="user", content="private source"),),
            response_model=Answer,
            generation=GenerationConfig(),
            retry=RetryConfig(max_attempts=1),
            limiter=ConcurrencyLimiter(1),
        )
    assert "private source" not in str(error.value)

    truncated = InstructorOpenAIProvider(
        model="gpt-test",
        capabilities=_capabilities(),
        completion=lambda **_kwargs: (Answer(value=1), {"finish_reason": "max_tokens"}),
    )
    with pytest.raises(ProviderTruncationError):
        await _generate(truncated)


@pytest.mark.asyncio
async def test_lazy_sdk_path_converts_messages_settings_and_normalizes_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_kwargs: dict[str, object] = {}
    request_kwargs: dict[str, object] = {}

    class FakeCompletions:
        async def create_with_completion(self, **kwargs: object) -> tuple[Answer, object]:
            request_kwargs.update(kwargs)
            return Answer(value=11), SimpleNamespace(
                choices=[SimpleNamespace(finish_reason="stop")],
                usage=SimpleNamespace(
                    prompt_tokens=12,
                    completion_tokens=3,
                    total_tokens=15,
                ),
                id="sdk-response",
            )

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs: object) -> None:
            client_kwargs.update(kwargs)

    patched = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    modules = {
        "openai": SimpleNamespace(AsyncOpenAI=FakeAsyncOpenAI),
        "instructor": SimpleNamespace(from_openai=lambda _client: patched),
    }
    monkeypatch.setattr(adapter_module, "import_module", modules.__getitem__)
    provider = InstructorOpenAIProvider(
        model="gpt-test",
        api_key="test-key",
        base_url="https://gateway.example/v1",
        capabilities=_capabilities(),
    )
    response = await provider.generate(
        messages=(
            ProviderMessage(role="system", content="fixed"),
            ProviderMessage(role="user", content="source"),
        ),
        response_model=Answer,
        generation=GenerationConfig(seed=4),
        retry=RetryConfig(),
        limiter=ConcurrencyLimiter(1),
    )

    assert client_kwargs == {
        "api_key": "test-key",
        "base_url": "https://gateway.example/v1",
    }
    assert request_kwargs["messages"] == [
        {"role": "system", "content": "fixed"},
        {"role": "user", "content": "source"},
    ]
    assert request_kwargs["max_retries"] == 0
    assert request_kwargs["seed"] == 4
    assert response.response_id == "sdk-response"
    assert response.usage is not None and response.usage.total_tokens == 15


@pytest.mark.asyncio
async def test_metadata_objects_and_invalid_usage_are_normalized_without_raw_data() -> None:
    metadata = SimpleNamespace(
        finish_reason=7,
        response_id=8,
        usage=SimpleNamespace(
            input_tokens=2,
            output_tokens=3,
            total_tokens="invalid",
        ),
    )
    provider = InstructorOpenAIProvider(
        model="gpt-test",
        capabilities=_capabilities(),
        completion=lambda **_kwargs: (Answer(value=1), metadata),
    )
    response = await _generate(provider)
    assert response.finish_reason is None
    assert response.response_id is None
    assert response.usage is not None
    assert response.usage.total_tokens == 5


@pytest.mark.asyncio
async def test_adapter_reports_missing_optional_extra_without_import_error_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = InstructorOpenAIProvider(
        model="gpt-test",
        api_key="not-a-real-key",
        capabilities=_capabilities(),
    )
    monkeypatch.setattr(
        provider, "_load_sdk_completion", lambda: (_ for _ in ()).throw(ImportError())
    )

    with pytest.raises(ProviderDependencyError, match="optional 'openai' extra"):
        await _generate(provider)


@pytest.mark.asyncio
async def test_adapter_propagates_cancelled_error() -> None:
    async def cancelled(**_kwargs: object) -> tuple[object, object]:
        raise asyncio.CancelledError

    provider = InstructorOpenAIProvider(
        model="gpt-test",
        api_key="not-a-real-key",
        capabilities=_capabilities(),
        completion=cancelled,
    )
    with pytest.raises(asyncio.CancelledError):
        await _generate(provider)
