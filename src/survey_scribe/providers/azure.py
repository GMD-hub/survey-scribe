"""Lazy Azure OpenAI adapter with key or refreshable token credentials."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from importlib import import_module
from typing import cast

from pydantic import BaseModel

from survey_scribe.config import GenerationConfig
from survey_scribe.providers.base import ProviderMessage
from survey_scribe.providers.capabilities import ModelCapabilities
from survey_scribe.providers.openai_compatible import (
    Completion,
    InstructorOpenAIProvider,
    _strict_wire_response_model,
)


class AzureOpenAIProvider(InstructorOpenAIProvider):
    """Instructor-backed Azure adapter that keeps token callbacks refreshable."""

    def __init__(
        self,
        *,
        deployment: str,
        azure_endpoint: str,
        api_version: str,
        capabilities: ModelCapabilities,
        api_key: str | None = None,
        token_callback: Callable[[], str] | None = None,
        completion: Completion | None = None,
    ) -> None:
        if api_key is not None and token_callback is not None:
            raise ValueError("configure exactly one Azure credential form")
        if api_key is None and token_callback is None and completion is None:
            raise ValueError("configure exactly one Azure credential form")
        if not azure_endpoint.startswith("https://"):
            raise ValueError("Azure endpoint must use HTTPS")
        if not api_version.strip():
            raise ValueError("Azure API version must not be empty")
        if capabilities.provider not in {"azure", "azure_openai"}:
            raise ValueError("capability row provider must identify Azure OpenAI")
        super().__init__(
            model=deployment,
            capabilities=capabilities,
            completion=completion,
        )
        self._azure_endpoint = azure_endpoint
        self._api_version = api_version
        self._azure_api_key = api_key
        self._token_callback = token_callback

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
            if generation.seed is not None:
                request["seed"] = generation.seed
            output, response = await patched.chat.completions.create_with_completion(**request)
            choice = response.choices[0] if response.choices else None
            usage = getattr(response, "usage", None)
            return output, {
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


__all__ = ["AzureOpenAIProvider"]
