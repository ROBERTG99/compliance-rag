"""Run event store against real Redis: slow runs, Redis failing mid-run, expiry (BUILD.md §4.5, §4.7)."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from redis.asyncio import Redis

from compliance_rag.api.sse import RunEvents

pytestmark = pytest.mark.integration


def _client(url: str) -> Redis:
    # the same timeouts the API uses (state.build_state)
    return Redis.from_url(url, socket_connect_timeout=1, socket_timeout=2)


async def test_read_waits_past_the_socket_timeout(redis_url: str) -> None:
    redis = _client(redis_url)
    events, run = RunEvents(redis), uuid.uuid4().hex
    await events.set_owner(run, "u")
    await events.append(run, "run_started", {})

    async def late() -> None:
        await asyncio.sleep(3.0)  # longer than socket_timeout=2, e.g. a slow first claim
        await events.append(run, "final", {"ok": True})

    task = asyncio.create_task(late())
    try:
        assert await events.read(run, 1, timeout_s=1.0) == []  # quiet period → caller sends a ping
        got = await events.read(run, 1, timeout_s=5.0)
        assert [(seq, name) for seq, name, _ in got] == [(2, "final")]
    finally:
        await task
        await redis.aclose()


async def test_redis_failure_mid_run_continues_numbering_in_memory(redis_url: str) -> None:
    redis = _client(redis_url)
    events, run = RunEvents(redis), uuid.uuid4().hex
    await events.set_owner(run, "u")
    for name in ("run_started", "node"):
        await events.append(run, name, {})
    dead = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.2, socket_timeout=0.2)
    events.redis = dead  # Redis goes away mid-run
    try:
        assert await events.append(run, "final", {}) == 3
        got = await events.read(run, 2, timeout_s=0.5)  # client cursor at 2 still sees the final event
        assert [(seq, name) for seq, name, _ in got] == [(3, "final")]
        assert await events.owner(run) == "u"
    finally:
        await dead.aclose()
        await redis.aclose()


async def test_expired_run_is_unknown_and_memory_is_not_kept_for_healthy_runs(redis_url: str) -> None:
    redis = _client(redis_url)
    events, run = RunEvents(redis, ttl_s=1), uuid.uuid4().hex
    try:
        await events.set_owner(run, "u")
        await events.append(run, "final", {})
        assert events.memory.owners == {} and not events.memory.events
        await asyncio.sleep(2.2)
        assert await events.owner(run) is None  # → 404, not pings forever
    finally:
        await redis.aclose()


async def test_memory_runs_are_evicted_after_ttl() -> None:
    events = RunEvents(None, ttl_s=1)
    await events.set_owner("old", "u")
    await events.append("old", "final", {})
    await asyncio.sleep(1.2)
    await events.set_owner("new", "u")
    assert "old" not in events.memory.owners and "old" not in events.memory.events


async def test_each_event_is_one_redis_round_trip_with_ordered_ids(redis_url: str) -> None:
    # events are written by the run's own task only, so their numbers need no shared counter: the graph waits on
    # one XADD per event (about 20 events precede the first claim), and the stream still expires
    redis = _client(redis_url)
    events, run = RunEvents(redis), uuid.uuid4().hex
    await events.set_owner(run, "u")
    calls: list[str] = []
    original = redis.execute_command

    async def counting(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(str(args[0]).upper())
        return await original(*args, **kwargs)

    redis.execute_command = counting  # type: ignore[method-assign]
    for i in range(5):
        assert await events.append(run, "node", {"i": i}) == i + 1
    redis.execute_command = original  # type: ignore[method-assign]
    assert calls == ["XADD"] * 4  # no counter; the first event shares one pipeline with its TTLs
    assert [seq for seq, _, _ in await events.read(run, 0)] == [1, 2, 3, 4, 5]
    assert 0 < await redis.ttl(f"crag:run:{run}") <= events.ttl_s
    await redis.aclose()
