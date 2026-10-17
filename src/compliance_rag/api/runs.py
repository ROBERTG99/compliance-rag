"""Running an ask: graph execution, event publishing, persistence and audit."""

from __future__ import annotations

import hashlib
import uuid
from datetime import date
from typing import Any

import structlog
from psycopg.types.json import Jsonb

from compliance_rag.api.errors import Problem, not_found
from compliance_rag.api.state import AppState
from compliance_rag.db.audit import append_audit
from compliance_rag.graph.build import run_graph
from compliance_rag.graph.respond import build_response
from compliance_rag.llm.gateway import GenerationUnavailable
from compliance_rag.obs.metrics import ASK_REQUESTS
from compliance_rag.retrieval.hybrid import RetrievalUnavailable
from compliance_rag.retrieval.types import Principal

log = structlog.get_logger(__name__)


async def resolve_conversation(state: AppState, principal: Principal, follow_up_of: str | None) -> str:
    """A follow-up continues the caller's own conversation only; anything else is 404."""
    if not follow_up_of:
        return str(uuid.uuid4())
    try:
        uuid.UUID(follow_up_of)
    except ValueError as exc:
        raise not_found("run") from exc
    async with state.services.pool.connection() as conn:
        cur = await conn.execute(
            "SELECT conversation_id, user_sub FROM answers WHERE run_id = %s", (follow_up_of,)
        )
        row = await cur.fetchone()
    if row is None or row[1] != principal["sub"]:
        raise not_found("run")
    return str(row[0])


def check_as_of(principal: Principal, as_of: date | None) -> date:
    today = date.today()
    as_of = as_of or today
    if as_of > today and principal["role"] != "content_admin":
        raise Problem(422, "Unprocessable Content", "as_of cannot be in the future", "as_of_in_future")
    return as_of


async def persist(
    state: AppState,
    principal: Principal,
    question: str,
    follow_up_of: str | None,
    final: dict[str, Any],
    graph_state: dict[str, Any],
) -> None:
    steps = graph_state.get("steps", [])
    async with state.services.pool.connection() as conn, conn.transaction():
        await conn.execute(
            """INSERT INTO answers (run_id, conversation_id, follow_up_of, user_sub, groups, question, as_of, response,
                   abstained, abstain_reason, steps, cost_usd, latency_ms)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                final["run_id"],
                final["conversation_id"],
                follow_up_of,
                principal["sub"],
                principal["groups"],
                question,
                final["as_of"],
                Jsonb(final),
                final["abstained"],
                graph_state.get("abstain_reason"),
                Jsonb(steps),
                round(float(graph_state.get("cost_usd") or 0.0), 6),
                int(final["latency_ms"]),
            ),
        )
        await append_audit(
            conn,
            actor_sub=principal["sub"],
            actor_role=principal["role"],
            action="ask",
            target=final["run_id"],
            details={
                "conversation_id": final["conversation_id"],
                "abstained": final["abstained"],
                "n_claims": len(final["claims"]),
                "as_of": final["as_of"],
                "question_sha256": hashlib.sha256(question.encode()).hexdigest(),
            },
        )


async def execute(
    state: AppState,
    principal: Principal,
    *,
    run_id: str,
    conversation_id: str,
    question: str,
    as_of: date,
    follow_up_of: str | None,
    emit: Any = None,
) -> dict[str, Any]:
    graph_state = await run_graph(
        state.graph,
        question=question,
        principal=principal,
        as_of=as_of.isoformat(),
        conversation_id=conversation_id,
        follow_up_of=follow_up_of,
        run_id=run_id,
        emit=emit,
    )
    final = build_response(graph_state)
    await persist(state, principal, question, follow_up_of, final, graph_state)
    return final


async def stream_run(
    state: AppState,
    principal: Principal,
    *,
    run_id: str,
    conversation_id: str,
    question: str,
    as_of: date,
    follow_up_of: str | None,
) -> None:
    """Background task for ``stream: true``: every event goes to the run's event stream."""

    async def emit(event: str, data: dict[str, Any]) -> None:
        await state.events.append(run_id, event, data)

    ASK_REQUESTS.labels(mode="stream").inc()
    await emit(
        "run_started",
        {
            "run_id": run_id,
            "conversation_id": conversation_id,
            "as_of": as_of.isoformat(),
            "role": principal["role"],
        },
    )
    try:
        final = await execute(
            state,
            principal,
            run_id=run_id,
            conversation_id=conversation_id,
            question=question,
            as_of=as_of,
            follow_up_of=follow_up_of,
            emit=emit,
        )
        await emit("final", final)
    except RetrievalUnavailable:
        await emit(
            "error",
            {"code": "retrieval_unavailable", "message": "retrieval is unavailable", "retryable": True},
        )
    except GenerationUnavailable:
        await emit(
            "error",
            {"code": "generation_unavailable", "message": "generation is unavailable", "retryable": True},
        )
    except Exception as exc:
        # type and run only: messages can echo question or document text
        log.error("stream_run_failed", run_id=run_id, error_type=type(exc).__name__)
        await emit("error", {"code": "internal", "message": "internal error", "retryable": False})
