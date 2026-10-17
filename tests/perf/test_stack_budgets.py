"""NFR-1, NFR-2, NFR-8 against the running stack (`make bench` starts it): 4 concurrent clients over HTTP.

* NFR-1 retrieval (legs + fusion + rerank) p95 < 300 ms — from each run's step records (`GET /v1/runs/{id}`).
* NFR-2 time to first verified claim p95 < 300 ms offline — client side, from `POST /v1/ask` to the first
  `claim` event on the run's SSE stream.
* NFR-8 `GET /v1/documents` p95 < 200 ms — library pages with and without filters, four personas.

The asks are measured at steady state: one unmeasured pass of the same workload first.

Numbers are written to `evals/reports/bench.json`.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.perf.budget import assert_budget, record, run_concurrently, timed

pytestmark = [pytest.mark.perf, pytest.mark.stack]
ROOT = Path(__file__).resolve().parents[2]
API = os.environ.get("API_URL", "http://localhost:8610")
OIDC = os.environ.get("OIDC_URL", "http://localhost:8612")
PERSONAS = ("analyst", "legal", "support", "admin")
CONCURRENCY = 4
PER_PERSONA = 14  # warm-up pass + measured pass stay under the 30 asks/min limit per user
RETRIEVAL_NODES = {"retrieve", "fuse", "rerank"}


async def _tokens() -> dict[str, str]:
    async with httpx.AsyncClient(base_url=OIDC, timeout=10) as idp:
        return {
            p: (await idp.post("/dev/token", json={"persona": p})).json()["access_token"] for p in PERSONAS
        }


def _questions() -> list[dict[str, Any]]:
    rows = [
        json.loads(line) for line in (ROOT / "evals/datasets/questions.v1.jsonl").read_text().splitlines()
    ]
    picked: list[dict[str, Any]] = []
    per: Counter[str] = Counter()
    for row in rows:
        persona = row["input"]["persona"]
        if row["split"] == "dev" and not row["expected"]["abstain"] and per[persona] < PER_PERSONA:
            per[persona] += 1
            picked.append(row)
    return picked


async def _ask(client: httpx.AsyncClient, token: str, row: dict[str, Any]) -> tuple[float | None, float]:
    """(ms to the first verified claim or None, retrieval ms from the run's steps)."""
    headers = {"Authorization": f"Bearer {token}"}
    body = {"question": row["input"]["question"], "as_of": row["input"]["as_of"], "stream": True}
    while True:
        started = time.perf_counter()
        accepted = await client.post("/v1/ask", json=body, headers=headers)
        if accepted.status_code != 429:
            break
        await asyncio.sleep(float(accepted.headers.get("Retry-After", "5")))  # not part of any timing
    assert accepted.status_code == 202, accepted.text
    run = accepted.json()
    first_claim: float | None = None
    async with client.stream("GET", run["events_url"], headers=headers) as events:
        async for line in events.aiter_lines():
            if line == "event: claim" and first_claim is None:
                first_claim = (time.perf_counter() - started) * 1000
            if line in ("event: final", "event: error"):
                break
    detail = (await client.get(f"/v1/runs/{run['run_id']}", headers=headers)).json()
    retrieval = sum(s["latency_ms"] for s in detail["steps"] if s["node"] in RETRIEVAL_NODES)
    return first_claim, retrieval


async def test_retrieval_and_time_to_first_claim_under_load() -> None:
    tokens = await _tokens()
    rows = _questions()
    calls = [lambda r=r: _ask(client, tokens[r["input"]["persona"]], r) for r in rows]
    async with httpx.AsyncClient(base_url=API, timeout=60) as client:
        # steady state: one unmeasured pass of the same workload fills connection pools and caches
        await run_concurrently(calls, CONCURRENCY)
        results = await run_concurrently(calls, CONCURRENCY)
    retrieval = [r for _, r in results]
    ttft = [t for t, _ in results if t is not None]
    context = {
        "concurrency": CONCURRENCY,
        "llm": "FakeLLM (offline)",
        "split": "dev",
        "method": "one unmeasured warm-up pass, then the measured pass over the same questions",
    }
    record("nfr1_retrieval", assert_budget("NFR-1 retrieval", retrieval, 300), **context)
    assert len(ttft) >= 0.8 * len(results), f"only {len(ttft)} of {len(results)} runs streamed a claim"
    record("nfr2_ttft", assert_budget("NFR-2 time to first claim", ttft, 300), **context)


async def test_document_library_latency() -> None:
    tokens = await _tokens()
    variants: list[dict[str, Any]] = [
        {},
        {"domain": "kyc"},
        {"q": "limit"},
        {"limit": 50},
        {"domain": "aml", "q": "review"},
    ]
    async with httpx.AsyncClient(base_url=API, timeout=30) as client:
        first = await client.get("/v1/documents", headers={"Authorization": f"Bearer {tokens['admin']}"})
        cursor = first.json()["next_cursor"]
        variants.append({"cursor": cursor})

        def call(i: int) -> Any:
            persona = PERSONAS[i % len(PERSONAS)]
            params = variants[i % len(variants)]

            async def get() -> None:
                resp = await client.get(
                    "/v1/documents", params=params, headers={"Authorization": f"Bearer {tokens[persona]}"}
                )
                assert resp.status_code == 200, resp.text

            return lambda: timed(get)

        samples = await run_concurrently([call(i) for i in range(120)], CONCURRENCY)
    record("nfr8_documents", assert_budget("NFR-8 GET /v1/documents", samples, 200), concurrency=CONCURRENCY)
