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


def test_blas_kernels_are_pinned_where_the_embedder_is_fitted() -> None:
    # OpenBLAS picks kernels per CPU (AVX-512 here, AVX2 on GitHub runners) and they round differently, so the
    # fitted LSA model differed between machines; Haswell kernels run on every AVX2 x86-64 host
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "export OPENBLAS_CORETYPE ?= Haswell" in makefile
    for dockerfile in ("docker/api.Dockerfile", "docker/tests.Dockerfile"):
        assert "OPENBLAS_CORETYPE=Haswell" in (ROOT / dockerfile).read_text(encoding="utf-8"), dockerfile
