"""Per-user ask rate limit (NFR-6): sliding 60 s window in Redis; fails open when Redis is unavailable."""

from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

from compliance_rag.obs.metrics import RATELIMIT_BYPASS

log = structlog.get_logger(__name__)
WINDOW_S = 60.0


@dataclass(frozen=True)
class Decision:
    allowed: bool
    retry_after_s: int = 0
    bypassed: bool = False


class RateLimiter:
    """Sliding-window log per user: one sorted-set member per accepted ask, scored by time."""

    def __init__(self, redis: Redis | None, per_minute: int, prefix: str = "crag:rl:") -> None:
        self.redis, self.per_minute, self.prefix = redis, per_minute, prefix

    async def hit(self, user_sub: str, now: float | None = None) -> Decision:
        if self.redis is None:
            RATELIMIT_BYPASS.inc()
            return Decision(True, bypassed=True)
        now = time.time() if now is None else now
        key, member = f"{self.prefix}{user_sub}", uuid.uuid4().hex
        try:
            # add first, then count, in one MULTI: concurrent asks cannot both see a free slot
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.zremrangebyscore(key, 0, now - WINDOW_S)
                pipe.zadd(key, {member: now})
                pipe.zcard(key)
                pipe.zrange(key, 0, 0, withscores=True)
                pipe.expire(key, int(WINDOW_S) + 1)
                _, _, count, oldest, _ = await pipe.execute()
            if int(count) > self.per_minute:
                await self.redis.zrem(key, member)  # refused asks do not occupy a slot
                first = float(oldest[0][1]) if oldest else now
                return Decision(False, retry_after_s=max(1, math.ceil(first + WINDOW_S - now)))
        except (RedisError, OSError) as exc:
            RATELIMIT_BYPASS.inc()
            log.warning("ratelimit_bypass", error=type(exc).__name__)
            return Decision(True, bypassed=True)
        return Decision(True)
