"""Azure, Anthropic, and named OpenAI-compatible adapter contracts."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ConfigDict

from survey_scribe.config import GenerationConfig, RetryConfig
from survey_scribe.providers import anthropic as anthropic_module
from survey_scribe.providers import azure as azure_module
from survey_scribe.providers.anthropic import InstructorAnthropicProvider
from survey_scribe.providers.azure import AzureOpenAIProvider
from survey_scribe.providers.base import (
    ConcurrencyLimiter,
    ProviderAuthenticationError,
    ProviderMessage,
    ProviderRateLimitError,
    ProviderTransportError,
)
from survey_scribe.providers.capabilities import CapabilityEvidence, ModelCapabilities
from survey_scribe.providers.openai_compatible import (
    InstructorOpenAIProvider,
    OpenAICompatiblePreset,
)

pytestmark = pytest.mark.allow_hosts(["127.0.0.1", "::1"])


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: int


def _provider_traceback_locals(error: BaseException) -> list[str]:
    values: list[str] = []
    traceback = error.__traceback__
    while traceback is not None:
        filename = traceback.tb_frame.f_code.co_filename.replace("\\", "/")
        if "/src/survey_scribe/providers/" in f"/{filename}":
            values.append(repr(traceback.tb_frame.f_locals))
        traceback = traceback.tb_next
    return values


def _capabilities(
    provider: str,
    model: str,
    *,
    settings: frozenset[str] | None = None,
) -> ModelCapabilities:
    return ModelCapabilities(
        provider=provider,
        model=model,
        structured_output=True,
        strict_schema=True,
        max_input_tokens=32_768,
        max_output_tokens=4_096,
        supported_generation_settings=(
            settings
            if settings is not None
            else frozenset({"temperature", "max_output_tokens", "seed"})
        ),
        evidence=CapabilityEvidence.configuration_only,
        tested_sdk_version="contract-fixture",
    )


async def _generate(provider: object) -> Answer:
    response = await provider.generate(  # type: ignore[attr-defined]
        messages=(ProviderMessage(role="user", content="questionnaire"),),
        response_model=Answer,
        generation=GenerationConfig(),
        retry=RetryConfig(max_attempts=1),
        limiter=ConcurrencyLimiter(1),
    )
    return response.output


def _azure_provider(**changes: object) -> AzureOpenAIProvider:
    values: dict[str, object] = {
        "deployment": "deployment-a",
        "azure_endpoint": "https://example.openai.azure.com",
        "api_version": "2025-01-01-preview",
        "capabilities": _capabilities("azure_openai", "deployment-a"),
        "completion": lambda **_kwargs: Answer(value=1),
    }
    values.update(changes)
    return AzureOpenAIProvider(**values)  # type: ignore[arg-type]


def test_openai_compatible_presets_set_only_reviewed_endpoints_and_headers() -> None:
    openai = InstructorOpenAIProvider.from_preset(
        OpenAICompatiblePreset.openai,
        model="configured-model",
        api_key="not-a-real-key",
        capabilities=_capabilities("openai", "configured-model"),
    )
    assert openai.base_url == "https://api.openai.com/v1"

    openrouter = InstructorOpenAIProvider.from_preset(
        OpenAICompatiblePreset.openrouter,
        model="configured-model",
        api_key="not-a-real-key",
        capabilities=_capabilities("openrouter", "configured-model"),
        default_headers={"HTTP-Referer": "https://example.test", "X-Title": "Survey Scribe"},
    )
    assert openrouter.base_url == "https://openrouter.ai/api/v1"

    vercel = InstructorOpenAIProvider.from_preset(
        OpenAICompatiblePreset.vercel,
        model="configured-model",
        api_key="not-a-real-key",
        capabilities=_capabilities("vercel", "configured-model"),
    )
    assert vercel.base_url == "https://ai-gateway.vercel.sh/v1"

    custom = InstructorOpenAIProvider.from_preset(
        OpenAICompatiblePreset.custom,
        model="configured-model",
        api_key="not-a-real-key",
        base_url="https://gateway.example/v1",
        capabilities=_capabilities("custom", "configured-model"),
    )
    assert custom.base_url == "https://gateway.example/v1"

    with pytest.raises(ValueError, match="header"):
        InstructorOpenAIProvider.from_preset(
            OpenAICompatiblePreset.openrouter,
            model="configured-model",
            capabilities=_capabilities("openrouter", "configured-model"),
            default_headers={"Authorization": "private"},
        )
    with pytest.raises(ValueError, match="base_url"):
        InstructorOpenAIProvider.from_preset(
            OpenAICompatiblePreset.custom,
            model="configured-model",
            capabilities=_capabilities("custom", "configured-model"),
        )
    with pytest.raises(ValueError, match="HTTPS"):
        InstructorOpenAIProvider.from_preset(
            OpenAICompatiblePreset.custom,
            model="configured-model",
            base_url="http://gateway.example/v1",
            capabilities=_capabilities("custom", "configured-model"),
        )


@pytest.mark.asyncio
async def test_azure_adapter_passes_refreshable_token_callback_lazily(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_kwargs: dict[str, object] = {}
    request_kwargs: dict[str, object] = {}

    class FakeAsyncAzureOpenAI:
        def __init__(self, **kwargs: object) -> None:
            client_kwargs.update(kwargs)

    class FakeCompletions:
        async def create_with_completion(self, **kwargs: object) -> tuple[Answer, object]:
            request_kwargs.update(kwargs)
            return Answer(value=3), SimpleNamespace(choices=[], usage=None, id="azure-response")

    patched = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    modules = {
        "openai": SimpleNamespace(AsyncAzureOpenAI=FakeAsyncAzureOpenAI),
        "instructor": SimpleNamespace(
            Mode=SimpleNamespace(TOOLS_STRICT=object()),
            from_openai=lambda _client, *, mode: patched,
        ),
    }
    monkeypatch.setattr(azure_module, "import_module", modules.__getitem__)
    issued = iter(("token-one", "token-two"))

    def callback() -> str:
        return next(issued)

    sensitive_calls = 0

    def sensitive_headers() -> dict[str, str]:
        nonlocal sensitive_calls
        sensitive_calls += 1
        return {"X-Synthetic-Aux-Key": "synthetic-request-secret"}

    provider = AzureOpenAIProvider(
        deployment="deployment-a",
        azure_endpoint="https://example.openai.azure.com",
        api_version="2025-01-01-preview",
        token_callback=callback,
        metadata_headers={"X-Synthetic-Route": "route-one"},
        sensitive_headers_callback=sensitive_headers,
        required_headers=("x-synthetic-route", "x-synthetic-aux-key"),
        capabilities=_capabilities("azure_openai", "deployment-a"),
    )

    assert sensitive_calls == 0
    assert "synthetic-request-secret" not in repr(provider)
    provider.inspect_schema(Answer)
    provider.estimate_tokens((ProviderMessage(role="user", content="questionnaire"),))
    assert sensitive_calls == 0
    assert await _generate(provider) == Answer(value=3)
    assert sensitive_calls == 1
    installed_callback = client_kwargs["azure_ad_token_provider"]
    assert callable(installed_callback)
    assert installed_callback() == "token-one"
    assert installed_callback() == "token-two"
    assert "api_key" not in client_kwargs
    assert "default_headers" not in client_kwargs
    assert client_kwargs["max_retries"] == 0
    assert request_kwargs["extra_headers"] == {
        "X-Synthetic-Route": "route-one",
        "X-Synthetic-Aux-Key": "synthetic-request-secret",
    }

    key_provider = AzureOpenAIProvider(
        deployment="deployment-a",
        azure_endpoint="https://example.openai.azure.com",
        api_version="2025-01-01-preview",
        api_key="not-a-real-key",
        capabilities=_capabilities("azure_openai", "deployment-a"),
        completion=lambda **_kwargs: Answer(value=4),
    )
    assert await _generate(key_provider) == Answer(value=4)

    with pytest.raises(ValueError, match="credential"):
        AzureOpenAIProvider(
            deployment="deployment-a",
            azure_endpoint="https://example.openai.azure.com",
            api_version="2025-01-01-preview",
            api_key="key",
            token_callback=lambda: "token",
            capabilities=_capabilities("azure_openai", "deployment-a"),
        )
    for changes, message in (
        ({"azure_endpoint": "http://invalid"}, "HTTPS"),
        ({"api_version": " "}, "must not be empty"),
        ({"capabilities": _capabilities("openai", "deployment-a")}, "identify Azure"),
    ):
        values: dict[str, object] = {
            "deployment": "deployment-a",
            "azure_endpoint": "https://example.openai.azure.com",
            "api_version": "2025-01-01-preview",
            "api_key": "key",
            "capabilities": _capabilities("azure_openai", "deployment-a"),
        }
        values.update(changes)
        with pytest.raises(ValueError, match=message):
            AzureOpenAIProvider(**values)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_azure_header_constructor_copies_metadata_and_freezes_requirements() -> None:
    metadata = {"X-Synthetic-Route": "route-one"}
    required = ["x-synthetic-route"]
    calls: list[dict[str, str]] = []

    def completion(**kwargs: object) -> Answer:
        calls.append(dict(kwargs["extra_headers"]))  # type: ignore[arg-type]
        return Answer(value=1)

    provider = _azure_provider(
        metadata_headers=metadata,
        required_headers=required,
        completion=completion,
    )

    metadata["X-Synthetic-Route"] = "route-two"
    required.append("X-Synthetic-Missing")
    assert await _generate(provider) == Answer(value=1)

    assert "route-two" not in repr(provider)
    assert calls == [{"X-Synthetic-Route": "route-one"}]


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://user:credential@example.test",  # pragma: allowlist secret
        "https://example.test/path#credential-fragment",
        "https://example.test/path?token=credential-query",
        "https://example.test/path?OcpApimSubscriptionKey=credential-query",
        "https://example.test/path?Ocp%2DApim%2DSubscription%2DKey=credential-query",
    ],
)
def test_azure_rejects_credential_bearing_endpoints_without_traceback_leaks(
    endpoint: str,
) -> None:
    with pytest.raises(ValueError) as error:
        _azure_provider(
            azure_endpoint=endpoint,
            api_key="credential-primary",  # pragma: allowlist secret
        )

    provider_frames = _provider_traceback_locals(error.value)

    assert provider_frames
    assert "credential" not in str(error.value).casefold()
    assert "credential-primary" not in repr(provider_frames)
    assert "credential-query" not in repr(provider_frames)


@pytest.mark.parametrize(
    ("metadata_headers", "message"),
    [
        ({"": "value"}, "names"),
        ({"not a token": "value"}, "names"),
        ({1: "value"}, "names"),
        ({"X-Synthetic": 1}, "values"),
        ({"X-Synthetic": ""}, "values"),
        ({"X-Synthetic": " leading"}, "values"),
        ({"X-Synthetic": "trailing "}, "values"),
        ({"X-Synthetic": "non-ascii-\N{LATIN SMALL LETTER E WITH ACUTE}"}, "values"),
        ({"X-Synthetic": "control\N{DELETE}"}, "values"),
        ({"X-Synthetic": "one", "x-synthetic": "two"}, "unique"),
        (
            {"X-Synthetic-Secret": "value"},  # pragma: allowlist secret
            "sensitive_headers_callback",
        ),
    ],
)
def test_azure_constructor_rejects_invalid_static_headers_with_safe_messages(
    metadata_headers: object,
    message: str,
) -> None:
    marker = "synthetic-private-marker"
    if isinstance(metadata_headers, dict) and len(metadata_headers) == 1:
        name = next(iter(metadata_headers))
        if isinstance(name, str) and metadata_headers[name] == "value":
            metadata_headers[name] = marker

    with pytest.raises(ValueError, match=message) as error:
        _azure_provider(metadata_headers=metadata_headers)

    assert marker not in str(error.value)


def test_azure_static_header_failure_clears_provider_traceback_locals() -> None:
    with pytest.raises(ValueError) as error:
        _azure_provider(
            api_key="synthetic-primary-value",  # pragma: allowlist secret
            metadata_headers={
                "X-Synthetic-Secret": "synthetic-static-secret"  # pragma: allowlist secret
            },
        )

    provider_frames = _provider_traceback_locals(error.value)

    assert provider_frames
    assert "synthetic-primary-value" not in repr(provider_frames)
    assert "synthetic-static-secret" not in repr(provider_frames)


@pytest.mark.parametrize("control", [*(chr(code) for code in range(32)), chr(127)])
def test_azure_constructor_rejects_every_ascii_control_in_header_values(control: str) -> None:
    with pytest.raises(ValueError, match="values"):
        _azure_provider(metadata_headers={"X-Synthetic": f"before{control}after"})


@pytest.mark.parametrize(
    "required_headers",
    [
        "X-Synthetic",
        b"X-Synthetic",
        7,
        [""],
        [1],
        ["X-Synthetic", "x-synthetic"],
    ],
)
def test_azure_constructor_rejects_invalid_required_header_collections(
    required_headers: object,
) -> None:
    with pytest.raises((TypeError, ValueError), match="required"):
        _azure_provider(required_headers=required_headers)


_RESERVED_HEADERS = (
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
)


@pytest.mark.asyncio
@pytest.mark.parametrize("reserved", _RESERVED_HEADERS)
async def test_azure_rejects_reserved_names_in_all_header_channels(reserved: str) -> None:
    mixed_case = reserved.upper()
    with pytest.raises(ValueError, match="reserved"):
        _azure_provider(metadata_headers={mixed_case: "value"})
    with pytest.raises(ValueError, match="reserved"):
        _azure_provider(required_headers=[mixed_case])

    provider = _azure_provider(sensitive_headers_callback=lambda: {mixed_case: "value"})
    with pytest.raises(ProviderAuthenticationError, match="authentication failed"):
        await _generate(provider)


@pytest.mark.asyncio
async def test_azure_resolves_fresh_sensitive_headers_for_each_package_attempt() -> None:
    metadata = {"X-Synthetic-Route": "route-one"}
    required = ["x-synthetic-route", "X-Synthetic-Aux-Key"]
    issued = iter(("synthetic-value-one", "synthetic-value-two"))
    calls: list[dict[str, str]] = []

    def sensitive_headers() -> dict[str, str]:
        return {"X-Synthetic-Aux-Key": next(issued)}

    async def completion(**kwargs: object) -> Answer:
        calls.append(dict(kwargs["extra_headers"]))  # type: ignore[arg-type]
        if len(calls) == 1:
            raise ProviderRateLimitError()
        return Answer(value=8)

    provider = _azure_provider(
        metadata_headers=metadata,
        sensitive_headers_callback=sensitive_headers,
        required_headers=required,
        completion=completion,
    )
    metadata["X-Synthetic-Route"] = "mutated-route"
    required.append("X-Synthetic-Never-Required")

    response = await provider.generate(
        messages=(ProviderMessage(role="user", content="questionnaire"),),
        response_model=Answer,
        generation=GenerationConfig(),
        retry=RetryConfig(max_attempts=2, initial_delay_seconds=0, max_delay_seconds=0),
        limiter=ConcurrencyLimiter(1),
    )

    assert response.output == Answer(value=8)
    assert response.transport_attempts == 2
    assert calls == [
        {
            "X-Synthetic-Route": "route-one",
            "X-Synthetic-Aux-Key": "synthetic-value-one",
        },
        {
            "X-Synthetic-Route": "route-one",
            "X-Synthetic-Aux-Key": "synthetic-value-two",
        },
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "callback",
    [
        lambda: "not-a-mapping",
        lambda: {"X-Synthetic": "one", "x-synthetic": "two"},
        lambda: {"X-Synthetic": "bad\nvalue"},
    ],
)
async def test_azure_dynamic_header_validation_is_safe_and_nonretryable(
    callback: object,
) -> None:
    completion_calls = 0

    def completion(**_kwargs: object) -> Answer:
        nonlocal completion_calls
        completion_calls += 1
        return Answer(value=1)

    provider = _azure_provider(
        sensitive_headers_callback=callback,
        completion=completion,
    )

    with pytest.raises(ProviderAuthenticationError) as error:
        await provider.generate(
            messages=(ProviderMessage(role="user", content="questionnaire"),),
            response_model=Answer,
            generation=GenerationConfig(),
            retry=RetryConfig(max_attempts=3, initial_delay_seconds=0, max_delay_seconds=0),
            limiter=ConcurrencyLimiter(1),
        )

    assert completion_calls == 0
    assert error.value.__cause__ is None
    assert error.value.__context__ is None


def test_azure_rejects_async_sensitive_header_callback_during_construction() -> None:
    async def callback() -> dict[str, str]:
        return {"X-Synthetic-Aux-Key": "value"}

    with pytest.raises(TypeError, match="synchronous"):
        _azure_provider(sensitive_headers_callback=callback)


@pytest.mark.asyncio
async def test_azure_closes_awaitable_sensitive_header_callback_result() -> None:
    class AwaitableHeaders:
        def __init__(self) -> None:
            self.closed = False

        def __await__(self):  # type: ignore[no-untyped-def]
            yield
            return {"X-Synthetic-Aux-Key": "value"}

        def close(self) -> None:
            self.closed = True

    result = AwaitableHeaders()
    provider = _azure_provider(sensitive_headers_callback=lambda: result)  # type: ignore[arg-type]

    with pytest.raises(ProviderAuthenticationError):
        await _generate(provider)

    assert result.closed is True


@pytest.mark.asyncio
async def test_azure_rejects_case_insensitive_cross_channel_collisions() -> None:
    provider = _azure_provider(
        metadata_headers={"X-Synthetic-Route": "public-route"},
        sensitive_headers_callback=lambda: {"x-synthetic-route": "synthetic-private-value"},
    )

    with pytest.raises(ProviderAuthenticationError) as error:
        await _generate(provider)

    assert "synthetic-private-value" not in str(error.value)
    assert error.value.__cause__ is None
    assert error.value.__context__ is None


@pytest.mark.asyncio
async def test_azure_callback_failure_detaches_secret_exception_and_traceback_locals() -> None:
    callback_calls = 0
    completion_calls = 0

    def failing_callback() -> dict[str, str]:
        nonlocal callback_calls
        callback_calls += 1
        raise RuntimeError("synthetic-callback-secret")

    def completion(**_kwargs: object) -> Answer:
        nonlocal completion_calls
        completion_calls += 1
        return Answer(value=1)

    provider = _azure_provider(
        sensitive_headers_callback=failing_callback,
        completion=completion,
    )

    with pytest.raises(ProviderAuthenticationError) as error:
        await provider.generate(
            messages=(ProviderMessage(role="user", content="questionnaire"),),
            response_model=Answer,
            generation=GenerationConfig(),
            retry=RetryConfig(max_attempts=3, initial_delay_seconds=0, max_delay_seconds=0),
            limiter=ConcurrencyLimiter(1),
        )

    provider_frames = _provider_traceback_locals(error.value)

    assert callback_calls == 1
    assert completion_calls == 0
    assert error.value.__cause__ is None
    assert error.value.__context__ is None
    assert not hasattr(error.value, "request")
    assert not hasattr(error.value, "response")
    assert "synthetic-callback-secret" not in repr(provider_frames)


@pytest.mark.asyncio
async def test_azure_missing_required_dynamic_header_fails_before_completion() -> None:
    completion_calls = 0

    def completion(**_kwargs: object) -> Answer:
        nonlocal completion_calls
        completion_calls += 1
        return Answer(value=1)

    provider = _azure_provider(
        sensitive_headers_callback=lambda: {"X-Synthetic-Other": "value"},
        required_headers=("X-Synthetic-Required",),
        completion=completion,
    )

    with pytest.raises(ProviderAuthenticationError, match="authentication failed"):
        await _generate(provider)
    assert completion_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_type",
    [asyncio.CancelledError, KeyboardInterrupt, SystemExit],
)
async def test_azure_sensitive_callback_propagates_process_control_errors(
    error_type: type[BaseException],
) -> None:
    def callback() -> dict[str, str]:
        raise error_type

    provider = _azure_provider(sensitive_headers_callback=callback)

    with pytest.raises(error_type):
        await _generate(provider)


@pytest.mark.asyncio
async def test_azure_sdk_failure_drops_request_headers_and_raw_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeAsyncAzureOpenAI:
        def __init__(self, **_kwargs: object) -> None:
            pass

    class FailingCompletions:
        async def create_with_completion(self, **_kwargs: object) -> tuple[Answer, object]:
            raise RuntimeError("503 synthetic-sdk-secret")

    patched = SimpleNamespace(chat=SimpleNamespace(completions=FailingCompletions()))
    modules = {
        "openai": SimpleNamespace(AsyncAzureOpenAI=FakeAsyncAzureOpenAI),
        "instructor": SimpleNamespace(
            Mode=SimpleNamespace(TOOLS_STRICT=object()),
            from_openai=lambda _client, *, mode: patched,
        ),
    }
    monkeypatch.setattr(azure_module, "import_module", modules.__getitem__)
    provider = AzureOpenAIProvider(
        deployment="deployment-a",
        azure_endpoint="https://example.openai.azure.com",
        api_version="2025-01-01-preview",
        api_key="not-a-real-key",
        metadata_headers={"X-Synthetic-Route": "route-one"},
        sensitive_headers_callback=lambda: {"X-Synthetic-Aux-Key": "synthetic-request-secret"},
        capabilities=_capabilities("azure_openai", "deployment-a"),
    )

    with pytest.raises(ProviderTransportError) as error:
        await _generate(provider)

    provider_frames = _provider_traceback_locals(error.value)

    assert error.value.__cause__ is None
    assert error.value.__context__ is None
    assert not hasattr(error.value, "request")
    assert not hasattr(error.value, "response")
    assert "synthetic-request-secret" not in repr(provider_frames)
    assert "synthetic-sdk-secret" not in repr(provider_frames)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [ProviderRateLimitError(), ProviderTransportError(retryable=False), asyncio.CancelledError()],
)
async def test_azure_detaches_secret_bearing_completion_failures(
    failure: BaseException,
) -> None:
    async def completion(**kwargs: object) -> Answer:
        assert kwargs["extra_headers"]
        raise failure

    provider = _azure_provider(
        sensitive_headers_callback=lambda: {"X-Synthetic-Aux-Key": "synthetic-completion-secret"},
        completion=completion,
    )

    with pytest.raises(type(failure)) as error:
        await _generate(provider)

    traceback_values: list[str] = []
    traceback = error.value.__traceback__
    while traceback is not None:
        traceback_values.append(repr(traceback.tb_frame.f_locals))
        traceback = traceback.tb_next

    assert "synthetic-completion-secret" not in repr(traceback_values)
    assert error.value.__cause__ is None
    assert error.value.__context__ is None


@pytest.mark.asyncio
async def test_azure_sdk_constructor_failure_is_detached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingAsyncAzureOpenAI:
        def __init__(self, **kwargs: object) -> None:
            assert kwargs["api_key"] == "synthetic-constructor-secret"  # pragma: allowlist secret
            raise RuntimeError("synthetic-constructor-secret")

    modules = {
        "openai": SimpleNamespace(AsyncAzureOpenAI=FailingAsyncAzureOpenAI),
        "instructor": SimpleNamespace(),
    }
    monkeypatch.setattr(azure_module, "import_module", modules.__getitem__)
    provider = AzureOpenAIProvider(
        deployment="deployment-a",
        azure_endpoint="https://example.openai.azure.com",
        api_version="2025-01-01-preview",
        api_key="synthetic-constructor-secret",  # pragma: allowlist secret
        capabilities=_capabilities("azure_openai", "deployment-a"),
    )

    with pytest.raises(ProviderTransportError) as error:
        await _generate(provider)

    traceback_values: list[str] = []
    traceback = error.value.__traceback__
    while traceback is not None:
        traceback_values.append(repr(traceback.tb_frame.f_locals))
        traceback = traceback.tb_next

    assert "synthetic-constructor-secret" not in repr(traceback_values)
    assert error.value.__cause__ is None
    assert error.value.__context__ is None


@pytest.mark.asyncio
async def test_direct_foundry_and_gateway_compositions_share_the_azure_adapter() -> None:
    direct_calls: list[dict[str, object]] = []
    gateway_calls: list[dict[str, object]] = []
    token_calls = 0

    async def direct_completion(**kwargs: object) -> tuple[Answer, object]:
        direct_calls.append(kwargs)
        return Answer(value=21), {
            "finish_reason": "stop",
            "response_id": "direct-response",
            "usage": {"input_tokens": 5, "output_tokens": 1, "total_tokens": 6},
        }

    async def gateway_completion(**kwargs: object) -> tuple[Answer, object]:
        gateway_calls.append(kwargs)
        return Answer(value=22), {
            "finish_reason": "stop",
            "response_id": "gateway-response",
            "usage": {"input_tokens": 7, "output_tokens": 2, "total_tokens": 9},
        }

    def token_callback() -> str:
        nonlocal token_calls
        token_calls += 1
        return "synthetic-token"

    direct = _azure_provider(api_key="not-a-real-key", completion=direct_completion)
    gateway = _azure_provider(
        token_callback=token_callback,
        metadata_headers={"X-Synthetic-Route": "questionnaire"},
        sensitive_headers_callback=lambda: {"X-Synthetic-Aux-Key": "synthetic-aux-value"},
        required_headers=("X-Synthetic-Route", "X-Synthetic-Aux-Key"),
        completion=gateway_completion,
    )
    direct_response = await direct.generate(
        messages=(ProviderMessage(role="user", content="questionnaire"),),
        response_model=Answer,
        generation=GenerationConfig(),
        retry=RetryConfig(max_attempts=1),
        limiter=ConcurrencyLimiter(1),
    )
    gateway_response = await gateway.generate(
        messages=(ProviderMessage(role="user", content="questionnaire"),),
        response_model=Answer,
        generation=GenerationConfig(),
        retry=RetryConfig(max_attempts=1),
        limiter=ConcurrencyLimiter(1),
    )
    await direct.aclose()
    await gateway.aclose()

    assert type(direct) is type(gateway) is AzureOpenAIProvider
    assert direct_response.output == Answer(value=21)
    assert gateway_response.output == Answer(value=22)
    assert direct_response.usage is not None and direct_response.usage.total_tokens == 6
    assert gateway_response.usage is not None and gateway_response.usage.total_tokens == 9
    assert direct_response.transport_attempts == gateway_response.transport_attempts == 1
    assert "extra_headers" not in direct_calls[0]
    assert gateway_calls[0]["extra_headers"] == {
        "X-Synthetic-Route": "questionnaire",
        "X-Synthetic-Aux-Key": "synthetic-aux-value",
    }
    assert token_calls == 0


@pytest.mark.asyncio
async def test_anthropic_adapter_is_lazy_and_normalizes_completion_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_kwargs: dict[str, object] = {}
    request_kwargs: dict[str, object] = {}

    class FakeAsyncAnthropic:
        def __init__(self, **kwargs: object) -> None:
            client_kwargs.update(kwargs)

    class FakeMessages:
        async def create_with_completion(self, **kwargs: object) -> tuple[Answer, object]:
            request_kwargs.update(kwargs)
            return Answer(value=5), SimpleNamespace(
                stop_reason="end_turn",
                id="anthropic-response",
                usage=SimpleNamespace(input_tokens=9, output_tokens=2),
            )

    patched = SimpleNamespace(messages=FakeMessages())
    modules = {
        "anthropic": SimpleNamespace(AsyncAnthropic=FakeAsyncAnthropic),
        "instructor": SimpleNamespace(
            Mode=SimpleNamespace(ANTHROPIC_TOOLS=object()),
            from_anthropic=lambda _client, *, mode: patched,
        ),
    }
    monkeypatch.setattr(anthropic_module, "import_module", modules.__getitem__)
    provider = InstructorAnthropicProvider(
        model="claude-configured",
        api_key="not-a-real-key",
        capabilities=_capabilities(
            "anthropic",
            "claude-configured",
            settings=frozenset({"temperature", "max_output_tokens"}),
        ),
    )

    assert await _generate(provider) == Answer(value=5)
    assert client_kwargs == {"api_key": "not-a-real-key", "max_retries": 0}
    assert request_kwargs["max_retries"] == 0
    assert request_kwargs["max_tokens"] == 4096

    with pytest.raises(ValueError, match="must not advertise seed"):
        InstructorAnthropicProvider(
            model="claude-configured",
            capabilities=_capabilities("anthropic", "claude-configured"),
        )
    with pytest.raises(ValueError, match="identify Anthropic"):
        InstructorAnthropicProvider(
            model="claude-configured",
            capabilities=_capabilities(
                "openai",
                "claude-configured",
                settings=frozenset({"temperature", "max_output_tokens"}),
            ),
        )
