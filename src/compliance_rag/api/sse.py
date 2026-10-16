"""Run event store and SSE framing (BUILD.md §4.5).

Events go to the Redis Stream ``crag:run:{run_id}`` with explicit ids ``0-<seq>`` (TTL 300 s) so a
client can resume with ``Last-Event-ID``. When Redis is unavailable the store falls back to process
memory: streaming still works, cross-process resume does not.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from typing import Any

from redis.asyncio import Redis

Event = tuple[int, str, dict[str, Any]]
TERMINAL = {"final", "error"}


def format_event(seq: int, event: str, data: dict[str, Any]) -> str:
    return f"id: {seq}\nevent: {event}\ndata: {json.dumps(data, separators=(',', ':'), default=str)}\n\n"


class MemoryEvents:
    def __init__(self) -> None:
        self.events: dict[str, list[Event]] = defaultdict(list)
        self.owners: dict[str, str] = {}
        self.cond = asyncio.Condition()

    async def set_owner(self, run_id: str, sub: str) -> None:
        self.owners[run_id] = sub

    async def owner(self, run_id: str) -> str | None:
        return self.owners.get(run_id)

    async def append(self, run_id: str, event: str, data: dict[str, Any]) -> int:
        async with self.cond:
            seq = len(self.events[run_id]) + 1
            self.events[run_id].append((seq, event, data))
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
    """Redis Streams with an in-memory fallback."""

    def __init__(self, redis: Redis | None, ttl_s: int = 300) -> None:
        self.redis = redis
        self.ttl_s = ttl_s
        self.memory = MemoryEvents()
        self._memory_runs: set[str] = set()

    @staticmethod
    def _key(run_id: str) -> str:
        return f"crag:run:{run_id}"

    def _use_memory(self, run_id: str) -> bool:
        return self.redis is None or run_id in self._memory_runs

    async def set_owner(self, run_id: str, sub: str) -> None:
        await self.memory.set_owner(run_id, sub)
        if self.redis is None:
            self._memory_runs.add(run_id)
            return
        try:
            await self.redis.set(f"{self._key(run_id)}:owner", sub, ex=self.ttl_s)
        except Exception:
            self._memory_runs.add(run_id)

    async def owner(self, run_id: str) -> str | None:
        if not self._use_memory(run_id):
            try:
                value = await self.redis.get(f"{self._key(run_id)}:owner")  # type: ignore[union-attr]
                if value is not None:
                    return value.decode() if isinstance(value, bytes) else str(value)
            except Exception:  # Redis unavailable: fall back to the in-process copy
                self._memory_runs.add(run_id)
        return await self.memory.owner(run_id)

    async def append(self, run_id: str, event: str, data: dict[str, Any]) -> int:
        if not self._use_memory(run_id):
            try:
                key = self._key(run_id)
                assert self.redis is not None
                seq = int(await self.redis.incr(f"{key}:seq"))
                await self.redis.xadd(
                    key, {"event": event, "data": json.dumps(data, default=str)}, id=f"0-{seq}"
                )
                if seq == 1:
                    for k in (key, f"{key}:seq", f"{key}:owner"):
                        await self.redis.expire(k, self.ttl_s)
                return seq
            except Exception:
                self._memory_runs.add(run_id)
        return await self.memory.append(run_id, event, data)

    async def read(self, run_id: str, after: int, timeout_s: float = 15.0) -> list[Event]:
        if self._use_memory(run_id):
            return await self.memory.read(run_id, after, timeout_s)
        assert self.redis is not None
        key = self._key(run_id)
        rows = await self.redis.xrange(key, min=f"0-{after + 1}", max="+")
        if not rows:
            resp = await self.redis.xread({key: f"0-{after}"}, block=int(timeout_s * 1000), count=500)
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
