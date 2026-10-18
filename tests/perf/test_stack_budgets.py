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

from tests.perf.budget import assert_budget, record, run_concurrently, summary, timed

pytestmark = [pytest.mark.perf, pytest.mark.stack]
ROOT = Path(__file__).resolve().parents[2]
API = os.environ.get("API_URL", "http://localhost:8610")
OIDC = os.environ.get("OIDC_URL", "http://localhost:8612")
PERSONAS = ("analyst", "legal", "support", "admin")
CONCURRENCY = 4
WARMUP_PER_PERSONA = 5  # warm-up questions are disjoint from the measured ones
PER_PERSONA = 20  # measured questions per persona; 429s (30 asks/min/user) are waited out, never timed
RETRIEVAL_NODES = {"retrieve", "fuse", "rerank"}


async def _tokens() -> dict[str, str]:
    async with httpx.AsyncClient(base_url=OIDC, timeout=10) as idp:
        return {
            p: (await idp.post("/dev/token", json={"persona": p})).json()["access_token"] for p in PERSONAS
        }


def _questions() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(warm-up rows, measured rows): answerable dev questions, the two sets disjoint."""
    rows = [
        json.loads(line) for line in (ROOT / "evals/datasets/questions.v1.jsonl").read_text().splitlines()
    ]
    warmup: list[dict[str, Any]] = []
    measured: list[dict[str, Any]] = []
    per: Counter[str] = Counter()
    for row in rows:
        persona = row["input"]["persona"]
        if row["split"] != "dev" or row["expected"]["abstain"]:
            continue
        per[persona] += 1
        if per[persona] <= WARMUP_PER_PERSONA:
            warmup.append(row)
        elif per[persona] <= WARMUP_PER_PERSONA + PER_PERSONA:
            measured.append(row)
    return warmup, measured


async def ask_once(
    client: httpx.AsyncClient, token: str, row: dict[str, Any], *, strict: bool = True
) -> tuple[float | None, float]:
    """(ms to the first verified claim or None, retrieval ms from the run's steps). With ``strict`` a run
    that ends in an `error` event fails the measurement; the warm-up pass is not strict."""
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
    ended: str | None = None
    async with client.stream("GET", run["events_url"], headers=headers) as events:
        async for line in events.aiter_lines():
            if line == "event: claim" and first_claim is None:
                first_claim = (time.perf_counter() - started) * 1000
            if ended == "event: error" and line.startswith("data: "):  # the error's code and retryability
                assert not strict, f"run {run['run_id']} ended with an error: {line[6:]}"
                return None, float("nan")
            if line in ("event: final", "event: error"):
                ended = line
                if line == "event: final":
                    break
    detail = (await client.get(f"/v1/runs/{run['run_id']}", headers=headers)).json()
    retrieval = sum(s["latency_ms"] for s in detail["steps"] if s["node"] in RETRIEVAL_NODES)
    return first_claim, retrieval


async def test_retrieval_and_time_to_first_claim_under_load() -> None:
    tokens = await _tokens()
    warmup, rows = _questions()
    async with httpx.AsyncClient(base_url=API, timeout=60) as client:
        # an unmeasured pass over *other* questions fills connection pools and process caches; the measured
        # questions' own chunks are not pre-cached
        await run_concurrently(
            [lambda r=r: ask_once(client, tokens[r["input"]["persona"]], r, strict=False) for r in warmup],
            CONCURRENCY,
        )
        results = await run_concurrently(
            [lambda r=r: ask_once(client, tokens[r["input"]["persona"]], r) for r in rows], CONCURRENCY
        )
    retrieval = [r for _, r in results]
    ttft = [t for t, _ in results if t is not None]
    context = {
        "concurrency": CONCURRENCY,
        "llm": "FakeLLM (offline)",
        "split": "dev",
        "method": "unmeasured warm-up pass over other dev questions, then the measured pass",
    }
    assert len(ttft) >= 0.8 * len(results), f"only {len(ttft)} of {len(results)} runs streamed a claim"
    nfr1 = summary(retrieval, 300)
    record("nfr1_retrieval", nfr1, **context)  # both are recorded before either is asserted
    assert_budget("NFR-2 time to first claim", ttft, 300, key="nfr2_ttft", **context)
    assert_budget("NFR-1 retrieval", retrieval, 300)


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
    assert_budget("NFR-8 GET /v1/documents", samples, 200, key="nfr8_documents", concurrency=CONCURRENCY)
