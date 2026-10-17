"""Latency budgets: p95 of samples against a limit, with the numbers written to `evals/reports/bench.json`."""

from __future__ import annotations

import asyncio
import json
import math
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "evals" / "reports" / "bench.json"


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def summary(values: list[float], budget_ms: float) -> dict[str, Any]:
    p95 = percentile(values, 0.95)
    return {
        "n": len(values),
        "p50_ms": round(percentile(values, 0.5), 1),
        "p95_ms": round(p95, 1),
        "max_ms": round(max(values), 1),
        "budget_ms": budget_ms,
        "passed": p95 < budget_ms,
    }


def assert_budget(name: str, values: list[float], budget_ms: float) -> dict[str, Any]:
    assert values, f"{name}: no samples"
    result = summary(values, budget_ms)
    assert result["passed"], f"{name}: p95 {result['p95_ms']} ms is not under {budget_ms} ms ({result})"
    return result


async def timed(call: Callable[[], Awaitable[Any]]) -> float:
    started = time.perf_counter()
    await call()
    return (time.perf_counter() - started) * 1000


async def run_concurrently(calls: list[Callable[[], Awaitable[Any]]], concurrency: int) -> list[Any]:
    sem = asyncio.Semaphore(concurrency)

    async def one(call: Callable[[], Awaitable[Any]]) -> Any:
        async with sem:
            return await call()

    return await asyncio.gather(*(one(c) for c in calls))


def record(name: str, result: dict[str, Any], **context: Any) -> None:
    data = json.loads(REPORT.read_text(encoding="utf-8")) if REPORT.exists() else {}
    data[name] = {**result, **context, "measured_at": datetime.now(UTC).isoformat(timespec="seconds")}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
