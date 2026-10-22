"""Per-user ask rate limit: sliding 60 s window in Redis; fails open when Redis is unavailable."""

from __future__ import annotations

import json
import math
import time
import uuid
from dataclasses import dataclass

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

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


class BodyLimit:
    """ASGI guard: refuse request bodies over the limit before they are buffered or spooled.

    ``Content-Length`` is checked up front; chunked bodies are counted while they stream in and abort with
    413 as soon as they pass the limit (raised as an HTTPException, which FastAPI's body parsing re-raises).
    """

    def __init__(self, app: ASGIApp, default_limit: int, limits: dict[str, int]) -> None:
        self.app, self.default_limit, self.limits = app, default_limit, limits

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            await self.app(scope, receive, send)
            return
        limit = self.limits.get(scope["path"], self.default_limit)
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            await _too_large(scope, send, limit)
            return
        seen = 0

        async def counted() -> Message:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    raise HTTPException(413, "Content Too Large")
            return message

        await self.app(scope, counted, send)


async def _too_large(scope: Scope, send: Send, limit: int) -> None:
    body = json.dumps(
        {
            "type": "https://compliance-rag.example/problems/upload_too_large",
            "title": "Content Too Large",
            "status": 413,
            "instance": scope["path"],
            "detail": f"request bodies are limited to {limit} bytes here",
            "code": "upload_too_large",
        }
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/problem+json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
