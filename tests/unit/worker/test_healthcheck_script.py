"""`scripts/worker_healthcheck.py`: the worker container's healthcheck without importing the worker."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from arq.constants import default_queue_name, health_check_key_suffix

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "worker_healthcheck.py"


def _run(redis_url: str, *flags: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "CRAG_REDIS_URL": redis_url}
    return subprocess.run(
        [sys.executable, *flags, str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_it_imports_neither_redis_nor_arq_nor_the_app() -> None:
    result = _run("redis://127.0.0.1:1/0", "-X", "importtime")  # nothing listens on port 1
    imported = {line.split("|")[-1].strip() for line in result.stderr.splitlines() if "|" in line}
    assert not {m for m in imported if m.split(".")[0] in {"redis", "arq", "compliance_rag", "asyncio"}}


def test_it_reads_arq_s_own_health_key() -> None:
    assert f'"{default_queue_name}{health_check_key_suffix}"' in SCRIPT.read_text(encoding="utf-8")


def test_unreachable_redis_is_unhealthy() -> None:
    assert _run("redis://127.0.0.1:1/0").returncode == 1
