"""Deterministic in-memory provider fake for contract and pipeline tests."""

from __future__ import annotations

import asyncio
import inspect
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from typing import Generic, Literal, TypeVar, cast

from pydantic import BaseModel, ValidationError

from survey_scribe.config import GenerationConfig, RetryConfig
from survey_scribe.providers.base import (
    ConcurrencyLimiter,
    ProviderMessage,
    ProviderResponse,
    ProviderTransportError,
    ProviderTruncationError,
    ProviderValidationError,
    SchemaDescriptor,
)
from survey_scribe.providers.capabilities import ModelCapabilities

T = TypeVar("T", bound=BaseModel)
Responder = Callable[["FakeRequest"], object | Awaitable[object]]


@dataclass(frozen=True, slots=True)
class FakeRequest:
    """Ephemeral fake request passed to a test callback and never retained."""

    messages: tuple[ProviderMessage, ...]
    response_model: type[BaseModel]
    generation: GenerationConfig
    request_schema_sha256: str


@dataclass(frozen=True, slots=True)
class FakeStep(Generic[T]):
    """One scripted transport, validation, truncation, or control outcome."""

    kind: Literal["output", "invalid", "transport", "raise"]
    value: object = None
    finish_reason: str | None = "stop"
    retryable: bool = False
    delay_seconds: float = 0.0

    @classmethod
    def output(
        cls,
        value: T,
        *,
        finish_reason: str | None = "stop",
        delay_seconds: float = 0.0,
    ) -> FakeStep[T]:
        return cls(
            kind="output",
            value=value,
            finish_reason=finish_reason,
            delay_seconds=delay_seconds,
        )

    @classmethod
    def invalid(cls, value: object, *, delay_seconds: float = 0.0) -> FakeStep[T]:
        return cls(kind="invalid", value=value, delay_seconds=delay_seconds)

    @classmethod
    def transport_error(
        cls,
        *,
        retryable: bool,
        delay_seconds: float = 0.0,
    ) -> FakeStep[T]:
        return cls(kind="transport", retryable=retryable, delay_seconds=delay_seconds)

    @classmethod
    def raises(cls, error: BaseException) -> FakeStep[T]:
        return cls(kind="raise", value=error)


class DeterministicFakeProvider:
    """Provider-port fake with bounded retries and no retained request bodies."""

    def __init__(
        self,
        *,
        capabilities: ModelCapabilities,
        steps: Sequence[FakeStep[BaseModel]] = (),
        responder: Responder | None = None,
    ) -> None:
        if steps and responder is not None:
            raise ValueError("configure scripted steps or one responder, not both")
        self.capabilities = capabilities
        self._steps = deque(steps)
        self._responder = responder
        self.call_count = 0
        self._inspection_count = 0
        self.schema_drift_after_inspections: int | None = None
        self._limiter: ConcurrencyLimiter | None = None

    @property
    def adapter_identity(self) -> str:
        return "survey-scribe/deterministic-fake/v1"

    @property
    def provider_name(self) -> str:
        return self.capabilities.provider

    @property
    def model(self) -> str:
        return self.capabilities.model

    @property
    def max_input_tokens(self) -> int:
        return self.capabilities.max_input_tokens

    @property
    def retained_request_bodies(self) -> int:
        return 0

    @property
    def peak_concurrency(self) -> int:
        return self._limiter.peak_active if self._limiter is not None else 0

    def inspect_schema(self, response_model: type[T]) -> SchemaDescriptor:
        self._inspection_count += 1
        descriptor = self.capabilities.inspect_schema(response_model)
        threshold = self.schema_drift_after_inspections
        if threshold is not None and self._inspection_count > threshold:
            return replace(descriptor, request_schema_sha256="f" * 64)
        return descriptor

    def estimate_tokens(self, messages: Sequence[ProviderMessage]) -> int:
        return self.capabilities.estimate_messages(tuple(messages))

    async def generate(
        self,
        *,
        messages: Sequence[ProviderMessage],
        response_model: type[T],
        generation: GenerationConfig,
        retry: RetryConfig,
        limiter: ConcurrencyLimiter,
    ) -> ProviderResponse[T]:
        descriptor = self.inspect_schema(response_model)
        self.capabilities.validate_generation(generation)
        materialized_messages = tuple(messages)
        self._limiter = limiter
        transport_attempts = 0
        validation_attempts = 0
        while transport_attempts < retry.max_attempts:
            transport_attempts += 1
            try:
                async with limiter.slot():
                    self.call_count += 1
                    raw, finish_reason = await self._one_attempt(
                        FakeRequest(
                            messages=materialized_messages,
                            response_model=response_model,
                            generation=generation,
                            request_schema_sha256=descriptor.request_schema_sha256,
                        )
                    )
            except ProviderTransportError as error:
                if not error.retryable or transport_attempts >= retry.max_attempts:
                    raise
                await _retry_delay(retry, transport_attempts)
                continue

            validation_attempts += 1
            try:
                output = response_model.model_validate(raw)
            except ValidationError:
                if validation_attempts >= retry.max_attempts:
                    raise ProviderValidationError() from None
                await _retry_delay(retry, validation_attempts)
                continue
            response = ProviderResponse(
                output=output,
                usage=None,
                finish_reason=finish_reason,
                provider=self.provider_name,
                model=self.model,
                response_id=None,
                transport_attempts=transport_attempts,
                validation_attempts=validation_attempts,
            )
            if response.truncated:
                raise ProviderTruncationError()
            return response
        raise ProviderTransportError(retryable=False)

    async def _one_attempt(self, request: FakeRequest) -> tuple[object, str | None]:
        if self._responder is not None:
            value = self._responder(request)
            if inspect.isawaitable(value):
                value = await cast(Awaitable[object], value)
            return value, "stop"
        if not self._steps:
            raise ProviderTransportError(retryable=False)
        step = self._steps.popleft()
        if step.delay_seconds:
            await asyncio.sleep(step.delay_seconds)
        if step.kind == "transport":
            raise ProviderTransportError(retryable=step.retryable)
        if step.kind == "raise":
            error = step.value
            if not isinstance(error, BaseException):
                raise RuntimeError("invalid fake control step")
            raise error
        return step.value, step.finish_reason


async def _retry_delay(retry: RetryConfig, attempt: int) -> None:
    delay = min(
        retry.max_delay_seconds,
        retry.initial_delay_seconds * (2 ** max(0, attempt - 1)),
    )
    if delay:
        await asyncio.sleep(delay)


__all__ = ["DeterministicFakeProvider", "FakeRequest", "FakeStep"]
