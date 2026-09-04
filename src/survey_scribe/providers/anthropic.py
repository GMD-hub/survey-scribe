"""Lazy Instructor-backed Anthropic structured-output adapter."""

from __future__ import annotations

from importlib import import_module
from typing import Literal, cast

from pydantic import BaseModel

from survey_scribe.config import GenerationConfig
from survey_scribe.providers.base import ProviderMessage
from survey_scribe.providers.capabilities import ModelCapabilities
from survey_scribe.providers.openai_compatible import Completion, InstructorOpenAIProvider


class InstructorAnthropicProvider(InstructorOpenAIProvider):
    """Anthropic adapter with the same normalized provider response contract."""

    def __init__(
        self,
        *,
        model: str,
        capabilities: ModelCapabilities,
        api_key: str | None = None,
        completion: Completion | None = None,
    ) -> None:
        if capabilities.provider != "anthropic":
            raise ValueError("capability row provider must identify Anthropic")
        if "seed" in capabilities.supported_generation_settings:
            raise ValueError("Anthropic capability rows must not advertise seed")
        super().__init__(
            model=model,
            api_key=api_key,
            capabilities=capabilities,
            completion=completion,
        )

    @property
    def adapter_identity(self) -> str:
        return "survey-scribe/instructor-anthropic/v1"

    @property
    def _dependency_extra(self) -> Literal["openai", "anthropic"]:
        return "anthropic"

    def _load_sdk_completion(self) -> Completion:
        anthropic = import_module("anthropic")
        instructor = import_module("instructor")
        client_kwargs: dict[str, object] = {"max_retries": 0}
        if self._api_key is not None:
            client_kwargs["api_key"] = self._api_key
        client = anthropic.AsyncAnthropic(**client_kwargs)
        self._client = client
        patched = instructor.from_anthropic(client, mode=instructor.Mode.ANTHROPIC_TOOLS)

        async def complete(**kwargs: object) -> object:
            generation = cast(GenerationConfig, kwargs["generation"])
            messages = cast(tuple[ProviderMessage, ...], kwargs["messages"])
            response_model = cast(type[BaseModel], kwargs["response_model"])
            request: dict[str, object] = {
                "model": kwargs["model"],
                "messages": [
                    {"role": message.role, "content": message.content}
                    for message in messages
                    if message.role != "system"
                ],
                "response_model": response_model,
                "max_retries": 0,
                "temperature": generation.temperature,
                "max_tokens": generation.max_output_tokens,
            }
            system = "\n\n".join(
                message.content for message in messages if message.role == "system"
            )
            if system:
                request["system"] = system
            output, response = await patched.messages.create_with_completion(**request)
            usage = getattr(response, "usage", None)
            input_tokens = getattr(usage, "input_tokens", 0) if usage is not None else 0
            output_tokens = getattr(usage, "output_tokens", 0) if usage is not None else 0
            return output, {
                "finish_reason": getattr(response, "stop_reason", None),
                "response_id": getattr(response, "id", None),
                "usage": (
                    {
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "total_tokens": input_tokens + output_tokens,
                    }
                    if usage is not None
                    else None
                ),
            }

        return complete


__all__ = ["InstructorAnthropicProvider"]
