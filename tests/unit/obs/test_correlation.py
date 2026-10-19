"""Every response carries a correlation id that is also on every log line of the request (T-43)."""

from __future__ import annotations

import json

import httpx
import pytest
import structlog
from fastapi import FastAPI

from compliance_rag.api.correlation import CorrelationId
from compliance_rag.obs.logging import configure_logging


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/ping")
    async def ping() -> dict[str, bool]:
        structlog.get_logger("t").info("handled")
        return {"ok": True}

    app.add_middleware(CorrelationId)
    return app


async def test_given_id_is_echoed_and_logged(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", service="api")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app()), base_url="http://api") as c:
        r = await c.get("/ping", headers={"X-Request-ID": "trace-abc-123"})
    assert r.headers["x-request-id"] == "trace-abc-123"
    lines = [json.loads(raw) for raw in capsys.readouterr().out.strip().splitlines()]
    handled = next(line for line in lines if line["event"] == "handled")
    access = next(line for line in lines if line["event"] == "request")
    assert handled["correlation_id"] == access["correlation_id"] == "trace-abc-123"


async def test_missing_or_malformed_id_is_replaced() -> None:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app()), base_url="http://api") as c:
        minted = (await c.get("/ping")).headers["x-request-id"]
        forged = (await c.get("/ping", headers={"X-Request-ID": "bad id\\n{json}"})).headers["x-request-id"]
    assert len(minted) == 32 and minted != forged and len(forged) == 32
