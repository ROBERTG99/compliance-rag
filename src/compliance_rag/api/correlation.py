"""Correlation ids: accept a well-formed ``X-Request-ID`` or mint one, bind it to every log line, echo it."""

from __future__ import annotations

import re
import uuid
from typing import Any

from compliance_rag.obs.logging import bind_correlation, clear_context

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

        async def send_with_id(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != HEADER]
                message = {**message, "headers": [*headers, (HEADER, correlation_id.encode())]}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            clear_context()
