"""Lazy Azure OpenAI adapter with key or refreshable token credentials."""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable, Collection, Mapping
from importlib import import_module
from typing import cast

from pydantic import BaseModel

from survey_scribe.config import GenerationConfig
from survey_scribe.errors import is_sensitive_key
from survey_scribe.providers.base import ProviderAuthenticationError, ProviderMessage
from survey_scribe.providers.capabilities import ModelCapabilities
from survey_scribe.providers.openai_compatible import (
    Completion,
    InstructorOpenAIProvider,
    _normalize_wire_output,
    _strict_wire_response_model,
    _validate_provider_base_url,
)

_HTTP_TOKEN_NAME = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_RESERVED_HEADERS = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "api-key",
        "host",
        "content-length",
        "content-type",
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-connection",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "expect",
    }
)


class AzureOpenAIProvider(InstructorOpenAIProvider):
    """Instructor-backed Azure adapter with per-attempt gateway headers.

    ``metadata_headers`` is copied at construction and must contain only
    non-secret values. ``sensitive_headers_callback`` is invoked immediately
    before each package-owned request attempt. ``required_headers`` is copied and
    checked case-insensitively after the two channels are merged. Caller-defined
    headers cannot replace authentication or HTTP transport headers.

    Callback or required-header failures become detached, non-retryable provider
    authentication errors. The callback must be synchronous and non-blocking.

    Args:
        metadata_headers: Non-secret static headers copied during construction.
        sensitive_headers_callback: Synchronous provider of attempt-local secret
            headers. The returned mapping is validated and not retained.
        required_headers: Header names that must exist after the two channels
            merge. Names are copied and compared case-insensitively.

    Raises:
        TypeError: A callback or required-header collection has the wrong shape.
        ValueError: Credentials, endpoint settings, or header rules are invalid.
    """

    def __init__(
        self,
        *,
        deployment: str,
        azure_endpoint: str,
        api_version: str,
        capabilities: ModelCapabilities,
        api_key: str | None = None,
        token_callback: Callable[[], str] | None = None,
        metadata_headers: Mapping[str, str] | None = None,
        sensitive_headers_callback: Callable[[], Mapping[str, str]] | None = None,
        required_headers: Collection[str] = (),
        completion: Completion | None = None,
    ) -> None:
        validation_error: tuple[type[Exception], str] | None = None
        try:
            if api_key is not None and token_callback is not None:
                raise ValueError("configure exactly one Azure credential form")
            if api_key is None and token_callback is None and completion is None:
                raise ValueError("configure exactly one Azure credential form")
            validated_endpoint = _validate_provider_base_url(
                azure_endpoint,
                label="Azure endpoint",
            )
            if not api_version.strip():
                raise ValueError("Azure API version must not be empty")
            if capabilities.provider not in {"azure", "azure_openai"}:
                raise ValueError("capability row provider must identify Azure OpenAI")
            if sensitive_headers_callback is not None and (
                not callable(sensitive_headers_callback)
                or inspect.iscoroutinefunction(sensitive_headers_callback)
            ):
                raise TypeError("Azure sensitive headers callback must be synchronous")
            validated_metadata = _validate_metadata_headers(metadata_headers)
            validated_required = _validate_required_headers(required_headers)
        except (TypeError, ValueError) as error:
            validation_error = (type(error), str(error))
        if validation_error is not None:
            error_type, error_message = validation_error
            api_key = None
            token_callback = None
            metadata_headers = None
            sensitive_headers_callback = None
            required_headers = ()
            azure_endpoint = ""
            raise error_type(error_message) from None
        super().__init__(
            model=deployment,
            capabilities=capabilities,
            completion=completion,
        )
        self._azure_endpoint = validated_endpoint
        self._api_version = api_version
        self._azure_api_key = api_key
        self._token_callback = token_callback
        self._metadata_headers = validated_metadata
        self._metadata_header_names = frozenset(name.casefold() for name in validated_metadata)
        self._sensitive_headers_callback = sensitive_headers_callback
        self._required_headers = validated_required

    @property
    def adapter_identity(self) -> str:
        return "survey-scribe/instructor-azure-openai/v1"

    def _load_sdk_completion(self) -> Completion:
        openai = import_module("openai")
        instructor = import_module("instructor")
        client_kwargs: dict[str, object] = {
            "azure_endpoint": self._azure_endpoint,
            "api_version": self._api_version,
            "max_retries": 0,
        }
        if self._azure_api_key is not None:
            client_kwargs["api_key"] = self._azure_api_key
        if self._token_callback is not None:
            client_kwargs["azure_ad_token_provider"] = self._token_callback
        client = openai.AsyncAzureOpenAI(**client_kwargs)
        self._client = client
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
                "response_model": _strict_wire_response_model(response_model, request_schema),
                "max_retries": 0,
                "temperature": generation.temperature,
                "max_tokens": generation.max_output_tokens,
            }
            extra_headers = cast(Mapping[str, str] | None, kwargs.get("extra_headers"))
            if extra_headers:
                request["extra_headers"] = dict(extra_headers)
            if generation.seed is not None:
                request["seed"] = generation.seed
            output, response = await patched.chat.completions.create_with_completion(**request)
            choice = response.choices[0] if response.choices else None
            usage = getattr(response, "usage", None)
            return _normalize_wire_output(output, response_model), {
                "finish_reason": getattr(choice, "finish_reason", None),
                "response_id": getattr(response, "id", None),
                "usage": (
                    {
                        "input_tokens": getattr(usage, "prompt_tokens", 0),
                        "output_tokens": getattr(usage, "completion_tokens", 0),
                        "total_tokens": getattr(usage, "total_tokens", 0),
                    }
                    if usage is not None
                    else None
                ),
            }

        return complete

    def _request_extra_headers(self) -> Mapping[str, str] | None:
        callback_result: object | None = None
        dynamic_headers: dict[str, str] | None = None
        merged_headers: dict[str, str] | None = None
        failed = False
        try:
            if self._sensitive_headers_callback is None:
                dynamic_headers = {}
            else:
                callback_result = self._sensitive_headers_callback()
                if inspect.isawaitable(callback_result):
                    close = getattr(callback_result, "close", None)
                    if callable(close):
                        close()
                    raise TypeError("Azure sensitive headers callback must be synchronous")
                dynamic_headers = _validate_header_mapping(callback_result, allow_sensitive=True)
            dynamic_names = {name.casefold() for name in dynamic_headers}
            if self._metadata_header_names & dynamic_names:
                raise ValueError("Azure metadata and sensitive header names must not collide")
            merged_headers = {**self._metadata_headers, **dynamic_headers}
            if not self._required_headers.issubset(self._metadata_header_names | dynamic_names):
                raise ValueError("Azure required headers are missing")
        except Exception:
            failed = True
            callback_result = None
            dynamic_headers = None
            merged_headers = None

        callback_result = None
        dynamic_headers = None
        if failed:
            raise ProviderAuthenticationError() from None
        return merged_headers or None


def _validate_metadata_headers(headers: object) -> dict[str, str]:
    if headers is None:
        return {}
    return _validate_header_mapping(headers, allow_sensitive=False)


def _validate_header_mapping(headers: object, *, allow_sensitive: bool) -> dict[str, str]:
    if not isinstance(headers, Mapping):
        raise TypeError("Azure headers must be a mapping")
    validated: dict[str, str] = {}
    normalized_names: set[str] = set()
    for name, value in headers.items():
        if not isinstance(name, str) or _HTTP_TOKEN_NAME.fullmatch(name) is None:
            raise ValueError("Azure header names must be non-empty ASCII HTTP token names")
        normalized = name.casefold()
        if normalized in normalized_names:
            raise ValueError("Azure header names must be unique case-insensitively")
        if normalized in _RESERVED_HEADERS:
            raise ValueError("Azure caller headers must not use reserved names")
        if not allow_sensitive and is_sensitive_key(name):
            raise ValueError("Azure sensitive metadata must use sensitive_headers_callback")
        if (
            not isinstance(value, str)
            or not value
            or not value.isascii()
            or value != value.strip(" ")
            or any(ord(character) <= 31 or ord(character) == 127 for character in value)
        ):
            raise ValueError(
                "Azure header values must be non-empty ASCII strings without controls "
                "or surrounding spaces"
            )
        normalized_names.add(normalized)
        validated[name] = value
    return validated


def _validate_required_headers(headers: object) -> frozenset[str]:
    if isinstance(headers, str | bytes) or not isinstance(headers, Collection):
        raise TypeError("Azure required headers must be a non-string collection")
    normalized_names: set[str] = set()
    for name in headers:
        if not isinstance(name, str) or _HTTP_TOKEN_NAME.fullmatch(name) is None:
            raise ValueError("Azure required header names must be valid HTTP token names")
        normalized = name.casefold()
        if normalized in normalized_names:
            raise ValueError("Azure required header names must be unique case-insensitively")
        if normalized in _RESERVED_HEADERS:
            raise ValueError("Azure required headers must not use reserved names")
        normalized_names.add(normalized)
    return frozenset(normalized_names)


__all__ = ["AzureOpenAIProvider"]
