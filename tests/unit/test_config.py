"""Configuration validation and precedence tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from survey_scribe.config import SurveyScribeConfig
from survey_scribe.errors import AmbiguousCredentialError, ConfigurationError


def _write_config(path: Path, *, model: str, provider: str = "openai") -> None:
    path.write_text(
        f'config_version = 1\nprovider = "{provider}"\nmodel = "{model}"\n',
        encoding="utf-8",
    )


def test_sdk_precedence_uses_constructor_config_environment_toml_and_defaults(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "explicit.toml"
    _write_config(config_path, model="from-toml")
    environment = {
        "SURVEY_SCRIBE_MODEL": "from-generic-environment",
        "OPENAI_API_KEY": "provider-key",
    }
    explicit = SurveyScribeConfig(model="from-config")

    assert SurveyScribeConfig.resolve().model is None
    assert SurveyScribeConfig.resolve(config_path=config_path).model == "from-toml"
    assert (
        SurveyScribeConfig.resolve(
            config_path=config_path,
            resolve_environment=True,
            environ=environment,
        ).model
        == "from-generic-environment"
    )
    assert (
        SurveyScribeConfig.resolve(
            config=explicit,
            config_path=config_path,
            resolve_environment=True,
            environ=environment,
        ).model
        == "from-config"
    )
    resolved = SurveyScribeConfig.resolve(
        constructor={"model": "from-constructor"},
        config=explicit,
        config_path=config_path,
        resolve_environment=True,
        environ=environment,
    )
    assert resolved.model == "from-constructor"
    assert resolved.api_key == SecretStr("provider-key")


def test_sdk_does_not_resolve_environment_unless_requested() -> None:
    resolved = SurveyScribeConfig.resolve(
        environ={
            "SURVEY_SCRIBE_PROVIDER": "anthropic",
            "ANTHROPIC_API_KEY": "not-loaded",
        }
    )

    assert resolved.provider == "openai"
    assert resolved.api_key is None


def test_cli_precedence_includes_current_directory_config(tmp_path: Path) -> None:
    cwd_config = tmp_path / "survey-scribe.toml"
    explicit_config = tmp_path / "explicit.toml"
    _write_config(cwd_config, model="from-cwd", provider="azure")
    _write_config(explicit_config, model="from-explicit", provider="azure")

    assert SurveyScribeConfig.resolve_cli(cwd=tmp_path, environ={}).model == "from-cwd"
    assert (
        SurveyScribeConfig.resolve_cli(
            cwd=tmp_path,
            config_path=explicit_config,
            environ={},
        ).model
        == "from-explicit"
    )

    provider_environment = {
        "AZURE_OPENAI_DEPLOYMENT": "from-provider-environment",
        "AZURE_OPENAI_API_KEY": "azure-key",
    }
    assert (
        SurveyScribeConfig.resolve_cli(
            cwd=tmp_path,
            config_path=explicit_config,
            environ=provider_environment,
        ).model
        == "from-provider-environment"
    )

    generic_environment = {
        **provider_environment,
        "SURVEY_SCRIBE_MODEL": "from-generic-environment",
    }
    assert (
        SurveyScribeConfig.resolve_cli(
            cwd=tmp_path,
            config_path=explicit_config,
            environ=generic_environment,
        ).model
        == "from-generic-environment"
    )
    assert (
        SurveyScribeConfig.resolve_cli(
            flags={"model": "from-flags"},
            cwd=tmp_path,
            config_path=explicit_config,
            environ=generic_environment,
        ).model
        == "from-flags"
    )


def test_parent_and_home_configs_are_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = tmp_path / "parent"
    child = parent / "child"
    home = tmp_path / "home"
    child.mkdir(parents=True)
    home.mkdir()
    _write_config(parent / "survey-scribe.toml", model="from-parent")
    _write_config(home / "survey-scribe.toml", model="from-home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))

    assert SurveyScribeConfig.from_config(cwd=child, environ={}).model is None
    assert SurveyScribeConfig.resolve_cli(cwd=child, environ={}).model is None


@pytest.mark.parametrize(
    "credentials",
    [
        {"api_key": SecretStr("key"), "bearer_token": SecretStr("token")},
        {"api_key": SecretStr("key"), "token_callback": lambda: "token"},
        {"bearer_token": SecretStr("token"), "token_callback": lambda: "token"},
    ],
)
def test_ambiguous_credentials_are_rejected(credentials: dict[str, object]) -> None:
    with pytest.raises(AmbiguousCredentialError, match="credential"):
        SurveyScribeConfig(**credentials)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("base_url", "not-a-url"),
        ("confidence_threshold", -0.01),
        ("confidence_threshold", 1.01),
        ("max_concurrency", 0),
        ("config_version", 2),
    ],
)
def test_invalid_values_are_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        SurveyScribeConfig(**{field: value})


@pytest.mark.parametrize(
    "contents",
    [
        'config_version = 1\nunknown = "value"\n',
        "config_version = 2\n",
        'config_version = 1\napi_key = "must-not-be-persisted"\n',
    ],
)
def test_toml_rejects_unknown_version_and_persisted_secret(tmp_path: Path, contents: str) -> None:
    config_path = tmp_path / "invalid.toml"
    config_path.write_text(contents, encoding="utf-8")

    with pytest.raises(ConfigurationError):
        SurveyScribeConfig.from_config(config_path, environ={})


def test_secret_fields_never_serialize_or_appear_in_repr() -> None:
    config = SurveyScribeConfig(api_key=SecretStr("api-secret"))
    callback_config = SurveyScribeConfig(token_callback=lambda: "callback-secret")

    serialized = config.model_dump(mode="json")
    rendered = config.model_dump_json()
    representation = repr(config) + repr(callback_config)

    assert "api_key" not in serialized
    assert "bearer_token" not in serialized
    assert "token_callback" not in serialized
    assert "api-secret" not in rendered
    assert "callback-secret" not in callback_config.model_dump_json()
    assert "callback-secret" not in rendered
    assert "api-secret" not in representation
    assert "callback-secret" not in representation


@pytest.mark.parametrize(
    "base_url",
    [
        "https://user:password@example.test/v1",
        "https://example.test/v1?api_key=query-secret",
        "https://example.test/v1?client_secret=query-secret",
        "https://example.test/v1?token=query-secret",
        "https://example.test/v1?key=query-secret",
        "https://example.test/v1?sig=query-secret",
        "https://example.test/v1#fragment-secret",
    ],
)
def test_base_url_rejects_embedded_credentials(base_url: str) -> None:
    with pytest.raises(ValidationError) as raised:
        SurveyScribeConfig(base_url=base_url)

    assert "password" not in str(raised.value)
    assert "query-secret" not in str(raised.value)
    assert "fragment-secret" not in str(raised.value)


def test_validation_errors_hide_invalid_credential_values() -> None:
    with pytest.raises(ValidationError) as raised:
        SurveyScribeConfig(api_key={"value": "constructor-secret"})

    assert "constructor-secret" not in str(raised.value)


def test_nested_toml_secret_is_rejected_without_exposure(tmp_path: Path) -> None:
    config_path = tmp_path / "nested-secret.toml"
    config_path.write_text(
        'config_version = 1\n[generation]\napi_key = "nested-secret-value"\n',
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError) as raised:
        SurveyScribeConfig.from_config(config_path, environ={})

    assert "nested-secret-value" not in str(raised.value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("config_version", True),
        ("max_concurrency", True),
        ("max_concurrency", "4"),
        ("confidence_threshold", float("nan")),
        ("confidence_threshold", float("inf")),
        ("artifacts", {"sidecar": "false"}),
        ("artifacts", {"manifest": False}),
        ("retry", {"initial_delay_seconds": float("inf")}),
    ],
)
def test_control_values_are_strict_and_finite(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        SurveyScribeConfig(**{field: value})
