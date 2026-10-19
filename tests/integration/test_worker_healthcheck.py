"""The worker healthcheck script against a real Redis: healthy only while Arq's health key exists."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from redis import Redis

pytestmark = pytest.mark.integration

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "worker_healthcheck.py"
KEY = "arq:queue:health-check"


def _status(redis_url: str) -> int:
    env = {**os.environ, "CRAG_REDIS_URL": redis_url}
    return subprocess.run([sys.executable, str(SCRIPT)], env=env, timeout=30, check=False).returncode


def test_healthy_while_the_worker_records_its_health(redis_url: str) -> None:
    with Redis.from_url(redis_url) as client:
        client.delete(KEY)
        assert _status(redis_url) == 1  # no worker has recorded health in this DB
        client.set(KEY, "Oct-18 17:30:55 j_complete=1 j_failed=0 j_retried=0 j_ongoing=0 queued=0", ex=11)
        assert _status(redis_url) == 0
        client.delete(KEY)
    assert _status(redis_url) == 1
