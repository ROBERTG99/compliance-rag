"""Shared test configuration.

NFR-9: tests never reach the public internet. A socket guard allows loopback, unix sockets and
private (RFC 1918) addresses, which covers testcontainers and the compose test network.
Mark a test with ``@pytest.mark.allow_network`` to opt out (no test in this repo does).
"""

from __future__ import annotations

import ipaddress
import os
import random
import socket
from collections.abc import Iterator
from typing import Any

import pytest

os.environ.setdefault("DEMO_MODE", "offline")
os.environ.setdefault("CRAG_LLM_PROVIDER", "fake")
for _key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "COHERE_API_KEY"):
    os.environ.pop(_key, None)

_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex


def _allowed(address: Any) -> bool:
    if isinstance(address, (str, bytes)):  # unix socket path
        return True
    host = address[0]
    if isinstance(host, bytes):
        host = host.decode()
    if host in {"localhost", "host.docker.internal"}:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        try:
            ip = ipaddress.ip_address(socket.gethostbyname(host))
        except OSError:
            return False
    return ip.is_loopback or ip.is_private or ip.is_link_local


def _guarded_connect(self: socket.socket, address: Any) -> None:
    if not _allowed(address):
        raise RuntimeError(f"network access blocked by test socket guard: {address!r}")
    _real_connect(self, address)


def _guarded_connect_ex(self: socket.socket, address: Any) -> int:
    if not _allowed(address):
        raise RuntimeError(f"network access blocked by test socket guard: {address!r}")
    return _real_connect_ex(self, address)


socket.socket.connect = _guarded_connect  # type: ignore[method-assign]
socket.socket.connect_ex = _guarded_connect_ex  # type: ignore[method-assign]


@pytest.fixture(autouse=True)
def _seed_everything() -> Iterator[None]:
    random.seed(2026)
    try:
        import numpy as np

        np.random.seed(2026)
    except ImportError:  # pragma: no cover
        pass
    yield
