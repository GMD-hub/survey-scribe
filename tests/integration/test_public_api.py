"""Integration coverage for the public facade and custom extraction pipelines."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, SecretStr

from survey_scribe import (
    ChunkedStructuredPipeline,
    ClientClosedError,
    ConfigurationError,
    ExtractionResult,
    ProgrammerInputError,
    ResultStatus,
    RunningEventLoopError,
    SourceBundle,
    StructuredPipeline,
    SurveyScribe,
    SurveyScribeConfig,
)
from survey_scribe.client import (
    _gather_conversions,
    _provider_from_config,
    convert_source,
    run_sync,
)
from survey_scribe.models.svis import DataType, SurveyVariable
from survey_scribe.pipeline import BlockExtraction, ExtractedMetadata, ExtractedVariable
from survey_scribe.providers.anthropic import InstructorAnthropicProvider
from survey_scribe.providers.azure import AzureOpenAIProvider
from survey_scribe.providers.base import ConcurrencyLimiter, ProviderResponse
from survey_scribe.providers.capabilities import CapabilityEvidence, ModelCapabilities
from survey_scribe.providers.openai_compatible import InstructorOpenAIProvider
from survey_scribe.providers.testing import DeterministicFakeProvider, FakeRequest
from survey_scribe.results import FailedBlock
from survey_scribe.sources import (
    ResolvedSource,
    SourceBlock,
    SourceDocument,
    SourceInputError,
    SourceLimits,
    SourceProvenance,
    SourceRegistry,
)


class TextAdapter:
    """Small source adapter used to exercise registry boundaries."""

    def convert(self, source: ResolvedSource, *, limits: SourceLimits) -> SourceDocument:
        del limits
        text = source.primary.read_text(encoding="utf-8")
        return _document(source.primary.name, (text,))


class BrokenAdapter:
    def convert(self, source: ResolvedSource, *, limits: SourceLimits) -> SourceDocument:
        del source, limits
        raise RuntimeError("private source failure")


class LineAdapter:
    def convert(self, source: ResolvedSource, *, limits: SourceLimits) -> SourceDocument:
        del limits
        return _document(
            source.primary.name,
            tuple(source.primary.read_text(encoding="utf-8").splitlines()),
        )


class Summary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    value: str


class Combined(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    values: tuple[str, ...]
    failed: tuple[str, ...]


class ClosingProvider(DeterministicFakeProvider):
    """Fake provider that records lifecycle delegation."""

    def __init__(self) -> None:
        super().__init__(
            capabilities=_capabilities(),
            responder=lambda _request: Summary(value="x"),
        )
        self.close_count = 0

    async def aclose(self) -> None:
        self.close_count += 1


class RetryingCloseProvider(ClosingProvider):
    """Fail the first cleanup call and succeed on retry."""

    async def aclose(self) -> None:
        self.close_count += 1
        if self.close_count == 1:
            raise RuntimeError("private cleanup failure")


def _capabilities(*, max_input_tokens: int = 200_000) -> ModelCapabilities:
    return ModelCapabilities(
        provider="fake",
        model="public-api-fake-v1",
        structured_output=True,
        strict_schema=True,
        max_input_tokens=max_input_tokens,
        max_output_tokens=8_192,
        supported_generation_settings=frozenset({"temperature", "max_output_tokens", "seed"}),
        evidence=CapabilityEvidence.verified,
        tested_sdk_version="fake-1",
    )


def _document(name: str, texts: tuple[str, ...]) -> SourceDocument:
    return SourceDocument(
        source_name=name,
        media_type="text/plain",
        blocks=tuple(
            SourceBlock(
                id=f"block-{index}",
                order=index,
                kind="text",
                text=text,
                provenance=SourceProvenance(source_name=name),
            )
            for index, text in enumerate(texts)
        ),
    )


def _chunk_id(request: FakeRequest) -> str:
    content = next(message.content for message in request.messages if message.role == "user")
    return content.split("CHUNK_ID: ", maxsplit=1)[1].splitlines()[0]


def _svis_provider() -> DeterministicFakeProvider:
    async def respond(request: FakeRequest) -> object:
        content = next(message.content for message in request.messages if message.role == "user")
        marker = "first" if "first" in content else "second"
        await asyncio.sleep(0.01 if marker == "first" else 0)
        if request.response_model is ExtractedMetadata:
            return ExtractedMetadata(
                survey_id=f"TST_2026_{marker.upper()}",
                country_code="TST",
                year=2026,
                survey_name=marker.title(),
            )
        block_ids = tuple(json.loads(content.split("SOURCE_BLOCK_IDS: ", 1)[1].splitlines()[0]))
        return BlockExtraction(
            block_id=_chunk_id(request),
            variables=(
                ExtractedVariable(
                    variable=SurveyVariable(
                        raw_name=marker,
                        data_type=DataType.text,
                        extraction_confidence=1.0,
                    ),
                    source_block_ids=(block_ids[0],),
                ),
            ),
        )

    return DeterministicFakeProvider(capabilities=_capabilities(), responder=respond)


def test_five_line_sync_use_and_bundle_acceptance(tmp_path: Path) -> None:
    source = tmp_path / "first.test"
    source.write_text("first", encoding="utf-8")
    provider = _svis_provider()
    client = SurveyScribe(provider, source_registry=SourceRegistry({".test": TextAdapter()}))
    result = client.convert(source)

    assert result.status is ResultStatus.success
    assert result.output is not None
    assert result.output.survey_id == "TST_2026_FIRST"
    bundle = SourceBundle(root=tmp_path, primary=Path("first.test"))
    assert client.convert(bundle).output is not None


@pytest.mark.asyncio
async def test_async_batch_preserves_order_and_one_global_ceiling(tmp_path: Path) -> None:
    sources = [tmp_path / "first.test", tmp_path / "second.test", tmp_path / "first-2.test"]
    for source, value in zip(sources, ("first", "second", "first"), strict=True):
        source.write_text(value, encoding="utf-8")
    provider = _svis_provider()
    client = SurveyScribe(
        provider,
        config=SurveyScribeConfig(max_concurrency=2),
        source_registry=SourceRegistry({".test": TextAdapter()}),
    )

    results = await client.aconvert_many(sources)

    assert [result.output.survey_id for result in results if result.output is not None] == [
        "TST_2026_FIRST",
        "TST_2026_SECOND",
        "TST_2026_FIRST",
    ]
    assert provider.peak_concurrency == 2


@pytest.mark.asyncio
async def test_sync_methods_reject_a_running_event_loop(tmp_path: Path) -> None:
    source = tmp_path / "first.test"
    source.write_text("first", encoding="utf-8")
    client = SurveyScribe(
        _svis_provider(), source_registry=SourceRegistry({".test": TextAdapter()})
    )

    with pytest.raises(RunningEventLoopError):
        client.convert(source)
    with pytest.raises(RunningEventLoopError):
        client.convert_many([source])
    with pytest.raises(RunningEventLoopError):
        client.close()
    await client.aclose()


@pytest.mark.asyncio
async def test_context_managers_close_once_and_closed_client_rejects_use(tmp_path: Path) -> None:
    provider = ClosingProvider()
    client = SurveyScribe(provider, source_registry=SourceRegistry({".test": TextAdapter()}))
    async with client as entered:
        assert entered is client
    await client.aclose()

    assert provider.close_count == 1
    with pytest.raises(ClientClosedError):
        await client.aconvert(tmp_path / "missing.test")


@pytest.mark.asyncio
async def test_failed_provider_cleanup_remains_retryable(tmp_path: Path) -> None:
    provider = RetryingCloseProvider()
    client = SurveyScribe(provider, source_registry=SourceRegistry({".test": TextAdapter()}))

    with pytest.raises(RuntimeError, match="cleanup"):
        await client.aclose()

    assert client._closed is False
    await client.aclose()
    await client.aclose()
    assert provider.close_count == 2
    source = tmp_path / "source.test"
    source.write_text("first", encoding="utf-8")
    with pytest.raises(ClientClosedError):
        await client.aconvert(source)


def test_sync_context_manager_closes_provider() -> None:
    provider = ClosingProvider()
    with SurveyScribe(provider) as client:
        assert client is not None
    client.close()
    assert provider.close_count == 1


def test_constructor_and_programmer_inputs_raise_typed_errors(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="model"):
        SurveyScribe()
    with pytest.raises(ProgrammerInputError, match="provider"):
        SurveyScribe(object())  # type: ignore[arg-type]
    client = SurveyScribe(
        _svis_provider(), source_registry=SourceRegistry({".test": TextAdapter()})
    )
    for invalid in (b"source.test", object(), "https://example.test/form.pdf"):
        with pytest.raises(SourceInputError):
            client.convert(invalid)  # type: ignore[arg-type]
    file_source = tmp_path / "file.test"
    with file_source.open("w", encoding="utf-8") as stream, pytest.raises(SourceInputError):
        client.convert(stream)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("keyword", "value", "message"),
    [
        ("config", object(), "config"),
        ("source_registry", object(), "source_registry"),
        ("source_limits", object(), "source_limits"),
        ("extraction_date", "2026-09-03", "extraction_date"),
        ("token_callback", object(), "token_callback"),
    ],
)
def test_constructor_rejects_invalid_typed_options(
    keyword: str, value: object, message: str
) -> None:
    arguments: dict[str, Any] = {keyword: value}

    with pytest.raises(ProgrammerInputError, match=message):
        SurveyScribe(provider="openai", model="model", api_key="test-key", **arguments)


def test_injected_provider_rejects_provider_configuration() -> None:
    with pytest.raises(ProgrammerInputError, match="injected provider"):
        SurveyScribe(_svis_provider(), model="other-model")


def test_from_config_builds_client_and_rejects_wrong_config_type(tmp_path: Path) -> None:
    config_path = tmp_path / "survey-scribe.toml"
    config_path.write_text(
        'config_version = 1\nprovider = "openai"\nmodel = "test-model"\n',
        encoding="utf-8",
    )

    client = SurveyScribe.from_config(
        config_path,
        config=SurveyScribeConfig(api_key=SecretStr("test-key")),
    )
    assert isinstance(client._provider, InstructorOpenAIProvider)
    client.close()
    with pytest.raises(ProgrammerInputError, match="config"):
        SurveyScribe.from_config(config=object())  # type: ignore[arg-type]


def test_provider_factory_selects_supported_adapters_and_rejects_bad_configuration() -> None:
    common = {"model": "test-model", "api_key": SecretStr("test-key")}
    assert isinstance(
        _provider_from_config(SurveyScribeConfig(provider="openai", **common)),
        InstructorOpenAIProvider,
    )
    assert isinstance(
        _provider_from_config(
            SurveyScribeConfig(provider="custom", base_url="https://gateway.example/v1", **common)
        ),
        InstructorOpenAIProvider,
    )
    assert isinstance(
        _provider_from_config(SurveyScribeConfig(provider="anthropic", **common)),
        InstructorAnthropicProvider,
    )
    assert isinstance(
        _provider_from_config(
            SurveyScribeConfig(
                provider="azure",
                base_url="https://resource.example",
                api_version="2026-01-01",
                **common,
            )
        ),
        AzureOpenAIProvider,
    )
    with pytest.raises(ConfigurationError, match="Custom"):
        _provider_from_config(SurveyScribeConfig(provider="custom", **common))
    with pytest.raises(ConfigurationError, match="Azure"):
        _provider_from_config(SurveyScribeConfig(provider="azure", **common))
    with pytest.raises(ConfigurationError, match="Unsupported"):
        _provider_from_config(SurveyScribeConfig(provider="unsupported", **common))
    with pytest.raises(ConfigurationError, match="credentials"):
        _provider_from_config(SurveyScribeConfig(provider="openai", model="test-model"))


def test_sdk_factory_maps_azure_bearer_token_to_token_provider() -> None:
    provider = _provider_from_config(
        SurveyScribeConfig(
            provider="azure",
            model="deployment",
            base_url="https://resource.example",
            api_version="2026-01-01",
            bearer_token=SecretStr("azure-bearer-token"),
        )
    )

    assert isinstance(provider, AzureOpenAIProvider)
    assert provider._azure_api_key is None
    assert provider._token_callback is not None
    assert provider._token_callback() == "azure-bearer-token"


@pytest.mark.parametrize(
    "base_url",
    ("http://provider.example/v1", "http://127.0.0.1:8000/v1"),
)
def test_public_constructor_rejects_unencrypted_custom_provider(base_url: str) -> None:
    with pytest.raises(ConfigurationError, match="HTTPS"):
        SurveyScribe(
            provider="custom",
            model="test-model",
            api_key="test-key",
            base_url=base_url,
        )


def test_sync_batch_preserves_order(tmp_path: Path) -> None:
    sources = [tmp_path / "first.test", tmp_path / "second.test"]
    for source, value in zip(sources, ("first", "second"), strict=True):
        source.write_text(value, encoding="utf-8")
    client = SurveyScribe(
        _svis_provider(), source_registry=SourceRegistry({".test": TextAdapter()})
    )

    results = client.convert_many(sources)

    assert [result.output.survey_name for result in results if result.output] == [
        "First",
        "Second",
    ]


@pytest.mark.asyncio
async def test_conversion_helper_handles_limiter_failures_and_control_exceptions(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.test"
    source.write_text("value", encoding="utf-8")
    successful = await convert_source(
        source,
        registry=SourceRegistry({".test": TextAdapter()}),
        limits=SourceLimits(),
        limiter=ConcurrencyLimiter(1),
    )
    assert isinstance(successful, SourceDocument)

    failed = await convert_source(
        source,
        registry=SourceRegistry({".test": BrokenAdapter()}),
        limits=SourceLimits(),
    )
    assert isinstance(failed, ExtractionResult)
    assert failed.status is ResultStatus.failed

    class ControlRegistry:
        def convert(self, *_args: object, **_kwargs: object) -> SourceDocument:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        await convert_source(
            source,
            registry=ControlRegistry(),  # type: ignore[arg-type]
            limits=SourceLimits(),
        )


@pytest.mark.asyncio
async def test_run_sync_closes_rejected_coroutine_and_iterable_errors_are_typed(
    tmp_path: Path,
) -> None:
    async def operation() -> str:
        return "value"

    with pytest.raises(RunningEventLoopError):
        run_sync(operation())

    client = SurveyScribe(
        _svis_provider(), source_registry=SourceRegistry({".test": TextAdapter()})
    )
    with pytest.raises(ProgrammerInputError, match="iterable"):
        await client.aconvert_many("source.test")

    def broken_sources():
        raise RuntimeError("iterator failed")
        yield tmp_path / "unused.test"

    with pytest.raises(ProgrammerInputError, match="iterable"):
        await client.aconvert_many(broken_sources())


@pytest.mark.asyncio
async def test_sync_only_provider_close_may_return_awaitable() -> None:
    class SyncClosingProvider(DeterministicFakeProvider):
        def __init__(self) -> None:
            super().__init__(capabilities=_capabilities(), responder=lambda _: Summary(value="x"))
            self.closed = False

        def close(self):
            async def finish() -> None:
                self.closed = True

            return finish()

    provider = SyncClosingProvider()
    client = SurveyScribe(provider)
    await client.aclose()

    assert provider.closed is True


@pytest.mark.asyncio
async def test_pipeline_failures_are_results_and_control_exceptions_propagate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.test"
    source.write_text("value", encoding="utf-8")
    client = SurveyScribe(
        _svis_provider(), source_registry=SourceRegistry({".test": TextAdapter()})
    )

    async def fail(*_args: object, **_kwargs: object) -> ExtractionResult:
        raise RuntimeError("private pipeline failure")

    monkeypatch.setattr(client._pipeline, "extract", fail)
    result = await client.aconvert(source)
    assert result.status is ResultStatus.failed

    async def interrupt(*_args: object, **_kwargs: object) -> ExtractionResult:
        raise KeyboardInterrupt

    monkeypatch.setattr(client._pipeline, "extract", interrupt)
    with pytest.raises(KeyboardInterrupt):
        await client.aconvert(source)


@pytest.mark.asyncio
async def test_batch_cancellation_cancels_sibling_tasks() -> None:
    started = asyncio.Event()

    async def operation() -> ExtractionResult:
        started.set()
        await asyncio.sleep(60)
        return ExtractionResult(output=None)

    task = asyncio.create_task(_gather_conversions((operation(), operation())))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_operational_failures_return_failed_and_control_exceptions_propagate(
    tmp_path: Path,
) -> None:
    source = tmp_path / "first.test"
    source.write_text("first", encoding="utf-8")
    failed = SurveyScribe(
        _svis_provider(), source_registry=SourceRegistry({".test": BrokenAdapter()})
    )
    result = await failed.aconvert(source)
    assert result.status is ResultStatus.failed
    assert "private source failure" not in repr(result)

    async def cancel(_request: FakeRequest) -> object:
        raise asyncio.CancelledError

    provider = DeterministicFakeProvider(capabilities=_capabilities(), responder=cancel)
    client = SurveyScribe(provider, source_registry=SourceRegistry({".test": TextAdapter()}))
    with pytest.raises(asyncio.CancelledError):
        await client.aconvert(source)


@pytest.mark.asyncio
async def test_sync_and_async_results_have_equivalent_outputs(tmp_path: Path) -> None:
    source = tmp_path / "first.test"
    source.write_text("first", encoding="utf-8")
    registry = SourceRegistry({".test": TextAdapter()})
    sync_result = await asyncio.to_thread(
        SurveyScribe(_svis_provider(), source_registry=registry).convert, source
    )
    async_result = await SurveyScribe(_svis_provider(), source_registry=registry).aconvert(source)

    assert sync_result.output == async_result.output
    assert sync_result.status is async_result.status


@pytest.mark.asyncio
async def test_structured_pipeline_makes_one_call_and_has_no_svis_policy() -> None:
    provider = DeterministicFakeProvider(
        capabilities=_capabilities(),
        responder=lambda _request: Summary(value="custom"),
    )
    result = await StructuredPipeline(provider, Summary).extract(
        _document("custom.txt", ("untrusted content",))
    )

    assert result.output == Summary(value="custom")
    assert result.status is ResultStatus.success
    assert provider.call_count == 1
    assert result.diagnostics == ()


@pytest.mark.asyncio
async def test_structured_pipeline_fails_before_call_on_token_overflow() -> None:
    provider = DeterministicFakeProvider(
        capabilities=_capabilities(max_input_tokens=16),
        responder=lambda _request: Summary(value="not called"),
    )
    result = await StructuredPipeline(provider, Summary, max_request_tokens=32).extract(
        _document("custom.txt", ("content",))
    )

    assert result.status is ResultStatus.failed
    assert provider.call_count == 0


@pytest.mark.asyncio
async def test_chunked_pipeline_reducer_empty_success_failure_and_partial() -> None:
    empty_calls: list[tuple[tuple[ProviderResponse[Summary], ...], tuple[FailedBlock, ...]]] = []

    def reduce(
        responses: tuple[ProviderResponse[Summary], ...], failures: tuple[FailedBlock, ...]
    ) -> Combined:
        empty_calls.append((responses, failures))
        return Combined(
            values=tuple(response.output.value for response in responses),
            failed=tuple(failure.block_id for failure in failures),
        )

    empty_provider = DeterministicFakeProvider(
        capabilities=_capabilities(), responder=lambda _: None
    )
    empty = await ChunkedStructuredPipeline(empty_provider, Summary, reduce).extract(
        _document("empty.txt", ())
    )
    assert empty.output == Combined(values=(), failed=())
    assert empty_provider.call_count == 0
    assert len(empty_calls) == 1

    async def respond(request: FakeRequest) -> object:
        if _chunk_id(request) == "chunk-000002":
            raise RuntimeError("private chunk failure")
        return Summary(value=_chunk_id(request))

    document = _document("chunks.txt", ("a" * 600, "b" * 600))
    strict_reducer_called = False

    def strict_reduce(
        responses: tuple[ProviderResponse[Summary], ...], failures: tuple[FailedBlock, ...]
    ) -> Combined:
        nonlocal strict_reducer_called
        strict_reducer_called = True
        return reduce(responses, failures)

    strict = await ChunkedStructuredPipeline(
        DeterministicFakeProvider(capabilities=_capabilities(), responder=respond),
        Summary,
        strict_reduce,
        max_request_tokens=1_400,
        overlap_tokens=0,
    ).extract(document)
    assert strict.status is ResultStatus.failed
    assert not strict_reducer_called

    partial = await ChunkedStructuredPipeline(
        DeterministicFakeProvider(capabilities=_capabilities(), responder=respond),
        Summary,
        reduce,
        max_request_tokens=1_400,
        overlap_tokens=0,
        allow_partial=True,
    ).extract(document)
    assert partial.status is ResultStatus.partial
    assert partial.output == Combined(values=("chunk-000001",), failed=("chunk-000002",))

    def broken_reducer(
        _responses: tuple[ProviderResponse[Summary], ...], _failures: tuple[FailedBlock, ...]
    ) -> Combined:
        raise ValueError("private reducer failure")

    failed = await ChunkedStructuredPipeline(empty_provider, Summary, broken_reducer).extract(
        _document("empty.txt", ())
    )
    assert failed.status is ResultStatus.failed
    assert "private reducer failure" not in repr(failed)


def test_chunked_pipeline_requires_a_callable_reducer() -> None:
    with pytest.raises(ProgrammerInputError, match="reducer"):
        ChunkedStructuredPipeline(_svis_provider(), Summary, None)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_custom_pipeline_convert_and_aconvert_accept_paths_and_bundles(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.test"
    source.write_text("content", encoding="utf-8")
    bundle = SourceBundle(root=tmp_path, primary=Path("source.test"))
    registry = SourceRegistry({".test": TextAdapter()})
    structured = StructuredPipeline(
        DeterministicFakeProvider(
            capabilities=_capabilities(), responder=lambda _request: Summary(value="structured")
        ),
        Summary,
        source_registry=registry,
    )
    chunked = ChunkedStructuredPipeline(
        DeterministicFakeProvider(
            capabilities=_capabilities(), responder=lambda _request: Summary(value="chunked")
        ),
        Summary,
        lambda responses, _failures: Combined(
            values=tuple(response.output.value for response in responses),
            failed=(),
        ),
        source_registry=registry,
    )

    structured_sync = await asyncio.to_thread(structured.convert, source)
    structured_async = await structured.aconvert(bundle)
    chunked_sync = await asyncio.to_thread(chunked.convert, bundle)
    chunked_async = await chunked.aconvert(source)

    assert structured_sync.output == structured_async.output == Summary(value="structured")
    assert chunked_sync.output == chunked_async.output == Combined(values=("chunked",), failed=())


@pytest.mark.asyncio
@pytest.mark.parametrize("pipeline_kind", ("structured", "chunked"))
async def test_custom_pipeline_public_methods_reject_invalid_inputs_and_report_source_failures(
    tmp_path: Path,
    pipeline_kind: str,
) -> None:
    source = tmp_path / "source.test"
    source.write_text("content", encoding="utf-8")
    provider = DeterministicFakeProvider(
        capabilities=_capabilities(), responder=lambda _request: Summary(value="unused")
    )
    if pipeline_kind == "structured":
        pipeline: StructuredPipeline[Summary] | ChunkedStructuredPipeline[Summary, Combined]
        pipeline = StructuredPipeline(
            provider,
            Summary,
            source_registry=SourceRegistry({".test": BrokenAdapter()}),
        )
    else:
        pipeline = ChunkedStructuredPipeline(
            provider,
            Summary,
            lambda responses, failures: Combined(
                values=tuple(response.output.value for response in responses),
                failed=tuple(failure.block_id for failure in failures),
            ),
            source_registry=SourceRegistry({".test": BrokenAdapter()}),
        )

    assert (await pipeline.aconvert(source)).status is ResultStatus.failed
    assert (await asyncio.to_thread(pipeline.convert, source)).status is ResultStatus.failed
    with pytest.raises(SourceInputError):
        await pipeline.aconvert("https://example.test/source.test")
    with pytest.raises(SourceInputError):
        await asyncio.to_thread(pipeline.convert, object())  # type: ignore[arg-type]
    assert provider.call_count == 0


@pytest.mark.asyncio
async def test_custom_pipeline_convert_methods_reject_a_running_loop(tmp_path: Path) -> None:
    source = tmp_path / "source.test"
    source.write_text("content", encoding="utf-8")
    registry = SourceRegistry({".test": TextAdapter()})
    provider = DeterministicFakeProvider(
        capabilities=_capabilities(), responder=lambda _request: Summary(value="unused")
    )
    pipelines = (
        StructuredPipeline(provider, Summary, source_registry=registry),
        ChunkedStructuredPipeline(
            provider,
            Summary,
            lambda _responses, _failures: Combined(values=(), failed=()),
            source_registry=registry,
        ),
    )

    for pipeline in pipelines:
        with pytest.raises(RunningEventLoopError):
            pipeline.convert(source)
    assert provider.call_count == 0


@pytest.mark.asyncio
async def test_chunked_aconvert_keeps_source_order_when_calls_finish_out_of_order(
    tmp_path: Path,
) -> None:
    source = tmp_path / "ordered.test"
    source.write_text("a" * 600 + "\n" + "b" * 600, encoding="utf-8")

    async def respond(request: FakeRequest) -> object:
        chunk_id = _chunk_id(request)
        if chunk_id == "chunk-000001":
            await asyncio.sleep(0.02)
        return Summary(value=chunk_id)

    reduced_orders: list[tuple[str, ...]] = []

    def reduce(
        responses: tuple[ProviderResponse[Summary], ...], failures: tuple[FailedBlock, ...]
    ) -> Combined:
        order = tuple(response.output.value for response in responses)
        reduced_orders.append(order)
        return Combined(values=order, failed=tuple(failure.block_id for failure in failures))

    pipeline = ChunkedStructuredPipeline(
        DeterministicFakeProvider(capabilities=_capabilities(), responder=respond),
        Summary,
        reduce,
        source_registry=SourceRegistry({".test": LineAdapter()}),
        max_request_tokens=1_400,
        overlap_tokens=0,
        max_concurrency=2,
    )

    result = await pipeline.aconvert(SourceBundle(root=tmp_path, primary=Path("ordered.test")))
    sync_result = await asyncio.to_thread(pipeline.convert, source)

    assert result.output == Combined(
        values=("chunk-000001", "chunk-000002"),
        failed=(),
    )
    assert sync_result.output == result.output
    assert reduced_orders == [
        ("chunk-000001", "chunk-000002"),
        ("chunk-000001", "chunk-000002"),
    ]
