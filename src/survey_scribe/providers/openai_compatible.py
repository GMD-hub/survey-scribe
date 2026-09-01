"""Lazy Instructor-backed adapter for OpenAI-compatible structured endpoints."""

from __future__ import annotations

import asyncio
import copy
import inspect
from collections.abc import Awaitable, Callable, Mapping, Sequence
from importlib import import_module
from typing import TypeVar, cast

from pydantic import BaseModel, ValidationError, create_model

from survey_scribe.config import GenerationConfig, RetryConfig
from survey_scribe.providers.base import (
    ConcurrencyLimiter,
    NormalizedUsage,
    ProviderAuthenticationError,
    ProviderDependencyError,
    ProviderMessage,
    ProviderRateLimitError,
    ProviderResponse,
    ProviderTransportError,
    ProviderTruncationError,
    ProviderValidationError,
    SchemaDescriptor,
)
from survey_scribe.providers.capabilities import ModelCapabilities

T = TypeVar("T", bound=BaseModel)
Completion = Callable[..., object | Awaitable[object]]


class InstructorOpenAIProvider:
    """Structured OpenAI-compatible provider with Instructor kept internal."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        capabilities: ModelCapabilities,
        completion: Completion | None = None,
    ) -> None:
        if not model.strip():
            raise ValueError("provider model must not be empty")
        if capabilities.model != model:
            raise ValueError("capability row model must match the configured model")
        self._model = model
        self._api_key = api_key
        self._base_url = base_url
        self.capabilities = capabilities
        self._completion = completion

    @property
    def adapter_identity(self) -> str:
        return "survey-scribe/instructor-openai-compatible/v1"

    @property
    def provider_name(self) -> str:
        return self.capabilities.provider

    @property
    def model(self) -> str:
        return self._model

    @property
    def max_input_tokens(self) -> int:
        return self.capabilities.max_input_tokens

    def inspect_schema(self, response_model: type[T]) -> SchemaDescriptor:
        return self.capabilities.inspect_schema(response_model)

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
        completion = self._completion
        if completion is None:
            try:
                completion = self._load_sdk_completion()
            except ImportError:
                raise ProviderDependencyError() from None
        materialized_messages = tuple(messages)
        transport_attempts = 0
        validation_attempts = 0
        while transport_attempts < retry.max_attempts:
            transport_attempts += 1
            try:
                async with limiter.slot():
                    result = completion(
                        model=self.model,
                        messages=materialized_messages,
                        response_model=response_model,
                        request_schema=descriptor.request_schema,
                        generation=generation,
                    )
                    if inspect.isawaitable(result):
                        result = await cast(Awaitable[object], result)
            except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
                raise
            except ProviderTransportError as error:
                if not error.retryable or transport_attempts >= retry.max_attempts:
                    raise
                await _retry_delay(retry, transport_attempts)
                continue
            except Exception as error:
                normalized = _classify_transport_error(error)
                if not normalized.retryable or transport_attempts >= retry.max_attempts:
                    raise normalized from None
                await _retry_delay(retry, transport_attempts)
                continue

            output_value, metadata = _split_result(result)
            validation_attempts += 1
            try:
                output = response_model.model_validate(output_value)
            except ValidationError:
                if validation_attempts >= retry.max_attempts:
                    raise ProviderValidationError() from None
                await _retry_delay(retry, validation_attempts)
                continue
            response = ProviderResponse(
                output=output,
                usage=_usage(metadata),
                finish_reason=_metadata_value(metadata, "finish_reason"),
                provider=self.provider_name,
                model=self.model,
                response_id=_metadata_value(metadata, "response_id"),
                transport_attempts=transport_attempts,
                validation_attempts=validation_attempts,
            )
            if response.truncated:
                raise ProviderTruncationError()
            return response
        raise ProviderTransportError(retryable=False)

    def _load_sdk_completion(self) -> Completion:
        openai = import_module("openai")
        instructor = import_module("instructor")
        client_kwargs: dict[str, object] = {}
        if self._api_key is not None:
            client_kwargs["api_key"] = self._api_key
        if self._base_url is not None:
            client_kwargs["base_url"] = self._base_url
        client = openai.AsyncOpenAI(**client_kwargs)
        patched = instructor.from_openai(client, mode=instructor.Mode.TOOLS_STRICT)

        async def complete(**kwargs: object) -> object:
            generation = cast(GenerationConfig, kwargs["generation"])
            messages = cast(tuple[ProviderMessage, ...], kwargs["messages"])
            response_model = cast(type[BaseModel], kwargs["response_model"])
            request_schema = cast(Mapping[str, object], kwargs["request_schema"])
            request: dict[str, object] = {
                "model": kwargs["model"],
                "messages": [
                    {"role": message.role, "content": message.content} for message in messages
                ],
                "response_model": _strict_wire_response_model(
                    response_model,
                    request_schema,
                ),
                "max_retries": 0,
                "temperature": generation.temperature,
                "max_tokens": generation.max_output_tokens,
            }
            if generation.seed is not None:
                request["seed"] = generation.seed
            output, completion_response = await patched.chat.completions.create_with_completion(
                **request
            )
            choice = completion_response.choices[0] if completion_response.choices else None
            usage = getattr(completion_response, "usage", None)
            return output, {
                "finish_reason": getattr(choice, "finish_reason", None),
                "response_id": getattr(completion_response, "id", None),
                "usage": {
                    "input_tokens": getattr(usage, "prompt_tokens", 0),
                    "output_tokens": getattr(usage, "completion_tokens", 0),
                    "total_tokens": getattr(usage, "total_tokens", 0),
                }
                if usage is not None
                else None,
            }

        return complete


def _strict_wire_response_model(
    response_model: type[T],
    request_schema: Mapping[str, object],
) -> type[T]:
    wire_model = create_model(
        f"{response_model.__name__}StrictWire",
        __base__=response_model,
    )

    def model_json_schema(
        cls: type[BaseModel], *_args: object, **_kwargs: object
    ) -> dict[str, object]:
        del cls
        return copy.deepcopy(dict(request_schema))

    wire_model.model_json_schema = classmethod(model_json_schema)  # type: ignore[method-assign]
    return cast(type[T], wire_model)


def _split_result(result: object) -> tuple[object, object]:
    if isinstance(result, tuple) and len(result) == 2:
        return result
    return result, {}


def _metadata_value(metadata: object, name: str) -> str | None:
    value = metadata.get(name) if isinstance(metadata, Mapping) else getattr(metadata, name, None)
    return value if isinstance(value, str) else None


def _usage(metadata: object) -> NormalizedUsage | None:
    raw = (
        metadata.get("usage") if isinstance(metadata, Mapping) else getattr(metadata, "usage", None)
    )
    if raw is None:
        return None

    def value(name: str) -> int:
        item = raw.get(name, 0) if isinstance(raw, Mapping) else getattr(raw, name, 0)
        return item if isinstance(item, int) and not isinstance(item, bool) and item >= 0 else 0

    input_tokens = value("input_tokens")
    output_tokens = value("output_tokens")
    total_tokens = value("total_tokens") or input_tokens + output_tokens
    return NormalizedUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )


def _classify_transport_error(error: Exception) -> ProviderTransportError:
    status = getattr(error, "status_code", None)
    if not isinstance(status, int):
        text = str(error)
        status = next(
            (code for code in (401, 403, 408, 429, 500, 502, 503, 504) if str(code) in text), None
        )
    if status in {401, 403}:
        return ProviderAuthenticationError()
    if status == 429:
        return ProviderRateLimitError()
    retryable = isinstance(error, TimeoutError | ConnectionError) or (
        isinstance(status, int) and (status == 408 or status >= 500)
    )
    return ProviderTransportError(retryable=retryable)


async def _retry_delay(retry: RetryConfig, attempt: int) -> None:
    delay = min(
        retry.max_delay_seconds,
        retry.initial_delay_seconds * (2 ** max(0, attempt - 1)),
    )
    if delay:
        await asyncio.sleep(delay)


__all__ = ["InstructorOpenAIProvider"]
