"""The budget check itself: an injected 400 ms delay must fail a 300 ms p95 budget."""

from __future__ import annotations

import asyncio

import pytest

from tests.perf.budget import assert_budget, percentile, run_concurrently, timed

pytestmark = pytest.mark.perf


async def test_budgets_fail_on_an_injected_400_ms_delay() -> None:
    async def fast() -> None:
        await asyncio.sleep(0.01)

    async def delayed() -> None:
        await asyncio.sleep(0.4)  # the injected delay

    ok = await run_concurrently([lambda: timed(fast) for _ in range(20)], concurrency=4)
    assert_budget("fast", ok, 300)
    slow = await run_concurrently([lambda: timed(delayed) for _ in range(20)], concurrency=4)
    with pytest.raises(AssertionError, match="not under 300"):
        assert_budget("delayed", slow, 300)


def test_p95_uses_the_nearest_rank() -> None:
    values = [float(v) for v in range(1, 101)]
    assert percentile(values, 0.95) == 95.0
    assert percentile([5.0], 0.95) == 5.0
