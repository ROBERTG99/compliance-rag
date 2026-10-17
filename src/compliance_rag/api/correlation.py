"""Correlation ids: accept a well-formed ``X-Request-ID`` or mint one, bind it to every log line, echo it.
Also the JSON access log (method, path, status, duration; never the query string or bodies)."""

from __future__ import annotations

import re
import time
import uuid
from typing import Any

import structlog

from compliance_rag.obs.logging import bind_correlation, clear_context

log = structlog.get_logger("compliance_rag.access")
QUIET = {"/healthz", "/readyz", "/metrics"}

HEADER = b"x-request-id"
VALID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


class CorrelationId:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        given = dict(scope.get("headers") or []).get(HEADER, b"").decode("latin-1")
        correlation_id = given if VALID.fullmatch(given) else uuid.uuid4().hex
        clear_context()
        bind_correlation(correlation_id)

        started = time.perf_counter()
        status = {"code": 500}

        async def send_with_id(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                status["code"] = int(message["status"])
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != HEADER]
                message = {**message, "headers": [*headers, (HEADER, correlation_id.encode())]}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            if scope["path"] not in QUIET:
                log.info(
                    "request",
                    method=scope["method"],
                    path=scope["path"],
                    status=status["code"],
                    duration_ms=round((time.perf_counter() - started) * 1000, 1),
                )
            clear_context()
