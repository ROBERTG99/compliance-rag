"""Run event store and SSE framing (BUILD.md §4.5).

Events go to the Redis Stream ``crag:run:{run_id}`` with explicit ids ``0-<seq>`` (TTL 300 s) so a
client can resume with ``Last-Event-ID``. When Redis is unavailable the store falls back to process
memory: streaming still works, cross-process resume does not.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict
from typing import Any

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

Event = tuple[int, str, dict[str, Any]]
TERMINAL = {"final", "error"}
log = structlog.get_logger(__name__)


def format_event(seq: int, event: str, data: dict[str, Any]) -> str:
    return f"id: {seq}\nevent: {event}\ndata: {json.dumps(data, separators=(',', ':'), default=str)}\n\n"


class MemoryEvents:
    """Process-local fallback; entries are evicted ``ttl_s`` after the run was registered."""

    def __init__(self, ttl_s: int = 300) -> None:
        self.ttl_s = ttl_s
        self.events: dict[str, list[Event]] = defaultdict(list)
        self.owners: dict[str, str] = {}
        self.created: dict[str, float] = {}
        self.cond = asyncio.Condition()

    def _sweep(self) -> None:
        cutoff = time.monotonic() - self.ttl_s
        for run_id in [r for r, at in self.created.items() if at < cutoff]:
            self.created.pop(run_id, None)
            self.owners.pop(run_id, None)
            self.events.pop(run_id, None)

    async def set_owner(self, run_id: str, sub: str) -> None:
        self._sweep()
        self.owners[run_id] = sub
        self.created.setdefault(run_id, time.monotonic())

    async def owner(self, run_id: str) -> str | None:
        self._sweep()
        return self.owners.get(run_id)

    async def append(self, run_id: str, event: str, data: dict[str, Any], after_seq: int = 0) -> int:
        async with self.cond:
            self.created.setdefault(run_id, time.monotonic())
            log = self.events[run_id]
            # continue the numbering of a run that started in Redis, so client cursors stay valid
            seq = max(after_seq, log[-1][0] if log else 0) + 1
            log.append((seq, event, data))
            self.cond.notify_all()
        return seq

    async def read(self, run_id: str, after: int, timeout_s: float) -> list[Event]:
        async with self.cond:
            pending = [e for e in self.events.get(run_id, []) if e[0] > after]
            if pending:
                return pending
            try:
                await asyncio.wait_for(self.cond.wait(), timeout=timeout_s)
            except TimeoutError:
                return []
            return [e for e in self.events.get(run_id, []) if e[0] > after]


class RunEvents:
    """Redis Streams with an in-memory fallback.

    Healthy runs live only in Redis (owner and events expire after ``ttl_s``). A run moves to memory
    when Redis fails; its numbering continues from the last Redis sequence so a client's
    ``Last-Event-ID`` still points at the right place.
    """

    # XREAD blocks in slices shorter than the client's 2 s socket timeout
    BLOCK_SLICE_S = 1.5

    def __init__(self, redis: Redis | None, ttl_s: int = 300) -> None:
        self.redis = redis
        self.ttl_s = ttl_s
        self.memory = MemoryEvents(ttl_s)
        self._memory_runs: set[str] = set()
        # per-run bookkeeping until the run ends or moves to memory; swept after ttl_s for runs that never end
        self._owners: dict[str, str] = {}
        self._last_seq: dict[str, int] = {}
        self._started: dict[str, float] = {}

    @staticmethod
    def _key(run_id: str) -> str:
        return f"crag:run:{run_id}"

    def _use_memory(self, run_id: str) -> bool:
        return self.redis is None or run_id in self._memory_runs

    async def _to_memory(self, run_id: str, exc: BaseException) -> None:
        if run_id not in self._memory_runs:
            log.warning("run_events_memory_fallback", error=type(exc).__name__)
            self._memory_runs.add(run_id)
            owner = self._owners.pop(run_id, None)
            if owner is not None:
                await self.memory.set_owner(run_id, owner)

    async def set_owner(self, run_id: str, sub: str) -> None:
        if self.redis is None:
            self._memory_runs.add(run_id)
            await self.memory.set_owner(run_id, sub)
            return
        self._sweep()
        self._owners[run_id] = sub
        self._started[run_id] = time.monotonic()
        try:
            await self.redis.set(f"{self._key(run_id)}:owner", sub, ex=self.ttl_s)
        except (RedisError, OSError) as exc:
            await self._to_memory(run_id, exc)

    def _sweep(self) -> None:
        cutoff = time.monotonic() - self.ttl_s
        for run_id in [r for r, at in self._started.items() if at < cutoff]:
            self._started.pop(run_id, None)
            self._owners.pop(run_id, None)
            self._last_seq.pop(run_id, None)

    async def owner(self, run_id: str) -> str | None:
        if not self._use_memory(run_id):
            try:
                value = await self.redis.get(f"{self._key(run_id)}:owner")  # type: ignore[union-attr]
                return None if value is None else value.decode() if isinstance(value, bytes) else str(value)
            except (RedisError, OSError) as exc:
                await self._to_memory(run_id, exc)
        return await self.memory.owner(run_id)

    async def append(self, run_id: str, event: str, data: dict[str, Any]) -> int:
        if not self._use_memory(run_id):
            try:
                key = self._key(run_id)
                assert self.redis is not None
                # a run's events are written by its own task only, so the sequence is local: one round trip per
                # event on the graph's critical path (the first one also sets the TTLs, in the same pipeline)
                seq = self._last_seq.get(run_id, 0) + 1
                fields: dict[Any, Any] = {"event": event, "data": json.dumps(data, default=str)}
                if seq == 1:
                    pipe = self.redis.pipeline(transaction=False)
                    pipe.xadd(key, fields, id=f"0-{seq}")
                    pipe.expire(key, self.ttl_s)
                    pipe.expire(f"{key}:owner", self.ttl_s)
                    await pipe.execute()
                else:
                    await self.redis.xadd(key, fields, id=f"0-{seq}")
                self._last_seq[run_id] = seq
                if event in TERMINAL:
                    self._owners.pop(run_id, None)
                    self._last_seq.pop(run_id, None)
                    self._started.pop(run_id, None)
                return seq
            except (RedisError, OSError) as exc:
                await self._to_memory(run_id, exc)
        return await self.memory.append(run_id, event, data, after_seq=self._last_seq.pop(run_id, 0))

    async def read(self, run_id: str, after: int, timeout_s: float = 15.0) -> list[Event]:
        if not self._use_memory(run_id):
            try:
                return await self._read_redis(run_id, after, timeout_s)
            except (RedisError, OSError) as exc:
                await self._to_memory(run_id, exc)
        return await self.memory.read(run_id, after, timeout_s)

    async def _read_redis(self, run_id: str, after: int, timeout_s: float) -> list[Event]:
        assert self.redis is not None
        key = self._key(run_id)
        rows = await self.redis.xrange(key, min=f"0-{after + 1}", max="+")
        deadline = time.monotonic() + timeout_s
        while not rows:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return []
            block_ms = max(1, int(min(remaining, self.BLOCK_SLICE_S) * 1000))
            resp = await self.redis.xread({key: f"0-{after}"}, block=block_ms, count=500)
            rows = [r for _, entries in resp for r in entries] if resp else []
        out: list[Event] = []
        for entry_id, fields in rows:
            eid = entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)
            f = {
                (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
                for k, v in fields.items()
            }
            out.append((int(eid.split("-")[1]), f["event"], json.loads(f["data"])))
        return out
