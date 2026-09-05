"""Instructor-backed OpenAI-compatible adapter contracts."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from types import SimpleNamespace
from typing import cast

import pytest
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_serializer, field_validator

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

pytestmark = pytest.mark.allow_hosts(["127.0.0.1", "::1"])


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: int


class AliasedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: int = Field(validation_alias="wireValue", serialization_alias="serializedValue")

    @field_validator("value")
    @classmethod
    def increment_once(cls, value: int) -> int:
        return value + 1

    @field_serializer("value")
    def serialize_value(self, value: int) -> int:
        return value + 100

    @computed_field
    @property
    def doubled(self) -> int:
        return self.value * 2


def _provider_traceback_locals(error: BaseException) -> list[str]:
    values: list[str] = []
    traceback = error.__traceback__
    while traceback is not None:
        filename = traceback.tb_frame.f_code.co_filename.replace("\\", "/")
        if "/src/survey_scribe/providers/" in f"/{filename}":
            values.append(repr(traceback.tb_frame.f_locals))
        traceback = traceback.tb_next
    return values


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


@pytest.mark.parametrize(
    "base_url",
    [
        "https://user:private@example.test",  # pragma: allowlist secret
        "https://example.test/v1#private-fragment",
        "https://example.test/v1?OcpApimSubscriptionKey=private-query",
    ],
)
def test_generic_constructor_detaches_credential_bearing_base_urls(base_url: str) -> None:
    with pytest.raises(ValueError) as error:
        InstructorOpenAIProvider(
            model="gpt-test",
            api_key="private-primary",  # pragma: allowlist secret
            base_url=base_url,
            capabilities=_capabilities(),
        )

    provider_frames = _provider_traceback_locals(error.value)

    assert provider_frames
    assert "private-primary" not in repr(provider_frames)
    assert "private-query" not in repr(provider_frames)


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
async def test_generic_adapter_keeps_explicit_completion_keyword_contract() -> None:
    async def completion(
        *,
        model: str,
        messages: tuple[ProviderMessage, ...],
        response_model: type[BaseModel],
        request_schema: object,
        generation: GenerationConfig,
    ) -> Answer:
        assert model == "gpt-test"
        assert messages
        assert response_model is Answer
        assert request_schema
        assert generation.max_output_tokens == 4096
        return Answer(value=9)

    provider = InstructorOpenAIProvider(
        model="gpt-test",
        capabilities=_capabilities(),
        completion=completion,
    )

    response = await _generate(provider)

    assert response.output == Answer(value=9)


def test_wire_output_preserves_validated_alias_and_serializer_values() -> None:
    wire_model = adapter_module._strict_wire_response_model(
        AliasedAnswer,
        _capabilities().inspect_schema(AliasedAnswer).request_schema,
    )
    wire_output = wire_model.model_validate({"wireValue": 4})

    output = adapter_module._normalize_wire_output(wire_output, AliasedAnswer)

    assert isinstance(output, AliasedAnswer)
    assert output.value == 5
    assert output.doubled == 10


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
async def test_mixed_failure_raises_final_validation_category_without_extra_delay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    delays: list[float] = []

    async def no_wait(delay: float) -> None:
        delays.append(delay)

    async def mixed(**_kwargs: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError
        return {"value": "invalid"}

    monkeypatch.setattr(asyncio, "sleep", no_wait)
    provider = InstructorOpenAIProvider(
        model="gpt-test",
        capabilities=_capabilities(),
        completion=mixed,
    )

    with pytest.raises(ProviderValidationError):
        await provider.generate(
            messages=(ProviderMessage(role="user", content="questionnaire"),),
            response_model=Answer,
            generation=GenerationConfig(),
            retry=RetryConfig(max_attempts=2, initial_delay_seconds=0.1),
            limiter=ConcurrencyLimiter(1),
        )

    assert calls == 2
    assert delays == [0.1]


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
    selected_modes: list[object] = []

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
    strict_mode = object()

    def from_openai(_client: object, *, mode: object) -> object:
        selected_modes.append(mode)
        return patched

    modules = {
        "openai": SimpleNamespace(AsyncOpenAI=FakeAsyncOpenAI),
        "instructor": SimpleNamespace(
            Mode=SimpleNamespace(TOOLS_STRICT=strict_mode),
            from_openai=from_openai,
        ),
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
        "max_retries": 0,
    }
    assert request_kwargs["messages"] == [
        {"role": "system", "content": "fixed"},
        {"role": "user", "content": "source"},
    ]
    assert request_kwargs["max_retries"] == 0
    assert request_kwargs["seed"] == 4
    assert selected_modes == [strict_mode]

    from instructor import Mode
    from instructor.process_response import handle_response_model

    _processed_model, wire_request = handle_response_model(
        cast(type[BaseModel], request_kwargs["response_model"]),
        mode=Mode.TOOLS_STRICT,
        messages=request_kwargs["messages"],
    )
    wire_function = wire_request["tools"][0]["function"]
    assert wire_function["strict"] is True
    wire_schema_json = json.dumps(
        wire_function["parameters"],
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    assert hashlib.sha256(wire_schema_json.encode("utf-8")).hexdigest() == (
        provider.inspect_schema(Answer).request_schema_sha256
    )
    assert wire_function["parameters"]["title"] == "AnswerStrictWire"
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

    inconsistent = SimpleNamespace(
        finish_reason="stop",
        response_id=None,
        usage={"input_tokens": 5, "output_tokens": 4, "total_tokens": 1},
    )
    safe = InstructorOpenAIProvider(
        model="gpt-test",
        capabilities=_capabilities(),
        completion=lambda **_kwargs: (Answer(value=2), inconsistent),
    )
    normalized = await _generate(safe)
    assert normalized.usage is not None
    assert normalized.usage.total_tokens == 9


@pytest.mark.asyncio
async def test_sdk_connection_and_instructor_validation_errors_use_bounded_retries() -> None:
    import httpx
    from instructor.exceptions import InstructorRetryException
    from openai import APIConnectionError

    connection_calls = 0

    async def connection_once(**_kwargs: object) -> Answer:
        nonlocal connection_calls
        connection_calls += 1
        if connection_calls == 1:
            raise APIConnectionError(request=httpx.Request("POST", "https://example.test"))
        return Answer(value=12)

    connection_provider = InstructorOpenAIProvider(
        model="gpt-test",
        capabilities=_capabilities(),
        completion=connection_once,
    )
    connection_response = await _generate(connection_provider)
    assert connection_response.transport_attempts == 2

    validation_calls = 0

    async def validation_once(**_kwargs: object) -> Answer:
        nonlocal validation_calls
        validation_calls += 1
        if validation_calls == 1:
            raise InstructorRetryException(
                [ValueError("private questionnaire")],
                n_attempts=1,
                total_usage=0,
            )
        return Answer(value=13)

    validation_provider = InstructorOpenAIProvider(
        model="gpt-test",
        capabilities=_capabilities(),
        completion=validation_once,
    )
    validation_response = await _generate(validation_provider)
    assert validation_response.transport_attempts == 2
    assert validation_response.validation_attempts == 2


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
