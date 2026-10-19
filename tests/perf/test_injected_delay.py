"""T-46: the stack measurement itself fails when 400 ms are injected into the rerank node (in-process app)."""

from __future__ import annotations

import time
from typing import Any

import pytest

from compliance_rag.rerank.feature import FeatureReranker
from tests.fixtures_services import ApiEnv
from tests.perf.budget import assert_budget
from tests.perf.test_stack_budgets import RETRIEVAL_NODES, ask_once

pytestmark = [pytest.mark.perf, pytest.mark.integration]
ROW = {
    "input": {"question": "What is the maximum age of a proof-of-address document?", "as_of": "2026-10-16"}
}


async def _measure(api_env: ApiEnv) -> tuple[list[float], list[float]]:
    token = await api_env.token("analyst")
    async with await api_env.client() as client:
        # unmeasured first ask, as in the stack bench: with six samples p95 is the maximum, so one cold request
        # (connection pools, first query shapes) would decide the baseline
        await ask_once(client, token, ROW, strict=False)
        results = [await ask_once(client, token, ROW) for _ in range(6)]
    return [r for _, r in results], [t for t, _ in results if t is not None]


async def test_budgets_fail_when_the_rerank_node_is_400_ms_slower(
    api_env: ApiEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert "rerank" in RETRIEVAL_NODES
    retrieval, ttft = await _measure(api_env)
    assert_budget("retrieval", retrieval, 300)
    assert_budget("ttft", ttft, 300)

    original = FeatureReranker.rerank

    def slow(self: FeatureReranker, *args: Any) -> Any:
        time.sleep(0.4)  # runs in the node's worker thread, like real rerank work
        return original(self, *args)

    monkeypatch.setattr(FeatureReranker, "rerank", slow)
    retrieval, ttft = await _measure(api_env)
    with pytest.raises(AssertionError, match="not under 300"):
        assert_budget("retrieval", retrieval, 300)
    with pytest.raises(AssertionError, match="not under 300"):
        assert_budget("ttft", ttft, 300)
