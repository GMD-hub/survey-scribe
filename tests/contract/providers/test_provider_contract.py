"""Shared structured-provider contract and deterministic fake behavior."""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError

import pytest
from pydantic import BaseModel, ConfigDict

from survey_scribe.config import GenerationConfig, RetryConfig
from survey_scribe.providers.base import (
    ConcurrencyLimiter,
    NormalizedUsage,
    ProviderCapabilityError,
    ProviderMessage,
    ProviderResponse,
    ProviderTransportError,
    ProviderTruncationError,
    ProviderValidationError,
    SchemaDescriptor,
)
from survey_scribe.providers.capabilities import (
    CapabilityEvidence,
    ModelCapabilities,
    schema_descriptor,
)
from survey_scribe.providers.testing import DeterministicFakeProvider, FakeStep

pytestmark = pytest.mark.allow_hosts(["127.0.0.1", "::1"])


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: int


class OpenMapping(BaseModel):
    values: dict[str, object]


def _capabilities(**changes: object) -> ModelCapabilities:
    values: dict[str, object] = {
        "provider": "fake",
        "model": "fake-structured-v1",
        "structured_output": True,
        "strict_schema": True,
        "max_input_tokens": 32_768,
        "max_output_tokens": 4_096,
        "supported_generation_settings": frozenset({"temperature", "max_output_tokens", "seed"}),
        "evidence": CapabilityEvidence.verified,
        "tested_sdk_version": "fake-1",
    }
    values.update(changes)
    return ModelCapabilities(**values)  # type: ignore[arg-type]


def test_provider_response_is_frozen_generic_and_normalizes_truncation() -> None:
    response = ProviderResponse(
        output=Answer(value=7),
        usage=NormalizedUsage(input_tokens=10, output_tokens=2, total_tokens=12),
        finish_reason="stop",
        provider="fake",
        model="fake-structured-v1",
        response_id="response-1",
        transport_attempts=2,
        validation_attempts=1,
    )

    assert response.output.value == 7
    assert response.truncated is False
    with pytest.raises(FrozenInstanceError):
        response.model = "changed"  # type: ignore[misc]

    truncated = ProviderResponse(
        output=Answer(value=7),
        usage=None,
        finish_reason="max_tokens",
        provider="fake",
        model="fake-structured-v1",
        response_id=None,
        transport_attempts=1,
        validation_attempts=1,
    )
    assert truncated.truncated is True
    with pytest.raises(ProviderTruncationError, match="structured response was truncated"):
        truncated.require_complete()


def test_provider_boundary_models_reject_invalid_safe_metadata() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        ProviderMessage(role="user", content="")
    with pytest.raises(ValueError, match="nonnegative integers"):
        NormalizedUsage(input_tokens=-1, output_tokens=0, total_tokens=0)
    with pytest.raises(ValueError, match="include input and output"):
        NormalizedUsage(input_tokens=2, output_tokens=2, total_tokens=3)
    with pytest.raises(TypeError, match="Pydantic model"):
        ProviderResponse(
            output={"value": 1},  # type: ignore[arg-type]
            usage=None,
            finish_reason=None,
            provider="fake",
            model="model",
            response_id=None,
            transport_attempts=1,
            validation_attempts=1,
        )
    with pytest.raises(ValueError, match="identifiers"):
        ProviderResponse(
            output=Answer(value=1),
            usage=None,
            finish_reason=None,
            provider="",
            model="model",
            response_id=None,
            transport_attempts=1,
            validation_attempts=1,
        )
    with pytest.raises(ValueError, match="SHA-256"):
        SchemaDescriptor(
            canonical_schema_sha256="bad",
            request_schema_sha256="a" * 64,
            canonical_schema_json="{}",
            request_schema_json="{}",
        )
    invalid = SchemaDescriptor(
        canonical_schema_sha256="a" * 64,
        request_schema_sha256="b" * 64,
        canonical_schema_json="[]",
        request_schema_json="[]",
    )
    with pytest.raises(RuntimeError, match="canonical schema"):
        _ = invalid.canonical_schema
    with pytest.raises(RuntimeError, match="request schema"):
        _ = invalid.request_schema
    with pytest.raises(ValueError, match="positive integer"):
        ConcurrencyLimiter(0)


@pytest.mark.parametrize(
    ("field", "value"),
    (("transport_attempts", 0), ("validation_attempts", 0)),
)
def test_provider_response_rejects_invalid_attempt_counts(field: str, value: int) -> None:
    kwargs = {
        "output": Answer(value=1),
        "usage": None,
        "finish_reason": "stop",
        "provider": "fake",
        "model": "fake-structured-v1",
        "response_id": None,
        "transport_attempts": 1,
        "validation_attempts": 1,
    }
    kwargs[field] = value
    with pytest.raises(ValueError, match="attempt counts"):
        ProviderResponse(**kwargs)


def test_schema_descriptor_is_deterministic_strict_and_hashes_both_schemas() -> None:
    descriptor = schema_descriptor(Answer)
    repeated = schema_descriptor(Answer)

    assert descriptor == repeated
    assert len(descriptor.canonical_schema_sha256) == 64
    assert len(descriptor.request_schema_sha256) == 64
    assert descriptor.canonical_schema_sha256 != descriptor.request_schema_sha256
    request_schema = descriptor.request_schema
    assert descriptor.canonical_schema["type"] == "object"
    assert request_schema["additionalProperties"] is False
    assert request_schema["required"] == ["value"]


def test_capabilities_reject_non_strict_or_semantically_open_schemas() -> None:
    with pytest.raises(ProviderCapabilityError, match="strict structured output"):
        _capabilities(strict_schema=False).inspect_schema(Answer)
    with pytest.raises(ProviderCapabilityError, match="unsupported strict schema"):
        _capabilities().inspect_schema(OpenMapping)


def test_capabilities_fail_closed_for_limits_and_unknown_generation_settings() -> None:
    capabilities = _capabilities(
        max_output_tokens=100,
        supported_generation_settings=frozenset({"temperature", "max_output_tokens"}),
    )
    with pytest.raises(ProviderCapabilityError, match="generation setting"):
        capabilities.validate_generation(GenerationConfig(seed=1))
    with pytest.raises(ProviderCapabilityError, match="output token limit"):
        capabilities.validate_generation(GenerationConfig(max_output_tokens=101))


def test_capability_rows_reject_unknown_or_malformed_claims_and_schema_types() -> None:
    with pytest.raises(ValueError, match="identifiers"):
        _capabilities(provider="")
    with pytest.raises(ValueError, match="token limits"):
        _capabilities(max_input_tokens=0)
    with pytest.raises(ValueError, match="unknown generation"):
        _capabilities(supported_generation_settings=frozenset({"top_p"}))
    with pytest.raises(ProviderCapabilityError, match="strict structured output"):
        _capabilities(evidence=CapabilityEvidence.unknown).inspect_schema(Answer)
    with pytest.raises(TypeError, match="Pydantic model class"):
        schema_descriptor(dict)  # type: ignore[arg-type]

    class OpenAdditional(BaseModel):
        model_config = ConfigDict(extra="forbid")

        values: dict[str, int]

    with pytest.raises(ProviderCapabilityError, match="unsupported strict schema"):
        schema_descriptor(OpenAdditional)


@pytest.mark.asyncio
async def test_fake_normalizes_transport_and_validation_attempts() -> None:
    provider = DeterministicFakeProvider(
        capabilities=_capabilities(),
        steps=(
            FakeStep.transport_error(retryable=True),
            FakeStep.invalid({"value": "not-an-integer"}),
            FakeStep.output(Answer(value=9)),
        ),
    )

    response = await provider.generate(
        messages=(ProviderMessage(role="user", content="untrusted questionnaire"),),
        response_model=Answer,
        generation=GenerationConfig(),
        retry=RetryConfig(initial_delay_seconds=0.0, max_delay_seconds=0.0),
        limiter=ConcurrencyLimiter(1),
    )

    assert response.output == Answer(value=9)
    assert response.transport_attempts == 3
    assert response.validation_attempts == 2
    assert provider.call_count == 3
    assert provider.retained_request_bodies == 0


@pytest.mark.asyncio
async def test_fake_fails_closed_on_truncation_and_validation_exhaustion() -> None:
    truncated = DeterministicFakeProvider(
        capabilities=_capabilities(),
        steps=(FakeStep.output(Answer(value=1), finish_reason="length"),),
    )
    with pytest.raises(ProviderTruncationError, match="structured response was truncated"):
        await truncated.generate(
            messages=(ProviderMessage(role="user", content="private source"),),
            response_model=Answer,
            generation=GenerationConfig(),
            retry=RetryConfig(max_attempts=1),
            limiter=ConcurrencyLimiter(1),
        )

    invalid = DeterministicFakeProvider(
        capabilities=_capabilities(),
        steps=(FakeStep.invalid({"value": "private source"}),),
    )
    with pytest.raises(
        ProviderValidationError, match="structured response validation failed"
    ) as error:
        await invalid.generate(
            messages=(ProviderMessage(role="user", content="private source"),),
            response_model=Answer,
            generation=GenerationConfig(),
            retry=RetryConfig(max_attempts=1),
            limiter=ConcurrencyLimiter(1),
        )
    assert "private source" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "control",
    (asyncio.CancelledError(), KeyboardInterrupt(), SystemExit()),
)
async def test_provider_propagates_cancellation_and_process_control(control: BaseException) -> None:
    provider = DeterministicFakeProvider(
        capabilities=_capabilities(),
        steps=(FakeStep.raises(control),),
    )
    with pytest.raises(type(control)):
        await provider.generate(
            messages=(ProviderMessage(role="user", content="private source"),),
            response_model=Answer,
            generation=GenerationConfig(),
            retry=RetryConfig(),
            limiter=ConcurrencyLimiter(1),
        )


@pytest.mark.asyncio
async def test_one_limiter_covers_each_fake_retry() -> None:
    limiter = ConcurrencyLimiter(2)
    providers = tuple(
        DeterministicFakeProvider(
            capabilities=_capabilities(),
            steps=(
                FakeStep.transport_error(retryable=True, delay_seconds=0.01),
                FakeStep.output(Answer(value=index), delay_seconds=0.01),
            ),
        )
        for index in range(6)
    )
    await asyncio.gather(
        *(
            provider.generate(
                messages=(ProviderMessage(role="user", content="source"),),
                response_model=Answer,
                generation=GenerationConfig(),
                retry=RetryConfig(initial_delay_seconds=0.0, max_delay_seconds=0.0),
                limiter=limiter,
            )
            for provider in providers
        )
    )

    assert limiter.peak_active == 2


@pytest.mark.asyncio
async def test_fake_rejects_conflicting_setup_and_invalid_or_missing_steps() -> None:
    async def responder(_request: object) -> object:
        return Answer(value=1)

    with pytest.raises(ValueError, match="not both"):
        DeterministicFakeProvider(
            capabilities=_capabilities(),
            steps=(FakeStep.output(Answer(value=1)),),
            responder=responder,
        )
    missing = DeterministicFakeProvider(capabilities=_capabilities())
    with pytest.raises(ProviderTransportError):
        await missing.generate(
            messages=(ProviderMessage(role="user", content="source"),),
            response_model=Answer,
            generation=GenerationConfig(),
            retry=RetryConfig(max_attempts=1),
            limiter=ConcurrencyLimiter(1),
        )
    invalid_control = DeterministicFakeProvider(
        capabilities=_capabilities(),
        steps=(FakeStep(kind="raise", value="not-an-exception"),),
    )
    with pytest.raises(RuntimeError, match="invalid fake control"):
        await invalid_control.generate(
            messages=(ProviderMessage(role="user", content="source"),),
            response_model=Answer,
            generation=GenerationConfig(),
            retry=RetryConfig(max_attempts=1),
            limiter=ConcurrencyLimiter(1),
        )


@pytest.mark.asyncio
async def test_fake_retry_delay_is_bounded_and_cancellable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delays: list[float] = []

    async def no_wait(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(asyncio, "sleep", no_wait)
    provider = DeterministicFakeProvider(
        capabilities=_capabilities(),
        steps=(
            FakeStep.transport_error(retryable=True, delay_seconds=0.25),
            FakeStep.output(Answer(value=1)),
        ),
    )
    await provider.generate(
        messages=(ProviderMessage(role="user", content="source"),),
        response_model=Answer,
        generation=GenerationConfig(),
        retry=RetryConfig(initial_delay_seconds=0.2, max_delay_seconds=0.2),
        limiter=ConcurrencyLimiter(1),
    )
    assert delays == [0.25, 0.2]
