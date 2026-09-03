"""Provider-neutral structured generation port and safe normalized results."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Generic, Literal, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

from survey_scribe.config import GenerationConfig, RetryConfig

T = TypeVar("T", bound=BaseModel)

_TRUNCATION_REASONS = frozenset(
    {
        "length",
        "max_output_tokens",
        "max_tokens",
        "model_length",
        "token_limit",
        "truncated",
    }
)


@dataclass(frozen=True, slots=True)
class ProviderMessage:
    """One provider-neutral chat message retained only for the active request."""

    role: Literal["system", "user", "assistant"]
    content: str

    def __post_init__(self) -> None:
        if not self.content:
            raise ValueError("provider message content must not be empty")


@dataclass(frozen=True, slots=True)
class NormalizedUsage:
    """Token usage without raw provider response data."""

    input_tokens: int
    output_tokens: int
    total_tokens: int

    def __post_init__(self) -> None:
        values = (self.input_tokens, self.output_tokens, self.total_tokens)
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values
        ):
            raise ValueError("normalized token usage must contain nonnegative integers")
        if self.total_tokens < self.input_tokens + self.output_tokens:
            raise ValueError("total token usage must include input and output usage")


@dataclass(frozen=True, slots=True)
class ProviderResponse(Generic[T]):
    """Validated model output with normalized non-sensitive provider metadata."""

    output: T
    usage: NormalizedUsage | None
    finish_reason: str | None
    provider: str
    model: str
    response_id: str | None
    transport_attempts: int
    validation_attempts: int

    def __post_init__(self) -> None:
        if not isinstance(self.output, BaseModel):
            raise TypeError("provider output must be a validated Pydantic model")
        if not self.provider or not self.model:
            raise ValueError("provider and model identifiers must not be empty")
        attempts = (self.transport_attempts, self.validation_attempts)
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in attempts
        ):
            raise ValueError("provider attempt counts must be positive integers")

    @property
    def truncated(self) -> bool:
        """Return whether the normalized finish reason means incomplete output."""
        return (self.finish_reason or "").strip().casefold() in _TRUNCATION_REASONS

    def require_complete(self) -> ProviderResponse[T]:
        """Fail closed when a provider reports token or length truncation."""
        if self.truncated:
            raise ProviderTruncationError()
        return self


@dataclass(frozen=True, slots=True)
class SchemaDescriptor:
    """Canonical and adapter-transformed schema identities for one model type."""

    canonical_schema_sha256: str
    request_schema_sha256: str
    canonical_schema_json: str
    request_schema_json: str

    def __post_init__(self) -> None:
        for value in (self.canonical_schema_sha256, self.request_schema_sha256):
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ValueError("schema hashes must be lowercase SHA-256 values")

    @property
    def canonical_schema(self) -> Mapping[str, object]:
        """Return a detached canonical schema mapping."""
        value = json.loads(self.canonical_schema_json)
        if not isinstance(value, dict):
            raise RuntimeError("canonical schema descriptor is invalid")
        return value

    @property
    def request_schema(self) -> Mapping[str, object]:
        """Return a detached transformed request schema mapping."""
        value = json.loads(self.request_schema_json)
        if not isinstance(value, dict):
            raise RuntimeError("request schema descriptor is invalid")
        return value


class ConcurrencyLimiter:
    """One shared asynchronous ceiling for all outbound attempts in a run."""

    def __init__(self, limit: int) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("concurrency limit must be a positive integer")
        self._semaphore = asyncio.Semaphore(limit)
        self._active = 0
        self._peak_active = 0

    @property
    def peak_active(self) -> int:
        """Return the maximum simultaneous outbound operations observed."""
        return self._peak_active

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        """Acquire one outbound-operation slot, including for a retry."""
        async with self._semaphore:
            self._active += 1
            self._peak_active = max(self._peak_active, self._active)
            try:
                yield
            finally:
                self._active -= 1


class ProviderError(Exception):
    """Base provider error with one fixed safe message and code."""

    code = "PROVIDER_ERROR"
    safe_message = "Structured provider operation failed."

    def __init__(self) -> None:
        super().__init__(self.safe_message)


class ProviderDependencyError(ProviderError, ImportError):
    """The selected optional provider extra is unavailable."""

    code = "PROVIDER_DEPENDENCY_MISSING"
    safe_message = "The optional provider extra is required for this provider."

    def __init__(self, extra: Literal["openai", "anthropic"] = "openai") -> None:
        self.safe_message = f"The optional '{extra}' extra is required for this provider."
        super().__init__()


class ProviderCapabilityError(ProviderError, ValueError):
    """A requested model, schema, limit, or setting is unsupported."""

    code = "PROVIDER_CAPABILITY_UNSUPPORTED"
    safe_message = "The provider does not support the requested strict structured output."

    def __init__(
        self,
        reason: Literal[
            "strict",
            "schema",
            "setting",
            "output_limit",
            "input_limit",
            "drift",
        ] = "strict",
    ) -> None:
        messages = {
            "strict": "The provider does not support strict structured output.",
            "schema": "The response model contains an unsupported strict schema.",
            "setting": "The request uses an unsupported generation setting.",
            "output_limit": "The request exceeds the provider output token limit.",
            "input_limit": "The request exceeds the provider input token limit.",
            "drift": "The provider schema descriptor changed during the routing run.",
        }
        self.safe_message = messages[reason]
        super().__init__()


class ProviderTransportError(ProviderError):
    """A provider transport failed with normalized retryability."""

    code = "PROVIDER_TRANSPORT_FAILED"
    safe_message = "The structured provider transport failed."

    def __init__(self, *, retryable: bool) -> None:
        self.retryable = retryable
        super().__init__()


class ProviderAuthenticationError(ProviderTransportError):
    """Provider credentials were rejected."""

    code = "PROVIDER_AUTHENTICATION_FAILED"
    safe_message = "Provider authentication failed."

    def __init__(self) -> None:
        super().__init__(retryable=False)


class ProviderRateLimitError(ProviderTransportError):
    """The provider applied a retryable rate limit."""

    code = "PROVIDER_RATE_LIMITED"
    safe_message = "The structured provider rate limit was exhausted."

    def __init__(self) -> None:
        super().__init__(retryable=True)


class ProviderValidationError(ProviderError, ValueError):
    """All bounded structured-response validation attempts failed."""

    code = "PROVIDER_VALIDATION_FAILED"
    safe_message = "The structured response validation failed."


class ProviderTruncationError(ProviderError):
    """The provider reported an incomplete length-limited response."""

    code = "PROVIDER_RESPONSE_TRUNCATED"
    safe_message = "The structured response was truncated."


@runtime_checkable
class StructuredProvider(Protocol):
    """Generic async port consumed directly by application and routing code."""

    @property
    def adapter_identity(self) -> str:
        """Return a stable adapter implementation identity."""
        ...

    @property
    def provider_name(self) -> str:
        """Return the normalized provider name."""
        ...

    @property
    def model(self) -> str:
        """Return the configured model or deployment identifier."""
        ...

    @property
    def max_input_tokens(self) -> int:
        """Return the named model row's input token limit."""
        ...

    def inspect_schema(self, response_model: type[T]) -> SchemaDescriptor:
        """Transform and validate a response schema without sending request data."""
        ...

    def estimate_tokens(self, messages: Sequence[ProviderMessage]) -> int:
        """Return a deterministic request-token estimate."""
        ...

    async def generate(
        self,
        *,
        messages: Sequence[ProviderMessage],
        response_model: type[T],
        generation: GenerationConfig,
        retry: RetryConfig,
        limiter: ConcurrencyLimiter,
    ) -> ProviderResponse[T]:
        """Generate one validated response through the shared limiter."""
        ...


__all__ = [
    "ConcurrencyLimiter",
    "NormalizedUsage",
    "ProviderAuthenticationError",
    "ProviderCapabilityError",
    "ProviderDependencyError",
    "ProviderError",
    "ProviderMessage",
    "ProviderRateLimitError",
    "ProviderResponse",
    "ProviderTransportError",
    "ProviderTruncationError",
    "ProviderValidationError",
    "SchemaDescriptor",
    "StructuredProvider",
]
