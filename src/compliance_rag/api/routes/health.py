"""Liveness, readiness, metrics and the caller's principal."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from compliance_rag.api.deps import current_principal, get_state
from compliance_rag.api.state import AppState
from compliance_rag.retrieval.types import Principal

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(state: AppState = Depends(get_state)) -> Response:
    checks: dict[str, str] = {}
    try:
        async with state.services.pool.connection() as conn:
            await conn.execute("SELECT 1")
        checks["postgres"] = "ok"
    except Exception:
        checks["postgres"] = "down"
    checks["opensearch"] = "ok" if await state.services.bm25.ping() else "degraded"
    try:
        checks["redis"] = "ok" if state.redis is not None and await state.redis.ping() else "degraded"
    except Exception:
        checks["redis"] = "degraded"
    ready = checks["postgres"] == "ok"
    return JSONResponse(
        {"status": "ready" if ready else "unavailable", "checks": checks}, status_code=200 if ready else 503
    )


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/v1/me")
async def me(principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    return dict(principal)
