"""``POST /v1/ask``, ``GET /v1/runs/{run_id}/events`` (SSE) and ``GET /v1/runs/{run_id}``."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Header, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from compliance_rag.api import runs
from compliance_rag.api.deps import current_principal, get_state
from compliance_rag.api.errors import not_found
from compliance_rag.api.sse import TERMINAL, format_event
from compliance_rag.api.state import AppState
from compliance_rag.obs.metrics import ASK_REQUESTS
from compliance_rag.retrieval.types import Principal

router = APIRouter(prefix="/v1", tags=["ask"])
PING_INTERVAL_S = 15.0


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=2000)
    as_of: date | None = None
    follow_up_of: str | None = None
    stream: bool = True


class AskAccepted(BaseModel):
    run_id: str
    events_url: str


class CitationOut(BaseModel):
    n: int
    chunk_id: str
    document_id: str
    version: int
    quote: str
    char_start: int
    char_end: int


class ClaimOut(BaseModel):
    index: int
    text: str
    citations: list[CitationOut]


class VersionOut(BaseModel):
    document_id: str
    version: int
    title: str
    valid_from: str | None
    valid_to: str | None
    superseded: bool


class AnswerResponse(BaseModel):
    run_id: str
    conversation_id: str
    answer: str
    claims: list[ClaimOut]
    abstained: bool
    message: str | None
    as_of: str
    versions: list[VersionOut]
    confidence: float | None
    degraded: list[str]
    cost_usd: float | None
    latency_ms: int
    label: str


class RunDetail(AnswerResponse):
    steps: list[dict[str, Any]]


@router.post("/ask", response_model=AnswerResponse | AskAccepted, responses={202: {"model": AskAccepted}})
async def ask(
    req: AskRequest,
    response: Response,
    principal: Principal = Depends(current_principal),
    state: AppState = Depends(get_state),
) -> Any:
    as_of = runs.check_as_of(principal, req.as_of)
    conversation_id = await runs.resolve_conversation(state, principal, req.follow_up_of)
    run_id = str(uuid.uuid4())
    if not req.stream:
        ASK_REQUESTS.labels(mode="sync").inc()
        return await runs.execute(
            state,
            principal,
            run_id=run_id,
            conversation_id=conversation_id,
            question=req.question,
            as_of=as_of,
            follow_up_of=req.follow_up_of,
        )
    await state.events.set_owner(run_id, principal["sub"])
    task = asyncio.create_task(
        runs.stream_run(
            state,
            principal,
            run_id=run_id,
            conversation_id=conversation_id,
            question=req.question,
            as_of=as_of,
            follow_up_of=req.follow_up_of,
        )
    )
    state.background.add(task)
    task.add_done_callback(state.background.discard)
    response.status_code = 202
    return AskAccepted(run_id=run_id, events_url=f"/v1/runs/{run_id}/events")


@router.get(
    "/runs/{run_id}/events",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def run_events(
    run_id: str,
    principal: Principal = Depends(current_principal),
    state: AppState = Depends(get_state),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    if await state.events.owner(run_id) != principal["sub"]:
        raise not_found("run")
    try:
        after = max(0, int(last_event_id or 0))
    except ValueError:
        after = 0

    async def stream() -> AsyncIterator[str]:
        cursor = after
        while True:
            events = await state.events.read(run_id, cursor, timeout_s=PING_INTERVAL_S)
            if not events:
                yield ": ping\n\n"
                continue
            for seq, event, data in events:
                cursor = seq
                yield format_event(seq, event, data)
                if event in TERMINAL:
                    return

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/runs/{run_id}", response_model=RunDetail)
async def get_run(
    run_id: str, principal: Principal = Depends(current_principal), state: AppState = Depends(get_state)
) -> Any:
    try:
        uuid.UUID(run_id)
    except ValueError as exc:
        raise not_found("run") from exc
    async with state.services.pool.connection() as conn:
        cur = await conn.execute(
            "SELECT response, steps FROM answers WHERE run_id = %s AND user_sub = %s",
            (run_id, principal["sub"]),
        )
        row = await cur.fetchone()
    if row is None:
        raise not_found("run")
    return {**row[0], "steps": row[1]}
