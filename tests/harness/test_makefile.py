"""Makefile exposes every target from BUILD.md §16 (T-02)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

BLOCK_H = [
    "bootstrap",
    "up",
    "down",
    "seed",
    "demo",
    "logs",
    "check-fast",
    "test",
    "test-docker",
    "e2e",
    "eval",
    "eval-live",
    "bench",
    "lint",
    "typecheck",
    "security",
    "verify",
    "verify-clean",
    "docs",
    "clean",
]
PROJECT = [
    "migrate",
    "corpus",
    "fit-reranker",
    "reindex",
    "eval-ablation",
    "redteam",
    "calibrate-judge",
    "record-fixtures",
    "replay-failed-jobs",
]


def _targets() -> set[str]:
    text = (ROOT / "Makefile").read_text()
    return set(re.findall(r"^([a-z][a-z0-9-]*):", text, flags=re.M))


def test_block_h_targets_exist() -> None:
    missing = [t for t in BLOCK_H + PROJECT if t not in _targets()]
    assert not missing, missing


def test_targets_are_phony() -> None:
    text = (ROOT / "Makefile").read_text().replace("\\\n", " ")
    phony = set(" ".join(re.findall(r"^\.PHONY:(.*)$", text, flags=re.M)).split())
    assert set(BLOCK_H + PROJECT) <= phony


def test_socket_guard_blocks_public_hosts() -> None:
    import socket

    import pytest

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(RuntimeError, match="network access blocked"):
            s.connect(("93.184.216.34", 443))
    finally:
        s.close()
