"""Run a suite over one dataset split and produce an ``evalgate.report.v1`` dictionary."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import math
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from evalgate.suite import MetricSpec, Suite, resolve

SCHEMA = "evalgate.report.v1"


class Target(Protocol):
    async def setup(self) -> None: ...
    async def __call__(self, row: dict[str, Any]) -> dict[str, Any]: ...
    async def close(self) -> None: ...
    def describe(self) -> dict[str, Any]: ...


def load_rows(path: str | Path, split: str | None) -> tuple[list[dict[str, Any]], str]:
    raw = Path(path).read_bytes()
    rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    if split and split != "all":
        rows = [r for r in rows if r.get("split") == split]
    return rows, hashlib.sha256(raw).hexdigest()


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def aggregate(spec: MetricSpec, scores: list[Any]) -> tuple[float | None, int]:
    present = [s for s in scores if s is not None]
    if not present:
        return None, 0
    if spec.aggregate == "ratio":
        num = sum(float(s[0]) for s in present)
        den = sum(float(s[1]) for s in present)
        return (num / den if den else 0.0), int(den)
    values = [float(s) for s in present]
    if spec.aggregate == "max":
        return max(values), len(values)
    if spec.aggregate == "p95":
        return _p95(values), len(values)
    return sum(values) / len(values), len(values)


async def run_suite(
    suite: Suite, split: str | None, *, limit: int | None = None, target: Target | None = None
) -> dict[str, Any]:
    rows, sha = load_rows(suite.dataset, split)
    if limit:
        rows = rows[:limit]
    owned = target is None
    target = target or resolve(suite.target)()
    fns = {m.name: resolve(m.fn) for m in suite.metrics}
    await target.setup()
    sem = asyncio.Semaphore(suite.concurrency)
    started = time.perf_counter()

    async def one(row: dict[str, Any]) -> dict[str, Any]:
        async with sem:
            try:
                output = await target(row)
            except Exception as exc:  # recorded, and it fails the run: an eval must not silently skip cases
                return {"id": row["id"], "error": f"{type(exc).__name__}: {exc}"[:500], "scores": {}}
        scores: dict[str, Any] = {}
        for name, fn in fns.items():
            value = fn(row, output)
            scores[name] = (await value) if inspect.isawaitable(value) else value
        return {"id": row["id"], "error": None, "scores": scores, "output": output}

    try:
        cases = await asyncio.gather(*(one(r) for r in rows))
        described = target.describe()
    finally:
        if owned:
            await target.close()
    metrics: dict[str, Any] = {}
    for spec in suite.metrics:
        value, n = aggregate(spec, [c["scores"].get(spec.name) for c in cases if c["error"] is None])
        passed = value is not None and (spec.threshold is None or spec.threshold.holds(value))
        metrics[spec.name] = {
            "value": value,
            "n": n,
            "unit": spec.unit,
            "threshold": spec.threshold.model_dump(exclude_none=True) if spec.threshold else None,
            "threshold_text": spec.threshold.describe() if spec.threshold else "",
            "gate": spec.gate,
            "hard": spec.hard,
            "higher_is_better": spec.higher_is_better,
            "passed": passed,
            "description": spec.description,
        }
    errors = [c for c in cases if c["error"]]
    return {
        "schema": SCHEMA,
        "suite": suite.name,
        "description": suite.description,
        "split": split or "all",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "duration_s": round(time.perf_counter() - started, 1),
        "dataset": {"path": suite.dataset, "sha256": sha, "n": len(rows)},
        "target": described,
        "metrics": metrics,
        "errors": len(errors),
        "passed": not errors and all(m["passed"] for m in metrics.values() if m["gate"]),
        "cases": [
            {k: v for k, v in c.items() if k != "output"} | {"output": _slim(c.get("output"))} for c in cases
        ],
    }


def _slim(output: dict[str, Any] | None) -> dict[str, Any] | None:
    """Keep what a reader needs to audit a case; drop chunk text (large, and re-derivable)."""
    if output is None:
        return None
    keep = ("abstained", "answer", "claims", "versions", "degraded", "abstain_reason", "retrieval_ms")
    slim = {k: output[k] for k in keep if k in output}
    slim["retrieved"] = [
        {k: c.get(k) for k in ("chunk_id", "document_id", "version", "rerank")}
        for c in output.get("retrieved", [])
    ]
    return slim
