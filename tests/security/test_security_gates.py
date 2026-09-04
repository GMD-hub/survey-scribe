"""Security collection and authoritative offline verification tests."""

from __future__ import annotations

import json
import socket
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts.run_security_gates import _fingerprint, collect, network_blocked, scanners, verify

NOW = datetime(2026, 9, 3, tzinfo=UTC)


def _reports(root: Path, *, collected_at: datetime = NOW) -> Path:
    root.mkdir()
    payloads = {
        "dependency": {"dependencies": [], "fixes": []},
        "static": {"errors": [], "generated_at": collected_at.isoformat(), "results": []},
        "secret": {"version": "1.5.0", "plugins_used": [], "results": {}},
    }
    for scanner, payload in payloads.items():
        boundary = (
            "network-enabled: advisory database collection only"
            if scanner == "dependency"
            else "tool-offline: local evidence"
        )
        (root / f"{scanner}.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "scanner": scanner,
                    "collected_at": collected_at.isoformat(),
                    "network_boundary": boundary,
                    "command": [scanner],
                    "exit_code": 0,
                    "report": payload,
                }
            ),
            encoding="utf-8",
        )
    return root


def _allowlist(root: Path, entries: str = "entries = []\n") -> Path:
    path = root / "allowlist.toml"
    path.write_text(
        "schema_version = 1\n"
        'owner = "Security owner"\n'
        'rationale = "Reviewed test policy"\n'
        'expires = "2027-09-03"\n'
        f"{entries}",
        encoding="utf-8",
    )
    return path


def _baseline(root: Path) -> Path:
    path = root / ".secrets.baseline"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tool": "detect-secrets",
                "tool_version": "1.5.0",
                "owner": "Security owner",
                "rationale": "Reviewed test policy",
                "expires": "2027-09-03",
                "entries": [],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_verify_passes_complete_fresh_reports_without_network(tmp_path: Path) -> None:
    reports = _reports(tmp_path / "reports")
    allowlist = _allowlist(tmp_path)
    assert verify(reports, allowlist, secret_baseline=_baseline(tmp_path), now=NOW) == []

    with network_blocked(), pytest.raises(RuntimeError, match="network access is blocked"):
        socket.create_connection(("example.invalid", 443))


def test_collection_keeps_machine_reports_when_scanners_find_issues(
    repository_root: Path, tmp_path: Path
) -> None:
    reports = {
        "pip-audit": {"dependencies": [], "fixes": []},
        "bandit": {"errors": [], "results": [{"test_id": "B999"}]},
        "detect-secrets": {"results": {}},
    }

    def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            1 if command[0] in {"pip-audit", "bandit"} else 0,
            stdout=json.dumps(reports[command[0]]),
            stderr="finding",
        )

    output = tmp_path / "reports"
    assert collect(output, root=repository_root, runner=runner, now=NOW) == []
    assert json.loads((output / "dependency.json").read_text())["exit_code"] == 1
    assert json.loads((output / "static.json").read_text())["report"]["results"]


def test_collection_does_not_claim_an_enforced_child_process_network_sandbox(
    repository_root: Path, tmp_path: Path
) -> None:
    seen_boundaries: list[str] = []

    def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        reports = {
            "pip-audit": {"dependencies": [], "fixes": []},
            "bandit": {"errors": [], "results": []},
            "detect-secrets": {"results": {}},
        }
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(reports[command[0]]))

    output = tmp_path / "reports"
    assert collect(output, root=repository_root, runner=runner, now=NOW) == []
    for name in ("static", "secret"):
        boundary = json.loads((output / f"{name}.json").read_text())["network_boundary"]
        seen_boundaries.append(boundary)
        assert boundary.startswith("tool-offline:")
        assert "network-blocked" not in boundary
    assert len(set(seen_boundaries)) == 2
    configured = {scanner.name: scanner for scanner in scanners(repository_root)}
    assert configured["static"].command[0] == "bandit"
    assert configured["secret"].command[0] == "detect-secrets"
    assert "--no-verify" in configured["secret"].command


@pytest.mark.parametrize("failure", ["missing", "malformed", "stale"])
def test_verify_rejects_missing_malformed_and_stale_reports(tmp_path: Path, failure: str) -> None:
    reports = _reports(
        tmp_path / "reports",
        collected_at=NOW - timedelta(days=2) if failure == "stale" else NOW,
    )
    if failure == "missing":
        (reports / "static.json").unlink()
    elif failure == "malformed":
        (reports / "static.json").write_text("not-json", encoding="utf-8")

    errors = verify(reports, _allowlist(tmp_path), secret_baseline=_baseline(tmp_path), now=NOW)

    assert any(failure in error or "incomplete" in error for error in errors)


def test_verify_rejects_wrong_report_shape(tmp_path: Path) -> None:
    reports = _reports(tmp_path / "reports")
    envelope = json.loads((reports / "dependency.json").read_text(encoding="utf-8"))
    envelope["report"] = {"unexpected": []}
    (reports / "dependency.json").write_text(json.dumps(envelope), encoding="utf-8")

    errors = verify(reports, _allowlist(tmp_path), secret_baseline=_baseline(tmp_path), now=NOW)

    assert "dependency report shape is invalid" in errors


@pytest.mark.parametrize(
    "entry",
    [
        '[[entries]]\nscanner = "secret"\nfingerprint = "bad"\nowner = ""\nrationale = ""\nexpires = "bad"\n',
        '[[entries]]\nscanner = "secret"\nfingerprint = "{}"\nowner = "Security"\nrationale = "Reviewed synthetic fixture"\nexpires = "2026-01-01"\n'.format(
            "0" * 64
        ),
    ],
)
def test_verify_rejects_invalid_or_expired_allowlist(tmp_path: Path, entry: str) -> None:
    errors = verify(
        _reports(tmp_path / "reports"),
        _allowlist(tmp_path, entry),
        secret_baseline=_baseline(tmp_path),
        now=NOW,
    )

    assert any("allowlist entry" in error for error in errors)


def test_secret_finding_requires_an_exact_reviewed_allowlist_entry(tmp_path: Path) -> None:
    reports = _reports(tmp_path / "reports")
    envelope = json.loads((reports / "secret.json").read_text(encoding="utf-8"))
    finding = {
        "id": "Secret Keyword",
        "path": "config.py",
        "line": 7,
        "secret_hash": "sha256:test",
    }
    envelope["report"]["results"] = {
        "config.py": [{"type": "Secret Keyword", "line_number": 7, "hashed_secret": "sha256:test"}]
    }
    (reports / "secret.json").write_text(json.dumps(envelope), encoding="utf-8")

    errors = verify(reports, _allowlist(tmp_path), secret_baseline=_baseline(tmp_path), now=NOW)

    assert errors == [f"unallowed secret finding {_fingerprint('secret', finding)}"]
