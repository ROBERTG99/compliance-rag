"""Liveness, readiness, metrics and the caller's principal."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, generate_latest, multiprocess

from compliance_rag.api.deps import current_principal, get_state
from compliance_rag.api.schemas import Health, Me, Ready
from compliance_rag.api.state import AppState
from compliance_rag.retrieval.types import Principal
from compliance_rag.settings import get_settings

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=Health)
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get(
    "/readyz", response_model=Ready, responses={503: {"model": Ready, "description": "Postgres unavailable"}}
)
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
def metrics() -> Response:
    # several uvicorn workers: each scrape must sum every process, not report the one that answered; reading
    # every per-process file is blocking I/O, so this is a sync route (FastAPI runs it in the threadpool)
    if get_settings().prometheus_multiproc_dir:
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)  # type: ignore[no-untyped-call]
        return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/v1/me", response_model=Me)
async def me(principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    return dict(principal)
