"""Installed command-line interface for Survey Scribe."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any, TextIO
from uuid import uuid4

from survey_scribe import (
    ArtifactCollisionError,
    ArtifactWriteError,
    ExtractionResult,
    ResultStatus,
    SurveyScribe,
    SurveyScribeConfig,
    __version__,
)
from survey_scribe.errors import redact_exception, redact_text

_EXIT_OK = 0
_EXIT_ERROR = 1
_BATCH_MANIFEST = "batch_manifest.json"
_BATCH_RESERVATION = f".{_BATCH_MANIFEST}.lock"
_PROVIDERS = (
    ("openai", "preset", "configuration-only", "OpenAI-compatible endpoint"),
    ("openrouter", "preset", "configuration-only", "OpenAI-compatible endpoint"),
    ("vercel", "preset", "configuration-only", "Vercel AI Gateway endpoint"),
    ("custom", "explicit", "configuration-only", "Requires --base-url"),
    ("azure/azure_openai", "adapter", "configuration-only", "Azure OpenAI or Foundry"),
    ("anthropic", "adapter", "configuration-only", "Requires anthropic extra"),
)


class _CommandError(RuntimeError):
    """A command failure whose message is safe for terminal output."""


def _export_routing_schema(_args: argparse.Namespace) -> int:
    from survey_scribe import canonical_routing_schema_json

    sys.stdout.write(canonical_routing_schema_json())
    return _EXIT_OK


def _create_client(config: SurveyScribeConfig) -> SurveyScribe:
    """Construct the public client; tests can replace this narrow seam."""
    return SurveyScribe(config=config)


def _new_batch_run_id() -> str:
    """Create one opaque identifier for a batch command invocation."""
    return uuid4().hex


def _add_configuration_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config", type=Path, help="Exact TOML path (default: ./survey-scribe.toml)."
    )
    parser.add_argument(
        "--provider",
        choices=("openai", "openrouter", "vercel", "custom", "azure", "azure_openai", "anthropic"),
        help="Provider adapter or OpenAI-compatible preset.",
    )
    parser.add_argument("--model", help="Provider model or Azure deployment name.")
    parser.add_argument("--base-url", help="HTTPS base URL for a custom or Azure endpoint.")
    parser.add_argument("--api-version", help="Azure API version.")
    credential = parser.add_mutually_exclusive_group()
    credential.add_argument(
        "--prompt-api-key",
        action="store_true",
        help="Read an API key from a non-echo terminal prompt.",
    )
    credential.add_argument(
        "--prompt-bearer-token",
        action="store_true",
        help="Read a bearer token from a non-echo terminal prompt.",
    )


def _add_conversion_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="Artifact directory (default: ./output).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Publish a new generation when artifacts already exist.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit nonzero when any result is partial.",
    )
    parser.add_argument(
        "--no-sidecar",
        action="store_true",
        help="Omit sidecars for successful results; partial results require sidecars.",
    )
    _add_configuration_arguments(parser)


def build_parser() -> argparse.ArgumentParser:
    """Build the installed command parser without loading optional SDKs."""
    parser = argparse.ArgumentParser(
        prog="survey-scribe",
        description="Convert local questionnaires and inspect Survey Scribe.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command")

    convert = commands.add_parser("convert", help="Convert one local questionnaire.")
    convert.add_argument("input", type=Path, help="Local questionnaire path.")
    _add_conversion_arguments(convert)
    convert.set_defaults(handler=_convert_command)

    batch = commands.add_parser("batch", help="Convert local questionnaires in input order.")
    batch.add_argument("inputs", nargs="+", type=Path, help="Local questionnaire paths.")
    _add_conversion_arguments(batch)
    batch.set_defaults(handler=_batch_command)

    providers = commands.add_parser("providers", help="List provider presets and evidence.")
    providers.set_defaults(handler=_providers_command)

    config = commands.add_parser("config", help="Validate resolved configuration.")
    config_commands = config.add_subparsers(dest="config_command", required=True)
    config_check = config_commands.add_parser("check", help="Resolve and validate configuration.")
    _add_configuration_arguments(config_check)
    config_check.set_defaults(handler=_config_check_command)

    schema = commands.add_parser("schema", help="Work with public JSON schemas.")
    schema_commands = schema.add_subparsers(dest="schema_command", required=True)
    export = schema_commands.add_parser("export", help="Export a public JSON schema.")
    export.add_argument("schema_name", choices=("routing",))
    export.set_defaults(handler=_export_routing_schema)
    return parser


def _configuration(args: argparse.Namespace) -> SurveyScribeConfig:
    flags: dict[str, object] = {
        "provider": getattr(args, "provider", None),
        "model": getattr(args, "model", None),
        "base_url": getattr(args, "base_url", None),
        "api_version": getattr(args, "api_version", None),
    }
    prompted: list[str] = []
    if getattr(args, "prompt_api_key", False):
        value = getpass.getpass("API key: ")
        if not value:
            raise _CommandError("Credential prompt was empty.")
        flags["api_key"] = value
        prompted.append(value)
    elif getattr(args, "prompt_bearer_token", False):
        value = getpass.getpass("Bearer token: ")
        if not value:
            raise _CommandError("Credential prompt was empty.")
        flags["bearer_token"] = value
        prompted.append(value)
    if getattr(args, "no_sidecar", False):
        flags["artifacts"] = {"sidecar": False}
    try:
        return SurveyScribeConfig.resolve_cli(flags=flags, config_path=args.config)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as error:
        raise _CommandError(redact_exception(error, sensitive_values=tuple(prompted))) from None


def _config_secrets(config: SurveyScribeConfig) -> tuple[str, ...]:
    return tuple(
        secret.get_secret_value()
        for secret in (config.api_key, config.bearer_token)
        if secret is not None
    )


def _safe_error(error: BaseException, config: SurveyScribeConfig) -> str:
    return redact_exception(error, sensitive_values=_config_secrets(config))


def _convert_command(args: argparse.Namespace) -> int:
    config = _configuration(args)
    try:
        with _create_client(config) as client:
            result = client.convert(args.input)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as error:
        raise _CommandError(_safe_error(error, config)) from None

    sidecar = config.artifacts.sidecar
    if result.status is ResultStatus.failed:
        _write_result_summary(result, stream=sys.stderr, config=config)
        return _EXIT_ERROR
    if result.status is ResultStatus.partial and not sidecar:
        _write_result_summary(result, stream=sys.stderr, config=config)
        _write_terminal_error(
            "PARTIAL_REQUIRES_SIDECAR",
            "Partial output requires a diagnostic sidecar; remove --no-sidecar.",
        )
        return _EXIT_ERROR
    try:
        written = result.write(
            args.output_dir,
            sidecar=sidecar,
            overwrite=args.overwrite,
        )
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as error:
        _write_result_summary(result, stream=sys.stderr, config=config)
        _write_terminal_error(
            getattr(error, "code", "ARTIFACT_WRITE_FAILED"), _safe_error(error, config)
        )
        return _EXIT_ERROR

    stream = sys.stderr if args.strict and written.status is ResultStatus.partial else sys.stdout
    _write_result_summary(written, stream=stream, config=config)
    return _EXIT_ERROR if args.strict and written.status is ResultStatus.partial else _EXIT_OK


def _batch_command(args: argparse.Namespace) -> int:
    config = _configuration(args)
    try:
        with _reserve_batch_manifest(args.output_dir, overwrite=args.overwrite):
            return _run_reserved_batch(args, config)
    except (ArtifactCollisionError, ArtifactWriteError) as error:
        _write_terminal_error(
            getattr(error, "code", "ARTIFACT_WRITE_FAILED"),
            _safe_error(error, config),
        )
        return _EXIT_ERROR


def _run_reserved_batch(args: argparse.Namespace, config: SurveyScribeConfig) -> int:
    try:
        with _create_client(config) as client:
            results = client.convert_many(args.inputs)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as error:
        raise _CommandError(_safe_error(error, config)) from None
    if len(results) != len(args.inputs):
        raise _CommandError("SurveyScribe returned an invalid batch result count.")

    sidecar = config.artifacts.sidecar
    invalid_sidecar = not sidecar and any(
        result.status is ResultStatus.partial for result in results
    )
    records: list[dict[str, Any]] = []
    write_failed = False
    for index, (source, result) in enumerate(zip(args.inputs, results, strict=True)):
        written = result
        write_error: BaseException | None = None
        result_sidecar_invalid = not sidecar and result.status is ResultStatus.partial
        if result.status is not ResultStatus.failed and not result_sidecar_invalid:
            try:
                written = result.write(
                    args.output_dir,
                    sidecar=sidecar,
                    overwrite=args.overwrite,
                )
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as error:
                write_error = error
                write_failed = True
        records.append(
            _batch_record(
                index=index,
                source=source,
                result=written,
                output_dir=args.output_dir,
                write_error=write_error,
                invalid_sidecar=result_sidecar_invalid,
                sensitive_values=_config_secrets(config),
            )
        )
        stream = (
            sys.stderr
            if write_error is not None
            or result.status is ResultStatus.failed
            or (args.strict and result.status is ResultStatus.partial)
            or (invalid_sidecar and result.status is ResultStatus.partial)
            else sys.stdout
        )
        _write_result_summary(written, stream=stream, config=config, index=index)
        if write_error is not None:
            _write_terminal_error(
                getattr(write_error, "code", "ARTIFACT_WRITE_FAILED"),
                _safe_error(write_error, config),
            )

    if invalid_sidecar:
        _write_terminal_error(
            "PARTIAL_REQUIRES_SIDECAR",
            "Batch contains partial output; remove --no-sidecar.",
        )

    manifest = {
        "schema_version": 1,
        "run_id": _new_batch_run_id(),
        "inputs": records,
    }
    try:
        manifest_path = _write_batch_manifest(
            args.output_dir,
            manifest,
            overwrite=args.overwrite,
        )
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as error:
        _write_terminal_error(
            getattr(error, "code", "ARTIFACT_WRITE_FAILED"),
            _safe_error(error, config),
        )
        return _EXIT_ERROR
    sys.stdout.write(
        f"batch_manifest={redact_text(str(manifest_path), sensitive_values=_config_secrets(config))}\n"
    )

    has_failed = any(result.status is ResultStatus.failed for result in results)
    has_partial = any(result.status is ResultStatus.partial for result in results)
    if write_failed or invalid_sidecar or has_failed or (args.strict and has_partial):
        return _EXIT_ERROR
    return _EXIT_OK


def _providers_command(_args: argparse.Namespace) -> int:
    sys.stdout.write("provider\tkind\tcapability evidence\tnotes\n")
    for provider, kind, evidence, notes in _PROVIDERS:
        sys.stdout.write(f"{provider}\t{kind}\t{evidence}\t{notes}\n")
    sys.stdout.write("verified model rows: none\n")
    return _EXIT_OK


def _config_check_command(args: argparse.Namespace) -> int:
    config = _configuration(args)
    try:
        with _create_client(config):
            pass
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as error:
        raise _CommandError(_safe_error(error, config)) from None
    model = redact_text(config.model or "<unset>", sensitive_values=_config_secrets(config))
    sys.stdout.write(
        f"configuration valid provider={config.provider} model={model} credential=configured\n"
    )
    return _EXIT_OK


def _write_result_summary(
    result: ExtractionResult[Any],
    *,
    stream: TextIO,
    config: SurveyScribeConfig,
    index: int | None = None,
) -> None:
    sensitive = _config_secrets(config)
    prefix = f"input={index} " if index is not None else ""
    survey_id = redact_text(result.survey_id or "<none>", sensitive_values=sensitive)
    codes = ",".join(
        redact_text(str(diagnostic.code), sensitive_values=sensitive)
        for diagnostic in result.diagnostics
    )
    stream.write(
        f"{prefix}status={result.status.value} survey_id={survey_id} "
        f"diagnostics={len(result.diagnostics)}"
        f"{f' codes={codes}' if codes else ''} failed_blocks={len(result.failed_blocks)}\n"
    )
    for artifact in result.artifacts:
        kind = redact_text(str(artifact.kind), sensitive_values=sensitive)
        path = redact_text(str(artifact.path), sensitive_values=sensitive)
        stream.write(f"{prefix}artifact {kind}={path}\n")


def _write_terminal_error(code: object, message: str) -> None:
    safe_code = redact_text(str(code))
    safe_message = redact_text(message)
    sys.stderr.write(f"error code={safe_code} message={safe_message}\n")


def _batch_record(
    *,
    index: int,
    source: Path,
    result: ExtractionResult[Any],
    output_dir: Path,
    write_error: BaseException | None,
    invalid_sidecar: bool,
    sensitive_values: tuple[str, ...],
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "index": index,
        "source_name": redact_text(source.name, sensitive_values=sensitive_values),
        "run_id": result.run_id,
        "survey_id": (
            redact_text(result.survey_id, sensitive_values=sensitive_values)
            if result.survey_id is not None
            else None
        ),
        "status": result.status.value,
        "diagnostics": [
            {"code": str(item.code), "severity": item.severity.value} for item in result.diagnostics
        ],
        "failed_block_count": len(result.failed_blocks),
        "artifacts": [
            {
                "kind": str(item.kind),
                "path": redact_text(
                    _relative_artifact_path(item.path, output_dir),
                    sensitive_values=sensitive_values,
                ),
                "sha256": item.sha256,
            }
            for item in result.artifacts
        ],
    }
    if write_error is not None:
        record["write_error"] = {
            "code": str(getattr(write_error, "code", "ARTIFACT_WRITE_FAILED")),
            "stage": getattr(write_error, "stage", None),
        }
    elif invalid_sidecar:
        record["write_error"] = {
            "code": "PARTIAL_REQUIRES_SIDECAR",
            "stage": "policy",
        }
    return record


def _relative_artifact_path(path: Path, output_dir: Path) -> str:
    try:
        return path.resolve().relative_to(output_dir.resolve()).as_posix()
    except ValueError:
        return path.name


def _write_batch_manifest(
    output_dir: Path,
    manifest: Mapping[str, Any],
    *,
    overwrite: bool,
) -> Path:
    destination = output_dir.resolve() / _BATCH_MANIFEST
    content = (
        json.dumps(manifest, ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    temporary: Path | None = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(
            prefix=f".{_BATCH_MANIFEST}.",
            suffix=".tmp",
            dir=destination.parent,
        )
        temporary = Path(name)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temporary, destination)
            temporary = None
        else:
            try:
                os.link(temporary, destination)
            except FileExistsError:
                raise ArtifactCollisionError(
                    f"Batch manifest already exists: {destination}; pass --overwrite"
                ) from None
            temporary.unlink()
            temporary = None
    except ArtifactCollisionError:
        raise
    except OSError as error:
        raise ArtifactWriteError("batch_manifest", redact_exception(error)) from None
    finally:
        if temporary is not None:
            with suppress(FileNotFoundError):
                temporary.unlink()
    return destination


@contextmanager
def _reserve_batch_manifest(output_dir: Path, *, overwrite: bool) -> Iterator[None]:
    destination = output_dir.resolve() / _BATCH_MANIFEST
    reservation = destination.parent / _BATCH_RESERVATION
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(reservation, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ArtifactCollisionError(
            f"Batch manifest publication is already in progress: {destination}"
        ) from None
    except OSError as error:
        raise ArtifactWriteError("batch_manifest", redact_exception(error)) from None
    try:
        if not overwrite and destination.exists():
            raise ArtifactCollisionError(
                f"Batch manifest already exists: {destination}; pass --overwrite"
            )
        yield
    finally:
        os.close(descriptor)
        with suppress(FileNotFoundError):
            reservation.unlink()


def main(argv: Sequence[str] | None = None) -> int:
    """Run the installed CLI and return its process exit status."""
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return _EXIT_OK
    try:
        return int(handler(args))
    except _CommandError as error:
        _write_terminal_error("COMMAND_FAILED", str(error))
        return _EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
