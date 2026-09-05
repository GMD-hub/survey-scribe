"""Installed Azure OpenAI and Instructor request-header contract."""

from __future__ import annotations

import json
import socket
from typing import Any

import httpx
import openai
import pytest
from pydantic import BaseModel, ConfigDict

from survey_scribe.config import GenerationConfig, RetryConfig
from survey_scribe.providers.azure import AzureOpenAIProvider
from survey_scribe.providers.base import ConcurrencyLimiter, ProviderMessage
from survey_scribe.providers.capabilities import CapabilityEvidence, ModelCapabilities

pytestmark = pytest.mark.allow_hosts(["127.0.0.1", "::1"])


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: int


def _capabilities() -> ModelCapabilities:
    return ModelCapabilities(
        provider="azure_openai",
        model="deployment-a",
        structured_output=True,
        strict_schema=True,
        max_input_tokens=32_768,
        max_output_tokens=4_096,
        supported_generation_settings=frozenset({"temperature", "max_output_tokens", "seed"}),
        evidence=CapabilityEvidence.configuration_only,
        tested_sdk_version="1.99.9",
    )


async def _successful_tool_response(request: httpx.Request, *, value: int) -> httpx.Response:
    body = json.loads(await request.aread())
    tool_name = body["tools"][0]["function"]["name"]
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-contract",
            "object": "chat.completion",
            "created": 0,
            "model": "deployment-a",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-contract",
                                "type": "function",
                                "function": {
                                    "name": tool_name,
                                    "arguments": json.dumps({"value": value}),
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {
                "prompt_tokens": 9,
                "completion_tokens": 2,
                "total_tokens": 11,
            },
        },
    )


def test_provider_contract_network_guard_blocks_dns_and_connections() -> None:
    with pytest.raises(RuntimeError, match="network access denied"):
        socket.getaddrinfo("example.test", 443)
    with socket.socket() as connection:
        with pytest.raises(RuntimeError):
            connection.connect(("192.0.2.1", 443))
        with pytest.raises(RuntimeError, match="network access denied"):
            connection.connect_ex(("127.0.0.1", 443))
        with pytest.raises(RuntimeError, match="network access denied"):
            connection.sendto(b"blocked", ("127.0.0.1", 443))


@pytest.mark.asyncio
async def test_installed_azure_sdk_forwards_request_headers_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    constructor_kwargs: dict[str, object] = {}
    request_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        body = json.loads(await request.aread())
        request_count += 1
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        tool_name = body["tools"][0]["function"]["name"]
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-contract",
                "object": "chat.completion",
                "created": 0,
                "model": "deployment-a",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-contract",
                                    "type": "function",
                                    "function": {
                                        "name": tool_name,
                                        "arguments": '{"value":3}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {
                    "prompt_tokens": 9,
                    "completion_tokens": 2,
                    "total_tokens": 11,
                },
            },
        )

    real_constructor = openai.AsyncAzureOpenAI
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as injected_client:

        def wrapped_constructor(**kwargs: Any) -> openai.AsyncAzureOpenAI:
            constructor_kwargs.update(kwargs)
            return real_constructor(**kwargs, http_client=injected_client)

        monkeypatch.setattr(openai, "AsyncAzureOpenAI", wrapped_constructor)
        provider = AzureOpenAIProvider(
            deployment="deployment-a",
            azure_endpoint="https://example.openai.azure.com",
            api_version="2025-01-01-preview",
            api_key="not-a-real-key",  # pragma: allowlist secret
            metadata_headers={"X-Synthetic-Route": "route-one"},
            sensitive_headers_callback=lambda: {"X-Synthetic-Aux-Key": "synthetic-request-secret"},
            required_headers=("x-synthetic-route", "x-synthetic-aux-key"),
            capabilities=_capabilities(),
        )
        try:
            response = await provider.generate(
                messages=(ProviderMessage(role="user", content="questionnaire"),),
                response_model=Answer,
                generation=GenerationConfig(),
                retry=RetryConfig(max_attempts=1),
                limiter=ConcurrencyLimiter(1),
            )
        finally:
            await provider.aclose()

        assert injected_client.is_closed

    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert isinstance(response.output, Answer)
    assert response.output.value == 3
    assert response.transport_attempts == 1
    assert response.usage is not None and response.usage.total_tokens == 11
    assert captured["url"] == (
        "https://example.openai.azure.com/openai/deployments/deployment-a/"
        "chat/completions?api-version=2025-01-01-preview"
    )
    assert headers["x-synthetic-route"] == "route-one"
    assert headers["x-synthetic-aux-key"] == "synthetic-request-secret"
    assert request_count == 1
    assert constructor_kwargs["max_retries"] == 0


@pytest.mark.asyncio
async def test_installed_azure_sdk_combines_token_provider_and_gateway_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_headers: dict[str, str] = {}
    token_calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.update(dict(request.headers))
        return await _successful_tool_response(request, value=4)

    def token_callback() -> str:
        nonlocal token_calls
        token_calls += 1
        return "synthetic-primary-token"  # pragma: allowlist secret

    real_constructor = openai.AsyncAzureOpenAI
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as injected_client:

        def wrapped_constructor(**kwargs: Any) -> openai.AsyncAzureOpenAI:
            return real_constructor(**kwargs, http_client=injected_client)

        monkeypatch.setattr(openai, "AsyncAzureOpenAI", wrapped_constructor)
        provider = AzureOpenAIProvider(
            deployment="deployment-a",
            azure_endpoint="https://example.openai.azure.com",
            api_version="2025-01-01-preview",
            token_callback=token_callback,
            metadata_headers={"X-Synthetic-Route": "route-one"},
            sensitive_headers_callback=lambda: {"X-Synthetic-Aux-Key": "aux-value"},
            required_headers=("X-Synthetic-Route", "X-Synthetic-Aux-Key"),
            capabilities=_capabilities(),
        )
        try:
            response = await provider.generate(
                messages=(ProviderMessage(role="user", content="questionnaire"),),
                response_model=Answer,
                generation=GenerationConfig(),
                retry=RetryConfig(max_attempts=1),
                limiter=ConcurrencyLimiter(1),
            )
        finally:
            await provider.aclose()

    assert response.output.value == 4
    assert token_calls == 1
    assert captured_headers["authorization"] == "Bearer synthetic-primary-token"
    assert "api-key" not in captured_headers
    assert captured_headers["x-synthetic-route"] == "route-one"
    assert captured_headers["x-synthetic-aux-key"] == "aux-value"


@pytest.mark.asyncio
async def test_installed_sdk_defers_retries_to_package_and_refreshes_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_headers: list[dict[str, str]] = []
    issued = iter(("aux-attempt-one", "aux-attempt-two"))
    constructor_kwargs: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.append(dict(request.headers))
        if len(captured_headers) == 1:
            return httpx.Response(
                503,
                json={"error": {"message": "temporary", "type": "server_error"}},
            )
        return await _successful_tool_response(request, value=5)

    real_constructor = openai.AsyncAzureOpenAI
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as injected_client:

        def wrapped_constructor(**kwargs: Any) -> openai.AsyncAzureOpenAI:
            constructor_kwargs.update(kwargs)
            return real_constructor(**kwargs, http_client=injected_client)

        monkeypatch.setattr(openai, "AsyncAzureOpenAI", wrapped_constructor)
        provider = AzureOpenAIProvider(
            deployment="deployment-a",
            azure_endpoint="https://example.openai.azure.com",
            api_version="2025-01-01-preview",
            api_key="not-a-real-key",  # pragma: allowlist secret
            sensitive_headers_callback=lambda: {"X-Synthetic-Aux-Key": next(issued)},
            capabilities=_capabilities(),
        )
        try:
            response = await provider.generate(
                messages=(ProviderMessage(role="user", content="questionnaire"),),
                response_model=Answer,
                generation=GenerationConfig(),
                retry=RetryConfig(
                    max_attempts=2,
                    initial_delay_seconds=0,
                    max_delay_seconds=0,
                ),
                limiter=ConcurrencyLimiter(1),
            )
        finally:
            await provider.aclose()

    assert response.output.value == 5
    assert response.transport_attempts == 2
    assert constructor_kwargs["max_retries"] == 0
    assert len(captured_headers) == 2
    assert [headers["x-synthetic-aux-key"] for headers in captured_headers] == [
        "aux-attempt-one",
        "aux-attempt-two",
    ]
