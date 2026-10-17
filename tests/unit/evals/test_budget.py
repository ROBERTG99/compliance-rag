"""`make eval-live`: estimate first, never spend past LIVE_EVAL_BUDGET_USD (BUILD.md §11, T-42)."""

from __future__ import annotations

from typing import Any

import pytest

from scripts.eval_live import Budget, refuse_offline, run_live


class CostlyTarget:
    def __init__(self, cost: float | None) -> None:
        self.cost, self.calls = cost, 0

    async def __call__(self, row: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        return {"answer": "x", "cost_usd": self.cost}


ROWS = [{"id": f"q-{i}", "input": {"question": "q"}} for i in range(10)]


async def test_stops_at_budget() -> None:
    target = CostlyTarget(0.02)
    run = await run_live(ROWS, target, Budget(0.05), estimate_usd=0.02)
    # 0.02 + 0.02 = 0.04; a third case (estimated 0.02) would pass 0.05
    assert target.calls == 2 and run.stopped and run.spent_usd == pytest.approx(0.04)
    assert [c["id"] for c in run.cases] == ["q-0", "q-1"]
    assert run.spent_usd <= 0.05


async def test_unknown_cost_is_charged_at_the_estimate() -> None:
    target = CostlyTarget(None)
    run = await run_live(ROWS, target, Budget(0.1), estimate_usd=0.03)
    assert target.calls == 3 and run.spent_usd == pytest.approx(0.09)


async def test_a_case_that_costs_more_than_estimated_still_stops_the_run() -> None:
    target = CostlyTarget(0.08)
    run = await run_live(ROWS, target, Budget(0.1), estimate_usd=0.01)
    assert target.calls == 1 and run.stopped


def test_offline_configuration_is_refused() -> None:
    assert refuse_offline("fake", has_key=False) is not None
    assert refuse_offline("anthropic", has_key=False) is not None
    assert refuse_offline("anthropic", has_key=True) is None
