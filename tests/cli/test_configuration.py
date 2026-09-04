"""CLI configuration, input, and credential safety tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from survey_scribe import ExtractionResult, cli
from survey_scribe.results import DiagnosticSeverity

from .conftest import FakeClient, make_svis


def test_cli_flags_override_generic_environment_and_explicit_toml(
    tmp_path: Path,
    cli_environment: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del cli_environment
    config_path = tmp_path / "settings.toml"
    config_path.write_text(
        'config_version = 1\nprovider = "anthropic"\nmodel = "toml-model"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("SURVEY_SCRIBE_PROVIDER", "openrouter")
    monkeypatch.setenv("SURVEY_SCRIBE_MODEL", "environment-model")
    observed = []

    def factory(config: Any) -> FakeClient:
        observed.append(config)
        return FakeClient([ExtractionResult(output=make_svis())])

    monkeypatch.setattr(cli, "_create_client", factory)

    assert (
        cli.main(
            [
                "convert",
                "input.txt",
                "--config",
                str(config_path),
                "--provider",
                "openai",
                "--model",
                "flag-model",
                "-o",
                str(tmp_path / "output"),
            ]
        )
        == 0
    )
    assert observed[0].provider == "openai"
    assert observed[0].model == "flag-model"


def test_cli_uses_only_current_directory_default_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent_config = tmp_path / "survey-scribe.toml"
    parent_config.write_text('config_version = 1\nmodel = "parent-model"\n', encoding="utf-8")
    child = tmp_path / "child"
    child.mkdir()
    monkeypatch.chdir(child)
    for key in tuple(__import__("os").environ):
        if key.startswith("SURVEY_SCRIBE_") or key.startswith("OPENAI_"):
            monkeypatch.delenv(key, raising=False)

    assert cli.main(["config", "check"]) == 1


def test_non_echo_prompt_overrides_environment_credential_without_output(
    tmp_path: Path,
    cli_environment: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del cli_environment
    secret = "prompted-super-secret"
    observed = []
    monkeypatch.setenv("SURVEY_SCRIBE_BEARER_TOKEN", "lower-priority-token")
    monkeypatch.setattr(cli.getpass, "getpass", lambda _prompt: secret)

    def factory(config: Any) -> FakeClient:
        observed.append(config)
        return FakeClient([ExtractionResult(output=make_svis())])

    monkeypatch.setattr(cli, "_create_client", factory)

    assert (
        cli.main(
            [
                "convert",
                "input.txt",
                "--prompt-api-key",
                "-o",
                str(tmp_path / "output"),
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert observed[0].api_key.get_secret_value() == secret
    assert observed[0].bearer_token is None
    assert secret not in captured.out + captured.err
    assert "lower-priority-token" not in captured.out + captured.err


def test_provider_failure_redacts_environment_secret(
    cli_environment: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del cli_environment

    class FailedProviderClient(FakeClient):
        def convert(self, path: Path) -> ExtractionResult[Any]:
            del path
            raise RuntimeError("authorization=Bearer cli-secret")

    monkeypatch.setattr(cli, "_create_client", lambda _config: FailedProviderClient([]))
    assert cli.main(["convert", "input.txt"]) == 1

    error = capsys.readouterr().err
    assert "cli-secret" not in error
    assert "[REDACTED]" in error


@pytest.mark.parametrize(
    ("source", "code"),
    [("missing.txt", "SOURCE_INPUT_INVALID"), ("questionnaire.exe", "SOURCE_FORMAT_UNSUPPORTED")],
)
def test_missing_and_unsupported_inputs_are_nonzero(
    cli_environment: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    source: str,
    code: str,
) -> None:
    del cli_environment

    class InputClient(FakeClient):
        def convert(self, path: Path) -> ExtractionResult[Any]:
            del path
            from survey_scribe import Diagnostic

            return ExtractionResult(
                output=None,
                diagnostics=(
                    Diagnostic(
                        code=code,
                        message="Input rejected",
                        severity=DiagnosticSeverity.error,
                    ),
                ),
            )

    monkeypatch.setattr(cli, "_create_client", lambda _config: InputClient([]))
    assert cli.main(["convert", source]) == 1
    assert code in capsys.readouterr().err


def test_config_check_reports_only_non_secret_identity(
    cli_environment: None,
    fake_client_factory: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del cli_environment
    fake_client_factory(ExtractionResult(output=make_svis()))
    assert cli.main(["config", "check"]) == 0

    captured = capsys.readouterr()
    assert captured.out == (
        "configuration valid provider=openai model=cli-model credential=configured\n"
    )
    assert "cli-secret" not in captured.out + captured.err


def test_cli_factory_maps_prompted_azure_bearer_token_to_token_provider(
    cli_environment: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del cli_environment
    prompted_value = "fixture-value"
    observed = []
    original_factory = cli._create_client
    monkeypatch.setattr(cli.getpass, "getpass", lambda _prompt: prompted_value)

    def factory(config: Any):
        client = original_factory(config)
        observed.append(client._provider)
        return client

    monkeypatch.setattr(cli, "_create_client", factory)

    assert (
        cli.main(
            [
                "config",
                "check",
                "--provider",
                "azure",
                "--model",
                "deployment",
                "--base-url",
                "https://resource.example",
                "--api-version",
                "2026-01-01",
                "--prompt-bearer-token",
            ]
        )
        == 0
    )
    provider = observed[0]
    assert provider._azure_api_key is None
    assert provider._token_callback() == prompted_value
    captured = capsys.readouterr()
    assert prompted_value not in captured.out + captured.err
