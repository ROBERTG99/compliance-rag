"""Input limits and rate limiting (NFR-6, T-31)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from prometheus_client import REGISTRY
from redis.asyncio import Redis

from compliance_rag.api.limits import RateLimiter
from tests.fixtures_services import ApiEnv

pytestmark = pytest.mark.integration

# an unknown topic abstains before generation, so 31 asks stay fast
ASK = {"question": "What is the cafeteria menu on Fridays?", "stream": False}


@pytest.fixture
def limiter_30(api_env: ApiEnv) -> Iterator[RateLimiter]:
    state = api_env.app.state.crag
    original = state.limiter
    state.limiter = RateLimiter(state.redis, per_minute=30, prefix=f"crag:test-rl:{uuid.uuid4().hex}:")
    try:
        yield state.limiter
    finally:
        state.limiter = original


async def test_429_after_30_asks(api_env: ApiEnv, limiter_30: RateLimiter) -> None:
    async with await api_env.client("support") as support:
        statuses = [(await support.post("/v1/ask", json=ASK)).status_code for _ in range(30)]
        limited = await support.post("/v1/ask", json=ASK)
    assert statuses == [200] * 30
    assert limited.status_code == 429
    assert limited.headers["content-type"].startswith("application/problem+json")
    assert 1 <= int(limited.headers["retry-after"]) <= 60
    assert limited.json()["code"] == "rate_limited"
    # the limit is per user: another persona is unaffected
    async with await api_env.client("legal") as legal:
        assert (await legal.post("/v1/ask", json=ASK)).status_code == 200


async def test_rate_limiter_fails_open_when_redis_is_down(api_env: ApiEnv) -> None:
    state = api_env.app.state.crag
    original = state.limiter
    dead = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.2, socket_timeout=0.2)
    state.limiter = RateLimiter(dead, per_minute=1)
    before = REGISTRY.get_sample_value("crag_ratelimit_bypass_total")
    try:
        async with await api_env.client("analyst") as analyst:
            assert [(await analyst.post("/v1/ask", json=ASK)).status_code for _ in range(3)] == [200] * 3
    finally:
        state.limiter = original
        await dead.aclose()
    assert REGISTRY.get_sample_value("crag_ratelimit_bypass_total") >= before + 3


async def test_question_and_upload_limits(api_env: ApiEnv) -> None:
    async with await api_env.client("analyst") as analyst:
        long_q = await analyst.post("/v1/ask", json={"question": "x" * 2001, "stream": False})
        empty_q = await analyst.post("/v1/ask", json={"question": "   ", "stream": False})
    assert long_q.status_code == 422 and empty_q.status_code == 422
    assert long_q.headers["content-type"].startswith("application/problem+json")

    meta = {
        "document_id": "LIM-0001",
        "version": "1",
        "title": "Limits",
        "domain": "kyc",
        "owner": "Compliance",
        "valid_from": "2026-01-01",
        "acl_groups": "all",
    }
    async with await api_env.client("admin") as admin:
        big = await admin.post(
            "/v1/documents",
            data=meta,
            files={"file": ("big.pdf", b"%PDF-1.7\n" + b"0" * (20 * 1024 * 1024 + 1), "application/pdf")},
        )
        exe = await admin.post(
            "/v1/documents", data=meta, files={"file": ("x.pdf", b"MZ\x90\x00binary", "application/pdf")}
        )
    assert big.status_code == 413 and exe.status_code == 415
    for resp in (big, exe):
        assert resp.headers["content-type"].startswith("application/problem+json")


async def test_queue_is_recreated_after_redis_comes_back(api_env: ApiEnv) -> None:
    state = api_env.app.state.crag
    original = state.arq
    state.arq = None  # as if Redis was down when the API started
    try:
        assert await state.queue() is not None  # created lazily on the next upload
    finally:
        if state.arq is not original and state.arq is not None:
            await state.arq.aclose()
        state.arq = original
