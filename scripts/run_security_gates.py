"""Collect security scanner evidence and verify it with one offline policy exit."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from loguru import logger

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SECRET_BASELINE = REPOSITORY_ROOT / ".secrets.baseline"
REPORT_SCHEMA_VERSION = 1
MAX_REPORT_AGE = timedelta(hours=24)
EXPECTED_SCANNERS = frozenset({"dependency", "static", "secret"})
FINDING_EXIT_CODES = {
    "dependency": frozenset({0, 1}),
    "static": frozenset({0, 1}),
    "secret": frozenset({0}),
}


@dataclass(frozen=True)
class Scanner:
    name: str
    network_boundary: str
    command: tuple[str, ...]


def _deny_network(*_args: object, **_kwargs: object) -> None:
    raise RuntimeError("network access is blocked during security verification")


@contextmanager
def network_blocked():
    """Block Python socket connections while offline policy executes."""
    create_connection = socket.create_connection
    connect = socket.socket.connect
    connect_ex = socket.socket.connect_ex
    socket.create_connection = _deny_network
    socket.socket.connect = _deny_network  # type: ignore[method-assign]
    socket.socket.connect_ex = _deny_network  # type: ignore[method-assign,assignment]
    try:
        yield
    finally:
        socket.create_connection = create_connection
        socket.socket.connect = connect  # type: ignore[method-assign]
        socket.socket.connect_ex = connect_ex  # type: ignore[method-assign,assignment]


def _tracked_files(root: Path) -> tuple[str, ...]:
    completed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        check=True,
        capture_output=True,
        timeout=30,
    )
    return tuple(
        decoded
        for path in completed.stdout.split(b"\0")
        if path
        and (decoded := path.decode("utf-8"))
        not in {".secrets.baseline", "security/allowlist.toml"}
    )


def scanners(root: Path) -> tuple[Scanner, ...]:
    tracked = _tracked_files(root)
    return (
        Scanner(
            name="dependency",
            network_boundary="network-enabled: advisory database collection only",
            command=(
                "pip-audit",
                "--format=json",
                "--progress-spinner=off",
                "--local",
                "--skip-editable",
            ),
        ),
        Scanner(
            name="static",
            network_boundary="tool-offline: Bandit performs local source analysis",
            command=(
                "bandit",
                "-q",
                "-ll",
                "-r",
                "src",
                "scripts",
                "docling_pipeline.py",
                "-f",
                "json",
            ),
        ),
        Scanner(
            name="secret",
            network_boundary="tool-offline: detect-secrets scans tracked files with --no-verify",
            command=(
                "detect-secrets",
                "scan",
                "--force-use-all-plugins",
                "--no-verify",
                *tracked,
            ),
        ),
    )


def _atomic_json(path: Path, value: object) -> None:
    content = (json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode()
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def collect(
    output_dir: Path,
    *,
    root: Path = REPOSITORY_ROOT,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    now: datetime | None = None,
) -> list[str]:
    """Run scanners and preserve valid JSON output regardless of findings."""
    errors: list[str] = []
    output_dir.mkdir(parents=True, exist_ok=True)
    collected_at = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
    for scanner in scanners(root):
        logger.info("{} collection boundary: {}", scanner.name, scanner.network_boundary)
        try:
            completed = runner(
                list(scanner.command),
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
                timeout=300,
            )
            payload = json.loads(completed.stdout)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            errors.append(
                f"{scanner.name} scanner did not produce valid JSON: {type(exc).__name__}"
            )
            payload = None
            return_code = None
        else:
            return_code = completed.returncode
            if return_code not in FINDING_EXIT_CODES[scanner.name]:
                errors.append(f"{scanner.name} scanner failed with exit code {return_code}")
        envelope = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "scanner": scanner.name,
            "collected_at": collected_at,
            "network_boundary": scanner.network_boundary,
            "command": list(scanner.command[:1]),
            "exit_code": return_code,
            "report": payload,
        }
        _atomic_json(output_dir / f"{scanner.name}.json", envelope)
    return errors


def _fingerprint(scanner: str, finding: Mapping[str, object]) -> str:
    payload = json.dumps(
        {"scanner": scanner, **finding}, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _dependency_findings(report: object) -> list[dict[str, object]]:
    if not isinstance(report, dict) or not isinstance(report.get("dependencies"), list):
        raise ValueError("dependency report shape is invalid")
    findings: list[dict[str, object]] = []
    for dependency in report["dependencies"]:
        if not isinstance(dependency, dict):
            raise ValueError("dependency report entry shape is invalid")
        if "skip_reason" in dependency:
            if not isinstance(dependency["skip_reason"], str):
                raise ValueError("dependency skip reason shape is invalid")
            continue
        if not isinstance(dependency.get("vulns"), list):
            raise ValueError("dependency report entry shape is invalid")
        for vulnerability in dependency["vulns"]:
            if not isinstance(vulnerability, dict) or not isinstance(vulnerability.get("id"), str):
                raise ValueError("dependency vulnerability shape is invalid")
            findings.append(
                {
                    "id": vulnerability["id"],
                    "package": dependency.get("name"),
                    "version": dependency.get("version"),
                }
            )
    return findings


def _static_findings(report: object) -> list[dict[str, object]]:
    if not isinstance(report, dict) or not isinstance(report.get("results"), list):
        raise ValueError("static report shape is invalid")
    findings: list[dict[str, object]] = []
    for result in report["results"]:
        if not isinstance(result, dict) or not isinstance(result.get("test_id"), str):
            raise ValueError("static finding shape is invalid")
        findings.append(
            {
                "id": result["test_id"],
                "path": result.get("filename"),
                "line": result.get("line_number"),
            }
        )
    return findings


def _secret_findings(report: object) -> list[dict[str, object]]:
    if not isinstance(report, dict) or not isinstance(report.get("results"), dict):
        raise ValueError("secret report shape is invalid")
    findings: list[dict[str, object]] = []
    for path, results in report["results"].items():
        if not isinstance(path, str) or not isinstance(results, list):
            raise ValueError("secret report entry shape is invalid")
        for result in results:
            if not isinstance(result, dict) or not isinstance(result.get("type"), str):
                raise ValueError("secret finding shape is invalid")
            findings.append(
                {
                    "id": result["type"],
                    "path": path,
                    "line": result.get("line_number"),
                    "secret_hash": result.get("hashed_secret"),
                }
            )
    return findings


FINDING_LOADERS: dict[str, Callable[[object], list[dict[str, object]]]] = {
    "dependency": _dependency_findings,
    "static": _static_findings,
    "secret": _secret_findings,
}


def _review_fields(data: Mapping[str, object], *, name: str, today: date) -> list[str]:
    errors: list[str] = []
    for field in ("owner", "rationale", "expires"):
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{name} requires nonempty {field}")
    if errors:
        return errors
    try:
        expiry = date.fromisoformat(str(data["expires"]))
    except ValueError:
        errors.append(f"{name} expiry must be ISO YYYY-MM-DD")
    else:
        if expiry < today:
            errors.append(f"{name} expired on {expiry.isoformat()}")
    return errors


def _load_allowlist(path: Path, *, today: date) -> tuple[set[tuple[str, str]], list[str]]:
    errors: list[str] = []
    try:
        with path.open("rb") as stream:
            data = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return set(), [f"allowlist cannot be loaded: {type(exc).__name__}"]
    if data.get("schema_version") != 1:
        errors.append("allowlist schema_version must equal 1")
    errors.extend(_review_fields(data, name="allowlist", today=today))
    entries = data.get("entries")
    if not isinstance(entries, list):
        return set(), [*errors, "allowlist entries must be an array"]
    allowed: set[tuple[str, str]] = set()
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            errors.append(f"allowlist entry {index} must be a table")
            continue
        for field in ("scanner", "fingerprint", "owner", "rationale", "expires"):
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                errors.append(f"allowlist entry {index} requires nonempty {field}")
        if errors and any(error.startswith(f"allowlist entry {index} ") for error in errors):
            continue
        if entry["scanner"] not in EXPECTED_SCANNERS:
            errors.append(f"allowlist entry {index} has unknown scanner")
        if len(entry["fingerprint"]) != 64 or any(
            character not in "0123456789abcdef" for character in entry["fingerprint"]
        ):
            errors.append(f"allowlist entry {index} fingerprint is invalid")
        try:
            expiry = date.fromisoformat(entry["expires"])
        except ValueError:
            errors.append(f"allowlist entry {index} expiry must be ISO YYYY-MM-DD")
        else:
            if expiry < today:
                errors.append(f"allowlist entry {index} expired on {expiry.isoformat()}")
        key = (entry["scanner"], entry["fingerprint"])
        if key in allowed:
            errors.append(f"allowlist entry {index} is duplicated")
        allowed.add(key)
    return allowed, errors


def _load_secret_baseline(
    path: Path, *, today: date
) -> tuple[set[tuple[str, str, str]], list[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return set(), [f"secret baseline cannot be loaded: {type(exc).__name__}"]
    if (
        not isinstance(data, dict)
        or data.get("schema_version") != 1
        or data.get("tool") != "detect-secrets"
        or data.get("tool_version") != "1.5.0"
    ):
        return set(), ["secret baseline shape or version is invalid"]
    errors = _review_fields(data, name="secret baseline", today=today)
    entries = data.get("entries")
    if not isinstance(entries, list):
        return set(), [*errors, "secret baseline entries must be an array"]
    baseline: set[tuple[str, str, str]] = set()
    for index, entry in enumerate(entries, start=1):
        if (
            not isinstance(entry, list)
            or len(entry) != 3
            or not all(isinstance(value, str) and value.strip() for value in entry)
        ):
            errors.append(f"secret baseline entry {index} shape is invalid")
            continue
        key = (entry[0], entry[1], entry[2])
        if key in baseline:
            errors.append(f"secret baseline entry {index} is duplicated")
        baseline.add(key)
    return baseline, errors


def verify(
    reports: Path,
    allowlist: Path,
    *,
    secret_baseline: Path = DEFAULT_SECRET_BASELINE,
    now: datetime | None = None,
) -> list[str]:
    """Return all offline policy errors from fresh collected reports."""
    with network_blocked():
        checked_at = (now or datetime.now(UTC)).astimezone(UTC)
        allowed, errors = _load_allowlist(allowlist, today=checked_at.date())
        baseline_secrets, baseline_errors = _load_secret_baseline(
            secret_baseline, today=checked_at.date()
        )
        errors.extend(baseline_errors)
        seen_scanners: set[str] = set()
        findings: list[tuple[str, str]] = []
        collected_secrets: set[tuple[str, str, str]] = set()
        for scanner in sorted(EXPECTED_SCANNERS):
            path = reports / f"{scanner}.json"
            try:
                envelope = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                errors.append(f"missing {scanner} report")
                continue
            except (OSError, json.JSONDecodeError):
                errors.append(f"malformed {scanner} report")
                continue
            if not isinstance(envelope, dict):
                errors.append(f"malformed {scanner} report envelope")
                continue
            if envelope.get("schema_version") != REPORT_SCHEMA_VERSION:
                errors.append(f"{scanner} report schema version is invalid")
            if envelope.get("scanner") != scanner:
                errors.append(f"{scanner} report scanner identity is invalid")
                continue
            seen_scanners.add(scanner)
            boundary = envelope.get("network_boundary")
            expected_boundary = "network-enabled:" if scanner == "dependency" else "tool-offline:"
            if not isinstance(boundary, str) or not boundary.startswith(expected_boundary):
                errors.append(f"{scanner} report network boundary is invalid")
            try:
                collected_at = datetime.fromisoformat(envelope["collected_at"])
                if collected_at.tzinfo is None:
                    raise ValueError
                age = checked_at - collected_at.astimezone(UTC)
                if age < timedelta(minutes=-5) or age > MAX_REPORT_AGE:
                    errors.append(f"{scanner} report is stale or future-dated")
            except (KeyError, TypeError, ValueError):
                errors.append(f"{scanner} report timestamp is invalid")
            if envelope.get("exit_code") not in FINDING_EXIT_CODES[scanner]:
                errors.append(f"{scanner} scanner did not complete successfully")
            try:
                scanner_findings = FINDING_LOADERS[scanner](envelope.get("report"))
            except ValueError as exc:
                errors.append(str(exc))
                continue
            if scanner == "secret":
                collected_secrets = {
                    (
                        str(finding["path"]),
                        str(finding["id"]),
                        str(finding["secret_hash"]),
                    )
                    for finding in scanner_findings
                }
                scanner_findings = [
                    finding
                    for finding in scanner_findings
                    if (
                        finding.get("path"),
                        finding.get("id"),
                        finding.get("secret_hash"),
                    )
                    not in baseline_secrets
                ]
            findings.extend(
                (scanner, _fingerprint(scanner, finding)) for finding in scanner_findings
            )
        if seen_scanners != EXPECTED_SCANNERS:
            errors.append("security report set is incomplete")
        for finding in findings:
            if finding not in allowed:
                errors.append(f"unallowed {finding[0]} finding {finding[1]}")
        unused = allowed - set(findings)
        for scanner, fingerprint in sorted(unused):
            errors.append(f"stale allowlist entry {scanner}:{fingerprint}")
        for path_value, secret_type, secret_hash in sorted(baseline_secrets - collected_secrets):
            errors.append(f"stale secret baseline entry {path_value}:{secret_type}:{secret_hash}")
        return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    collect_parser = subparsers.add_parser("collect")
    collect_parser.add_argument("--output-dir", type=Path, required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--reports", type=Path, required=True)
    verify_parser.add_argument("--allowlist", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logger.remove()
    logger.add(sys.stderr, format="{message}")
    if args.command == "collect":
        errors = collect(args.output_dir)
        if errors:
            for error in errors:
                logger.error(error)
            return 1
        logger.info("Security evidence collected; no policy decision was made")
        return 0
    errors = verify(args.reports, args.allowlist)
    if errors:
        for error in errors:
            logger.error(error)
        return 1
    logger.info("Authoritative offline security policy verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
