"""With several API worker processes, /metrics aggregates every process (prometheus multiprocess mode)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
INC = "from compliance_rag.obs.metrics import ACL_POSTCHECK_VIOLATIONS as c; c.inc()"
SCRAPE = (
    "import asyncio; from compliance_rag.api.routes.health import metrics; "
    "print(asyncio.run(metrics()).body.decode())"
)


def _run(code: str, env: dict[str, str]) -> str:
    return subprocess.run(
        [sys.executable, "-c", code], env=env, cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout


def test_counters_from_every_worker_process_are_summed(tmp_path: Path) -> None:
    env = {**os.environ, "PROMETHEUS_MULTIPROC_DIR": str(tmp_path)}
    _run(INC, env)  # worker process 1
    _run(INC, env)  # worker process 2
    scraped = _run(SCRAPE, env)  # whichever process serves the scrape sees both
    line = next(x for x in scraped.splitlines() if x.startswith("crag_acl_postcheck_violations_total "))
    assert float(line.split()[1]) == 2.0
