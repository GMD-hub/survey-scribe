"""Typed configuration and deterministic source precedence."""

from __future__ import annotations

import os
import tomllib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Literal, Self
from urllib.parse import parse_qsl

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)

from survey_scribe.errors import (
    AmbiguousCredentialError,
    ConfigurationError,
    is_sensitive_key,
    is_sensitive_query_key,
    redact_exception,
)

CONFIG_VERSION = 1
DEFAULT_CONFIG_FILENAME = "survey-scribe.toml"

TokenCallback = Callable[[], str]


class GenerationConfig(BaseModel):
    """Structured generation settings shared by provider adapters."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    temperature: float = Field(default=0.0, ge=0.0, le=2.0, strict=True, allow_inf_nan=False)
    max_output_tokens: int = Field(default=4096, ge=1, strict=True)
    seed: int | None = Field(default=None, strict=True)


class RetryConfig(BaseModel):
    """Bounded retry settings."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    max_attempts: int = Field(default=3, ge=1, le=10, strict=True)
    initial_delay_seconds: float = Field(default=0.5, ge=0.0, strict=True, allow_inf_nan=False)
    max_delay_seconds: float = Field(default=8.0, ge=0.0, strict=True, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_delay_range(self) -> Self:
        """Require the maximum delay to include the initial delay."""
        if self.max_delay_seconds < self.initial_delay_seconds:
            raise ValueError("max_delay_seconds must be at least initial_delay_seconds")
        return self


class RoutingConfig(BaseModel):
    """Provider-neutral routing limits and thresholds."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    max_source_quote_chars: int = Field(default=2_000, ge=1, le=2_000, strict=True)
    max_request_tokens: int = Field(default=32_000, ge=1, le=32_000, strict=True)
    max_inventory_items_per_call: int = Field(default=250, ge=1, le=250, strict=True)
    max_candidate_targets_per_reference: int = Field(default=10, ge=1, le=10, strict=True)
    max_discrepancies_per_review_call: int = Field(default=25, ge=1, le=25, strict=True)
    max_source_spans_per_decision: int = Field(default=8, ge=1, le=8, strict=True)
    max_condition_depth: int = Field(default=6, ge=1, le=6, strict=True)
    max_condition_nodes: int = Field(default=100, ge=1, le=100, strict=True)
    low_confidence_threshold: float = Field(
        default=0.70,
        ge=0.0,
        le=1.0,
        strict=True,
        allow_inf_nan=False,
    )
    unusual_in_degree_threshold: int = Field(default=4, ge=1, strict=True)
    unusual_out_degree_threshold: int = Field(default=3, ge=1, strict=True)
    max_concurrency: int = Field(default=4, ge=1, le=128, strict=True)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)


class ArtifactConfig(BaseModel):
    """Default artifact publication settings."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    sidecar: bool = Field(default=True, strict=True)
    manifest: Literal[True] = True


class SurveyScribeConfig(BaseModel):
    """Validated application configuration with non-serializable credentials."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        arbitrary_types_allowed=True,
        hide_input_in_errors=True,
    )

    config_version: Literal[1] = CONFIG_VERSION
    provider: str = "openai"
    model: str | None = None
    base_url: AnyHttpUrl | None = None
    api_version: str | None = None
    api_key: SecretStr | None = Field(default=None, exclude=True, repr=False)
    bearer_token: SecretStr | None = Field(default=None, exclude=True, repr=False)
    token_callback: TokenCallback | None = Field(default=None, exclude=True, repr=False)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    max_concurrency: int = Field(default=4, ge=1, le=128, strict=True)
    confidence_threshold: float = Field(
        default=0.7, ge=0.0, le=1.0, strict=True, allow_inf_nan=False
    )
    routing: RoutingConfig = Field(default_factory=RoutingConfig)
    artifacts: ArtifactConfig = Field(default_factory=ArtifactConfig)

    def __init__(self, **data: Any) -> None:
        credential_names = ("api_key", "bearer_token", "token_callback")
        if sum(data.get(name) is not None for name in credential_names) > 1:
            raise AmbiguousCredentialError(
                "Configure exactly one credential form: api key, bearer token, or token callback"
            )
        super().__init__(**data)

    @field_validator("config_version", mode="before")
    @classmethod
    def require_integer_config_version(cls, value: object) -> object:
        """Reject Boolean values that compare equal to version one."""
        if type(value) is not int:
            raise ValueError("config_version must be the integer 1")
        return value

    @field_validator("base_url")
    @classmethod
    def reject_secret_bearing_base_url(cls, value: AnyHttpUrl | None) -> AnyHttpUrl | None:
        """Reject credentials and non-routing fragments in provider base URLs."""
        if value is None:
            return None
        if value.scheme != "https":
            raise ValueError("base_url must use HTTPS")
        if value.username is not None or value.password is not None:
            raise ValueError("base_url must not contain user information")
        if value.fragment:
            raise ValueError("base_url must not contain a fragment")
        if any(is_sensitive_query_key(key) for key, _item in parse_qsl(value.query or "")):
            raise ValueError("base_url must not contain sensitive query parameters")
        return value

    @field_validator("provider")
    @classmethod
    def normalize_provider(cls, value: str) -> str:
        """Normalize provider names while rejecting empty values."""
        normalized = value.strip().lower().replace("-", "_")
        if not normalized:
            raise ValueError("provider must not be empty")
        return normalized

    @field_validator("model", "api_version")
    @classmethod
    def reject_empty_optional_strings(cls, value: str | None) -> str | None:
        """Reject configured string values that contain only whitespace."""
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("configured value must not be empty")
        return normalized

    @model_validator(mode="after")
    def reject_ambiguous_credentials(self) -> Self:
        """Allow at most one key, bearer token, or token callback."""
        credentials = (self.api_key, self.bearer_token, self.token_callback)
        if sum(value is not None for value in credentials) > 1:
            raise AmbiguousCredentialError(
                "Configure exactly one credential form: api key, bearer token, or token callback"
            )
        return self

    @classmethod
    def resolve(
        cls,
        *,
        constructor: Mapping[str, object] | None = None,
        config: SurveyScribeConfig | None = None,
        config_path: str | os.PathLike[str] | None = None,
        resolve_environment: bool = False,
        environ: Mapping[str, str] | None = None,
    ) -> Self:
        """Resolve SDK settings without implicit TOML or environment access.

        Args:
            constructor: Highest-priority field values. Entries set to ``None``
                are ignored.
            config: Explicitly set fields from an existing configuration model.
            config_path: Exact TOML file to read. No file is read when omitted.
            resolve_environment: Whether to read credential and provider values
                from ``environ`` or the process environment.
            environ: Environment mapping to use instead of ``os.environ``.

        Returns:
            A validated, frozen configuration model.

        Raises:
            ConfigurationError: A file is missing, malformed, secret-bearing, or
                resolves to invalid settings.
            AmbiguousCredentialError: More than one credential form is resolved.
        """
        file_values = _read_toml(Path(config_path)) if config_path is not None else {}
        explicit_config = _explicit_model_values(config) if config is not None else {}
        constructor_values = _without_none(dict(constructor or {}))
        values: dict[str, Any] = dict(file_values)
        if resolve_environment:
            environment = os.environ if environ is None else environ
            provider_hint = _provider_hint(
                constructor_values,
                explicit_config,
                _generic_environment(environment),
                file_values,
            )
            values = _merge_config_sources(
                values,
                _environment_values(environment, provider_hint=provider_hint),
            )
        values = _merge_config_sources(values, explicit_config)
        values = _merge_config_sources(values, constructor_values)
        return cls._validate_resolved(values)

    @classmethod
    def from_config(
        cls,
        path: str | os.PathLike[str] | None = None,
        *,
        constructor: Mapping[str, object] | None = None,
        config: SurveyScribeConfig | None = None,
        resolve_environment: bool = False,
        environ: Mapping[str, str] | None = None,
        cwd: str | os.PathLike[str] | None = None,
    ) -> Self:
        """Resolve an explicit TOML file, or only the current-directory file.

        Args:
            path: Exact TOML path. When omitted, only
                ``cwd/survey-scribe.toml`` is considered.
            constructor: Highest-priority field values.
            config: Explicitly set fields from an existing configuration model.
            resolve_environment: Whether to resolve environment values.
            environ: Environment mapping to use instead of ``os.environ``.
            cwd: Directory used for default-file discovery. The process current
                directory is used when omitted.

        Returns:
            A validated, frozen configuration model.

        Raises:
            ConfigurationError: The selected file or resolved values are invalid.
            AmbiguousCredentialError: More than one credential form is resolved.
        """
        config_path: Path | None
        if path is not None:
            config_path = Path(path)
        else:
            current_directory = Path.cwd() if cwd is None else Path(cwd)
            candidate = current_directory / DEFAULT_CONFIG_FILENAME
            config_path = candidate if candidate.is_file() else None
        return cls.resolve(
            constructor=constructor,
            config=config,
            config_path=config_path,
            resolve_environment=resolve_environment,
            environ=environ,
        )

    @classmethod
    def resolve_cli(
        cls,
        *,
        flags: Mapping[str, object] | None = None,
        config_path: str | os.PathLike[str] | None = None,
        environ: Mapping[str, str] | None = None,
        cwd: str | os.PathLike[str] | None = None,
    ) -> Self:
        """Resolve CLI settings without searching parent or home directories.

        Args:
            flags: Highest-priority non-``None`` command-line values.
            config_path: Exact TOML path. When omitted, only
                ``cwd/survey-scribe.toml`` is considered.
            environ: Environment mapping. The process environment is used when
                omitted.
            cwd: Directory used for default-file discovery.

        Returns:
            A validated, frozen configuration model.

        Raises:
            ConfigurationError: The requested file is missing or resolved values
                are invalid.
            AmbiguousCredentialError: More than one credential form is resolved.
        """
        current_directory = Path.cwd() if cwd is None else Path(cwd)
        requested_path = (
            Path(config_path)
            if config_path is not None
            else current_directory / DEFAULT_CONFIG_FILENAME
        )
        file_values = _read_toml(requested_path) if requested_path.is_file() else {}
        if config_path is not None and not requested_path.is_file():
            raise ConfigurationError(f"Configuration file does not exist: {requested_path}")
        environment = os.environ if environ is None else environ
        flag_values = _without_none(dict(flags or {}))
        generic_environment = _generic_environment(environment)
        provider_hint = _provider_hint(
            flag_values,
            generic_environment,
            file_values,
        )
        values = _merge_config_sources(
            file_values,
            _provider_environment(environment, provider_hint),
        )
        values = _merge_config_sources(values, generic_environment)
        values = _merge_config_sources(values, flag_values)
        return cls._validate_resolved(values)

    @classmethod
    def _validate_resolved(cls, values: Mapping[str, object]) -> Self:
        credential_names = ("api_key", "bearer_token", "token_callback")
        if sum(values.get(name) is not None for name in credential_names) > 1:
            raise AmbiguousCredentialError(
                "Configure exactly one credential form: api key, bearer token, or token callback"
            )
        try:
            return cls.model_validate(values)
        except AmbiguousCredentialError:
            raise
        except ValidationError as error:
            raise ConfigurationError(_safe_validation_error(error)) from None


def _read_toml(path: Path) -> dict[str, Any]:
    """Read and validate one exact TOML path."""
    if not path.is_file():
        raise ConfigurationError(f"Configuration file does not exist: {path}")
    try:
        with path.open("rb") as stream:
            values = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigurationError(redact_exception(error)) from None
    persisted_secrets = _persisted_secret_paths(values)
    if persisted_secrets:
        names = ", ".join(sorted(persisted_secrets))
        raise ConfigurationError(f"TOML must not persist credential fields: {names}")
    try:
        validated = SurveyScribeConfig.model_validate(values)
    except (ValidationError, AmbiguousCredentialError) as error:
        message = (
            _safe_validation_error(error) if isinstance(error, ValidationError) else str(error)
        )
        raise ConfigurationError(message) from None
    return validated.model_dump()


def _explicit_model_values(model: BaseModel) -> dict[str, Any]:
    """Return only values explicitly set by the caller, including nested models."""
    values: dict[str, Any] = {}
    for field_name in model.model_fields_set:
        value = getattr(model, field_name)
        if isinstance(value, BaseModel):
            values[field_name] = _explicit_model_values(value)
        else:
            values[field_name] = value
    return values


def _without_none(values: Mapping[str, object]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(existing, Mapping) and isinstance(value, Mapping):
            merged[key] = _deep_merge(existing, value)
        else:
            merged[key] = value
    return merged


def _merge_config_sources(
    base: Mapping[str, Any],
    override: Mapping[str, Any],
) -> dict[str, Any]:
    """Merge precedence ranks while treating credential forms as one setting."""
    credential_names = {"api_key", "bearer_token", "token_callback"}
    merged_base = dict(base)
    if credential_names.intersection(override):
        for name in credential_names:
            merged_base.pop(name, None)
    return _deep_merge(merged_base, override)


def _provider_hint(*sources: Mapping[str, Any]) -> str:
    for source in sources:
        provider = source.get("provider")
        if isinstance(provider, str) and provider.strip():
            return provider.strip().lower().replace("-", "_")
    return "openai"


def _generic_environment(environ: Mapping[str, str]) -> dict[str, Any]:
    names = {
        "SURVEY_SCRIBE_PROVIDER": "provider",
        "SURVEY_SCRIBE_MODEL": "model",
        "SURVEY_SCRIBE_BASE_URL": "base_url",
        "SURVEY_SCRIBE_API_KEY": "api_key",
        "SURVEY_SCRIBE_BEARER_TOKEN": "bearer_token",
    }
    return {
        field: environ[name] for name, field in names.items() if environ.get(name) not in (None, "")
    }


def _provider_environment(environ: Mapping[str, str], provider: str) -> dict[str, Any]:
    provider_names: dict[str, dict[str, str]] = {
        "openai": {
            "OPENAI_API_KEY": "api_key",
            "OPENAI_BASE_URL": "base_url",
        },
        "openrouter": {"OPENROUTER_API_KEY": "api_key"},
        "vercel": {"AI_GATEWAY_API_KEY": "api_key"},
        "anthropic": {"ANTHROPIC_API_KEY": "api_key"},
        "azure": {
            "AZURE_OPENAI_API_KEY": "api_key",
            "AZURE_OPENAI_ENDPOINT": "base_url",
            "AZURE_OPENAI_API_VERSION": "api_version",
            "AZURE_OPENAI_DEPLOYMENT": "model",
        },
        "azure_openai": {
            "AZURE_OPENAI_API_KEY": "api_key",
            "AZURE_OPENAI_ENDPOINT": "base_url",
            "AZURE_OPENAI_API_VERSION": "api_version",
            "AZURE_OPENAI_DEPLOYMENT": "model",
        },
    }
    names = provider_names.get(provider, {})
    return {
        field: environ[name] for name, field in names.items() if environ.get(name) not in (None, "")
    }


def _environment_values(environ: Mapping[str, str], *, provider_hint: str) -> dict[str, Any]:
    return _merge_config_sources(
        _provider_environment(environ, provider_hint),
        _generic_environment(environ),
    )


def _persisted_secret_paths(values: Mapping[str, Any], *, prefix: str = "") -> tuple[str, ...]:
    found: list[str] = []
    for key, value in values.items():
        path = f"{prefix}.{key}" if prefix else key
        if is_sensitive_key(key) or key == "token_callback":
            found.append(path)
        elif isinstance(value, Mapping):
            found.extend(_persisted_secret_paths(value, prefix=path))
    return tuple(found)


def _safe_validation_error(error: ValidationError) -> str:
    details = error.errors(include_input=False, include_url=False)
    return redact_exception(ValueError(str(details)))
