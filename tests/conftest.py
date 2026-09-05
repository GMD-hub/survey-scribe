"""Shared pytest configuration."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1"})


def _deny_network(*_args: object, **_kwargs: object) -> None:
    raise RuntimeError("network access denied by the test fixture")


@pytest.fixture(autouse=True)
def deny_network_for_loopback_marked_tests(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Permit event-loop setup but deny network APIs during marked tests."""
    marker = request.node.get_closest_marker("allow_hosts")
    if marker is None:
        return
    allowed = marker.args[0]
    if not isinstance(allowed, list) or not set(allowed).issubset(_LOOPBACK_HOSTS):
        raise AssertionError("allow_hosts markers must contain only literal loopback addresses")
    monkeypatch.setattr(socket, "create_connection", _deny_network)
    monkeypatch.setattr(socket, "getaddrinfo", _deny_network)
    monkeypatch.setattr(socket, "gethostbyname", _deny_network)
    monkeypatch.setattr(socket, "gethostbyname_ex", _deny_network)
    monkeypatch.setattr(socket.socket, "connect", _deny_network)
    monkeypatch.setattr(socket.socket, "connect_ex", _deny_network)
    monkeypatch.setattr(socket.socket, "sendto", _deny_network)


@pytest.fixture
def repository_root() -> Path:
    """Return the repository root."""
    return Path(__file__).resolve().parents[1]
