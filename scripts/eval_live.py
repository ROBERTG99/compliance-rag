"""`make eval-live`: the RAG suite against a real model, within LIVE_EVAL_BUDGET_USD (BUILD.md §11).

    CRAG_LLM_PROVIDER=anthropic ANTHROPIC_API_KEY=... LIVE_EVAL_BUDGET_USD=2 uv run python scripts/eval_live.py
    make record-fixtures   # the same with CRAG_RECORD_CASSETTES=1: responses become offline cassettes

Prints the estimated cost of the whole split first, then runs one question at a time and stops before the
next question would pass the budget (an unknown cost is charged at the estimate). Writes
`evals/reports/runs/live.json` (gitignored); live numbers never go into `evals/REPORT.md` automatically.
Refuses to run offline (FakeLLM) or without provider credentials.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "evals" / "suites" / "rag.yaml"
# rough per-question token use of the generate route (system + 8 excerpts in, claims + thinking out)
EST_GENERATE_IN, EST_GENERATE_OUT = 4_000, 2_000
EST_CONDENSE_IN, EST_CONDENSE_OUT = 600, 200


@dataclass
class Budget:
    limit_usd: float
    spent_usd: float = 0.0

    def can_afford(self, estimate_usd: float) -> bool:
        return self.spent_usd + estimate_usd <= self.limit_usd + 1e-12

    def charge(self, cost_usd: float) -> None:
        self.spent_usd += cost_usd


@dataclass
class LiveRun:
    cases: list[dict[str, Any]] = field(default_factory=list)
    spent_usd: float = 0.0
    stopped: bool = False


Target = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


async def run_live(
    rows: list[dict[str, Any]], target: Target, budget: Budget, *, estimate_usd: float
) -> LiveRun:
    """Run questions in order while the next one fits the budget. The next question is assumed to cost the
    larger of the estimate and the costliest question so far; only a single question that costs more than
    the remaining budget can overshoot it."""
    run = LiveRun()
    next_cost = estimate_usd
    for row in rows:
        if not budget.can_afford(next_cost):
            run.stopped = True
            break
        output = await target(row)
        cost = output.get("cost_usd")
        actual = float(cost) if cost is not None else estimate_usd
        budget.charge(actual)
        next_cost = max(next_cost, actual)
        run.cases.append({"id": row["id"], "output": output})
    run.spent_usd = budget.spent_usd
    return run


def refuse_offline(provider: str, *, has_key: bool) -> str | None:
    if provider == "fake":
        return "CRAG_LLM_PROVIDER=fake: live evals need CRAG_LLM_PROVIDER=anthropic or bedrock"
    if not has_key:
        return f"no credentials for {provider}: set ANTHROPIC_API_KEY (or the Bedrock credentials)"
    return None


def estimate_per_question(settings: Any) -> float:
    from compliance_rag.llm.gateway import estimate_cost

    return estimate_cost(settings.model_generate, EST_GENERATE_IN, EST_GENERATE_OUT) + estimate_cost(
        settings.model_fast, EST_CONDENSE_IN, EST_CONDENSE_OUT
    )


async def amain(split: str, limit: int | None) -> int:
    from evalgate.runner import aggregate, load_rows
    from evalgate.suite import load_suite, resolve

    from compliance_rag.evals.target import RagTarget
    from compliance_rag.settings import get_settings

    settings = get_settings()
    has_key = settings.anthropic_api_key is not None if settings.llm_provider == "anthropic" else True
    reason = refuse_offline(settings.llm_provider, has_key=has_key)
    if reason:
        print(f"eval-live: {reason}", file=sys.stderr)
        return 2
    suite = load_suite(SUITE)
    rows, sha = load_rows(suite.dataset, split)
    rows = rows[:limit] if limit else rows
    per_question = estimate_per_question(settings)
    print(
        f"estimated cost: {len(rows)} questions × ${per_question:.4f} ≈ ${len(rows) * per_question:.2f}; "
        f"budget ${settings.live_eval_budget_usd:.2f}"
        + (" (recording cassettes)" if settings.record_cassettes else "")
    )
    target = RagTarget(settings)
    await target.setup()
    started = time.perf_counter()
    try:
        run = await run_live(rows, target, Budget(settings.live_eval_budget_usd), estimate_usd=per_question)
        described = target.describe()
    finally:
        await target.close()
    by_id = {r["id"]: r for r in rows}
    metrics = {}
    for spec in suite.metrics:
        fn = resolve(spec.fn)
        value, n = aggregate(spec, [fn(by_id[c["id"]], c["output"]) for c in run.cases])
        metrics[spec.name] = {
            "value": value,
            "n": n,
            "unit": spec.unit,
            "threshold": spec.threshold and spec.threshold.describe(),
        }
    report = {
        "schema": "crag.live.v1",
        "split": split,
        "dataset_sha256": sha,
        "target": described,
        "questions_run": len(run.cases),
        "questions_total": len(rows),
        "stopped_at_budget": run.stopped,
        "spent_usd": round(run.spent_usd, 4),
        "budget_usd": settings.live_eval_budget_usd,
        "duration_s": round(time.perf_counter() - started, 1),
        "metrics": metrics,
    }
    out = ROOT / "evals" / "reports" / "runs" / "live.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    stop = " (stopped at the budget)" if run.stopped else ""
    print(
        f"ran {len(run.cases)}/{len(rows)} questions for ${run.spent_usd:.4f}{stop} → {out.relative_to(ROOT)}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", default="test", choices=["dev", "test"])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--record", action="store_true", help="record cassettes (sets CRAG_RECORD_CASSETTES)")
    args = parser.parse_args(argv)
    if args.record:
        import os

        os.environ["CRAG_RECORD_CASSETTES"] = "1"
    return asyncio.run(amain(args.split, args.limit or None))


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
