"""Public SVIS-only synchronous and asynchronous Survey Scribe facade."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable, Coroutine, Iterable
from datetime import date
from typing import Any, Self, TypeVar

from pydantic import SecretStr

from survey_scribe.config import SurveyScribeConfig
from survey_scribe.errors import (
    ClientClosedError,
    ConfigurationError,
    ProgrammerInputError,
    RunningEventLoopError,
)
from survey_scribe.models.svis import SurveySVIS
from survey_scribe.pipeline import ExtractionPipeline, PipelineConfig
from survey_scribe.providers.base import ConcurrencyLimiter, StructuredProvider
from survey_scribe.results import (
    ArtifactProvenance,
    Diagnostic,
    DiagnosticSeverity,
    ExtractionResult,
)
from survey_scribe.sources.base import (
    DEFAULT_SOURCE_LIMITS,
    LocalSource,
    SourceBundle,
    SourceDocument,
    SourceLimits,
    validate_source_argument,
)
from survey_scribe.sources.registry import SourceRegistry, SourceSvisConversionResult

T = TypeVar("T")


class SurveyScribe:
    """SVIS-only facade over local source conversion and structured extraction."""

    def __init__(
        self,
        provider: StructuredProvider | str | None = None,
        *,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        api_version: str | None = None,
        token_callback: object | None = None,
        config: SurveyScribeConfig | None = None,
        resolve_environment: bool = False,
        source_registry: SourceRegistry | None = None,
        source_limits: SourceLimits = DEFAULT_SOURCE_LIMITS,
        extraction_date: date | None = None,
    ) -> None:
        if config is not None and not isinstance(config, SurveyScribeConfig):
            raise ProgrammerInputError("config must be a SurveyScribeConfig")
        if source_registry is not None and not isinstance(source_registry, SourceRegistry):
            raise ProgrammerInputError("source_registry must be a SourceRegistry")
        if not isinstance(source_limits, SourceLimits):
            raise ProgrammerInputError("source_limits must be SourceLimits")
        if extraction_date is not None and not isinstance(extraction_date, date):
            raise ProgrammerInputError("extraction_date must be a date")
        if isinstance(provider, StructuredProvider):
            if (
                any(
                    value is not None
                    for value in (model, api_key, base_url, api_version, token_callback)
                )
                or resolve_environment
            ):
                raise ProgrammerInputError(
                    "provider configuration cannot be combined with an injected provider"
                )
            resolved_provider = provider
            resolved_config = config or SurveyScribeConfig()
        else:
            if provider is not None and not isinstance(provider, str):
                raise ProgrammerInputError("provider must be a provider name or StructuredProvider")
            if token_callback is not None and not callable(token_callback):
                raise ProgrammerInputError("token_callback must be callable")
            resolved_config = SurveyScribeConfig.resolve(
                constructor={
                    "provider": provider,
                    "model": model,
                    "api_key": api_key,
                    "base_url": base_url,
                    "api_version": api_version,
                    "token_callback": token_callback,
                },
                config=config,
                resolve_environment=resolve_environment,
            )
            resolved_provider = _provider_from_config(resolved_config)
        pipeline_config = PipelineConfig(
            max_concurrency=resolved_config.max_concurrency,
            confidence_threshold=resolved_config.confidence_threshold,
            generation=resolved_config.generation,
            retry=resolved_config.retry,
        )
        self._provider = resolved_provider
        self._registry = source_registry or SourceRegistry.default()
        self._source_limits = source_limits
        active_extraction_date = extraction_date or date.today()
        self._pipeline = ExtractionPipeline(
            resolved_provider,
            config=pipeline_config,
            extraction_date=active_extraction_date,
        )
        self._extraction_date = active_extraction_date
        self._max_concurrency = resolved_config.max_concurrency
        self._closed = False

    @classmethod
    def from_config(
        cls,
        path: LocalSource | None = None,
        *,
        config: SurveyScribeConfig | None = None,
        resolve_environment: bool = False,
        source_registry: SourceRegistry | None = None,
        source_limits: SourceLimits = DEFAULT_SOURCE_LIMITS,
    ) -> Self:
        """Build the facade from explicit config, one TOML path, or opted-in environment."""
        if config is not None and not isinstance(config, SurveyScribeConfig):
            raise ProgrammerInputError("config must be a SurveyScribeConfig")
        resolved = SurveyScribeConfig.from_config(
            path,
            config=config,
            resolve_environment=resolve_environment,
        )
        provider = _provider_from_config(resolved)
        return cls(
            provider,
            config=resolved,
            source_registry=source_registry,
            source_limits=source_limits,
        )

    def convert(self, source: LocalSource | SourceBundle) -> ExtractionResult[SurveySVIS]:
        """Convert one local source from synchronous code."""
        _reject_running_loop()
        self._require_open()
        validate_source_argument(source)
        return asyncio.run(self.aconvert(source))

    async def aconvert(
        self,
        source: LocalSource | SourceBundle,
    ) -> ExtractionResult[SurveySVIS]:
        """Convert one local source through the registry and SVIS pipeline."""
        self._require_open()
        validated = validate_source_argument(source)
        limiter = ConcurrencyLimiter(self._max_concurrency)
        return await self._aconvert(validated, limiter)

    def convert_many(
        self,
        sources: Iterable[LocalSource | SourceBundle],
    ) -> list[ExtractionResult[SurveySVIS]]:
        """Convert local sources in stable input order from synchronous code."""
        _reject_running_loop()
        self._require_open()
        materialized = _validate_sources(sources)
        return asyncio.run(self._aconvert_many(materialized))

    async def aconvert_many(
        self,
        sources: Iterable[LocalSource | SourceBundle],
    ) -> list[ExtractionResult[SurveySVIS]]:
        """Convert local sources in input order under one provider-call ceiling."""
        self._require_open()
        return await self._aconvert_many(_validate_sources(sources))

    async def _aconvert_many(
        self,
        sources: tuple[LocalSource | SourceBundle, ...],
    ) -> list[ExtractionResult[SurveySVIS]]:
        limiter = ConcurrencyLimiter(self._max_concurrency)
        operations = tuple(self._aconvert(source, limiter) for source in sources)
        return list(await _gather_conversions(operations))

    async def _aconvert(
        self,
        source: LocalSource | SourceBundle,
        limiter: ConcurrencyLimiter,
    ) -> ExtractionResult[SurveySVIS]:
        try:
            async with limiter.slot():
                conversion = await asyncio.to_thread(
                    self._registry.convert_for_svis,
                    source,
                    limits=self._source_limits,
                    extraction_date=self._extraction_date,
                )
        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
            raise
        except Exception as error:
            return _failed_result(error)
        if conversion.svis is not None:
            return _native_svis_result(conversion)
        try:
            return await self._pipeline.extract(conversion.document, limiter=limiter)
        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
            raise
        except Exception as error:
            return _failed_result(error)

    def close(self) -> None:
        """Close this facade and its provider from synchronous code."""
        _reject_running_loop()
        if self._closed:
            return
        asyncio.run(self.aclose())

    async def aclose(self) -> None:
        """Close this facade and delegate provider cleanup when available."""
        if self._closed:
            return
        close_async = getattr(self._provider, "aclose", None)
        if callable(close_async):
            outcome = close_async()
            if inspect.isawaitable(outcome):
                await outcome
        else:
            close_sync = getattr(self._provider, "close", None)
            if callable(close_sync):
                outcome = close_sync()
                if inspect.isawaitable(outcome):
                    await outcome
        self._closed = True

    def __enter__(self) -> Self:
        _reject_running_loop()
        self._require_open()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    async def __aenter__(self) -> Self:
        self._require_open()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    def _require_open(self) -> None:
        if self._closed:
            raise ClientClosedError("SurveyScribe is closed")


async def convert_source(
    source: LocalSource | SourceBundle,
    *,
    registry: SourceRegistry,
    limits: SourceLimits,
    limiter: ConcurrencyLimiter | None = None,
) -> SourceDocument | ExtractionResult[None]:
    """Normalize one prevalidated local source without blocking the event loop."""
    validated = validate_source_argument(source)
    try:
        if limiter is not None:
            async with limiter.slot():
                return await asyncio.to_thread(registry.convert, validated, limits=limits)
        return await asyncio.to_thread(registry.convert, validated, limits=limits)
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as error:
        return _failed_result(error)


def run_sync(operation: Coroutine[Any, Any, T]) -> T:
    """Run one coroutine only when the caller has no active event loop."""
    try:
        _reject_running_loop()
    except RunningEventLoopError:
        operation.close()
        raise
    return asyncio.run(operation)


def _reject_running_loop() -> None:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    raise RunningEventLoopError(
        "Synchronous Survey Scribe methods cannot run inside an active event loop; "
        "use the corresponding async method"
    )


def _validate_sources(
    sources: Iterable[LocalSource | SourceBundle],
) -> tuple[LocalSource | SourceBundle, ...]:
    if isinstance(sources, str | bytes | bytearray) or not isinstance(sources, Iterable):
        raise ProgrammerInputError("sources must be an iterable of local sources")
    try:
        return tuple(validate_source_argument(source) for source in sources)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as error:
        if getattr(error, "code", None) is not None:
            raise
        raise ProgrammerInputError("sources could not be read as an iterable") from error


async def _gather_conversions(
    operations: tuple[Coroutine[Any, Any, ExtractionResult[SurveySVIS]], ...],
) -> tuple[ExtractionResult[SurveySVIS], ...]:
    tasks = tuple(asyncio.create_task(operation) for operation in operations)
    try:
        return tuple(await asyncio.gather(*tasks))
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


def _failed_result(error: Exception) -> ExtractionResult[Any]:
    return ExtractionResult(
        output=None,
        diagnostics=(
            Diagnostic(
                code=getattr(error, "code", "CONVERSION_FAILED"),
                message="Conversion failed.",
                severity=DiagnosticSeverity.error,
            ),
        ),
    )


def _native_svis_result(
    conversion: SourceSvisConversionResult,
) -> ExtractionResult[SurveySVIS]:
    output = conversion.svis
    assert output is not None
    diagnostics = tuple(
        Diagnostic(
            code=item.code,
            message=(
                "The XLSForm used deterministic fallbacks for required metadata."
                if item.code == "METADATA_INCOMPLETE"
                else "The XLSForm contains a preserved unsupported or unresolved feature."
            ),
            severity=(
                DiagnosticSeverity.error if item.severity == "error" else DiagnosticSeverity.warning
            ),
        )
        for item in (conversion.native.diagnostics if conversion.native is not None else ())
    )
    provenance = (
        ArtifactProvenance(
            source_sha256=(conversion.document.snapshot_sha256,),
            model_response_sha256=(),
            prompt_versions=(),
        )
        if conversion.document.snapshot_sha256 is not None
        else None
    )
    return ExtractionResult(
        output=output,
        diagnostics=diagnostics,
        artifact_provenance=provenance,
    )


def _provider_from_config(config: SurveyScribeConfig) -> StructuredProvider:
    if config.model is None:
        raise ConfigurationError(
            "A model is required. Set SURVEY_SCRIBE_MODEL or add model to survey-scribe.toml."
        )
    api_key = _secret_value(config.api_key)
    bearer_token = _secret_value(config.bearer_token)
    credential = api_key or bearer_token
    if credential is None and config.token_callback is None:
        raise ConfigurationError(
            "Provider credentials are required. Set a provider API key or token callback."
        )

    from survey_scribe.providers.capabilities import CapabilityEvidence, ModelCapabilities

    supported = {"temperature", "max_output_tokens"}
    if config.provider != "anthropic":
        supported.add("seed")
    capabilities = ModelCapabilities(
        provider=config.provider,
        model=config.model,
        structured_output=True,
        strict_schema=True,
        max_input_tokens=32_000,
        max_output_tokens=max(4_096, config.generation.max_output_tokens),
        supported_generation_settings=frozenset(supported),
        evidence=CapabilityEvidence.configuration_only,
        tested_sdk_version="configuration-only",
    )
    try:
        if config.provider == "anthropic":
            from survey_scribe.providers.anthropic import InstructorAnthropicProvider

            return InstructorAnthropicProvider(
                model=config.model,
                capabilities=capabilities,
                api_key=credential,
            )
        if config.provider in {"azure", "azure_openai"}:
            from survey_scribe.providers.azure import AzureOpenAIProvider

            if config.base_url is None or config.api_version is None:
                raise ConfigurationError("Azure requires base_url and api_version")
            token_provider = config.token_callback
            if bearer_token is not None:
                token_provider = _static_token_provider(bearer_token)
            return AzureOpenAIProvider(
                deployment=config.model,
                azure_endpoint=str(config.base_url).rstrip("/"),
                api_version=config.api_version,
                capabilities=capabilities,
                api_key=api_key,
                token_callback=token_provider,
            )
        if config.provider not in {"openai", "openrouter", "vercel", "custom"}:
            raise ConfigurationError(f"Unsupported provider: {config.provider}")
        from survey_scribe.providers.openai_compatible import (
            InstructorOpenAIProvider,
            OpenAICompatiblePreset,
        )

        if config.provider == "custom" and config.base_url is None:
            raise ConfigurationError("Custom providers require base_url")
        if config.base_url is not None:
            return InstructorOpenAIProvider(
                model=config.model,
                api_key=credential,
                base_url=str(config.base_url).rstrip("/"),
                capabilities=capabilities,
            )
        return InstructorOpenAIProvider.from_preset(
            OpenAICompatiblePreset(config.provider),
            model=config.model,
            api_key=credential,
            capabilities=capabilities,
        )
    except ConfigurationError:
        raise
    except (TypeError, ValueError) as error:
        raise ConfigurationError(str(error)) from None


def _secret_value(secret: SecretStr | None) -> str | None:
    return secret.get_secret_value() if secret is not None else None


def _static_token_provider(token: str) -> Callable[[], str]:
    def provide_token() -> str:
        return token

    return provide_token


__all__ = ["SurveyScribe"]
