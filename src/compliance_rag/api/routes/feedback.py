"""Feedback (one per user per run) and admin triage into the dev split only."""

from __future__ import annotations

import base64
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from compliance_rag.api.deps import current_principal, get_state, require_role
from compliance_rag.api.errors import Problem, not_found
from compliance_rag.api.state import AppState
from compliance_rag.db.audit import append_audit
from compliance_rag.evals.splits import SplitRegistryUnavailable, in_test_split
from compliance_rag.retrieval.types import Principal
from compliance_rag.validation import SafeText

router = APIRouter(prefix="/v1", tags=["feedback"])

Rating = Literal["up", "down"]
Reason = Literal[
    "correct", "wrong_fact", "wrong_citation", "outdated", "missing_info", "should_abstain", "other"
]
Status = Literal["new", "triaged", "added_to_dev_set"]

_COLUMNS = "f.id, f.run_id, f.rating, f.reason, f.comment, f.status, f.created_at"


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: uuid.UUID
    rating: Rating
    reason: Reason
    comment: SafeText | None = Field(default=None, max_length=1000)


class FeedbackItem(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    rating: Rating
    reason: Reason
    comment: str | None
    status: Status
    created_at: datetime


class TriageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["triaged", "added_to_dev_set"]
    # triage only ever targets the dev split; "test" is a schema violation (422)
    split: Literal["dev"] = "dev"


class TriageItem(FeedbackItem):
    user_sub: str
    question: str
    as_of: str
    abstained: bool
    in_test_split: bool


class FeedbackPage(BaseModel):
    items: list[TriageItem]
    next_cursor: str | None


def _item(row: dict[str, Any]) -> dict[str, Any]:
    return FeedbackItem.model_validate(row).model_dump(mode="json")


def _test_split(state: AppState, question: str) -> bool:
    try:
        return in_test_split(question, state.settings.root / "evals" / "datasets")
    except SplitRegistryUnavailable as exc:
        raise Problem(
            503, "Service Unavailable", "test split registry unavailable", "split_registry"
        ) from exc


@router.post(
    "/feedback",
    status_code=201,
    response_model=FeedbackItem,
    responses={200: {"model": FeedbackItem, "description": "Existing feedback updated"}},
)
async def post_feedback(
    req: FeedbackRequest,
    principal: Principal = Depends(current_principal),
    state: AppState = Depends(get_state),
) -> JSONResponse:
    async with state.services.pool.connection() as conn, conn.transaction():
        owner = await (
            await conn.execute("SELECT user_sub FROM answers WHERE run_id = %s", (req.run_id,))
        ).fetchone()
        if owner is None or owner[0] != principal["sub"]:
            raise not_found("run")
        cur = await conn.execute(
            f"""INSERT INTO feedback AS f (run_id, user_sub, rating, reason, comment)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (run_id, user_sub) DO UPDATE
                  SET rating = EXCLUDED.rating, reason = EXCLUDED.reason, comment = EXCLUDED.comment
                RETURNING {_COLUMNS}, (xmax = 0) AS inserted""",  # noqa: S608 - constant column list
            (req.run_id, principal["sub"], req.rating, req.reason, req.comment),
        )
        row = await cur.fetchone()
        assert row is not None
        names = [d.name for d in cur.description or []]
        record = dict(zip(names, row, strict=True))
        created = bool(record.pop("inserted"))
        await append_audit(
            conn,
            actor_sub=principal["sub"],
            actor_role=principal["role"],
            action="feedback",
            target=str(req.run_id),
            # the comment is free text from the user: it stays in the feedback table only
            details={
                "feedback_id": str(record["id"]),
                "rating": req.rating,
                "reason": req.reason,
                "created": created,
            },
        )
    return JSONResponse(_item(record), status_code=201 if created else 200)


def _decode_cursor(cursor: str | None) -> tuple[str, str] | None:
    if not cursor:
        return None
    try:
        ts, _, fid = base64.urlsafe_b64decode(cursor.encode()).decode().partition("|")
        uuid.UUID(fid)
        datetime.fromisoformat(ts)
    except ValueError as exc:
        raise Problem(422, "Unprocessable Content", "invalid cursor", "validation") from exc
    return ts, fid


@router.get("/feedback", response_model=FeedbackPage)
async def list_feedback(
    status: Status | None = None,
    rating: Rating | None = None,
    reason: Reason | None = None,
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    principal: Principal = Depends(require_role("content_admin")),
    state: AppState = Depends(get_state),
) -> dict[str, Any]:
    where: list[str] = ["true"]
    params: dict[str, Any] = {"limit": limit + 1}
    for name, value in (("status", status), ("rating", rating), ("reason", reason)):
        if value is not None:
            where.append(f"f.{name} = %({name})s")
            params[name] = value
    after = _decode_cursor(cursor)
    if after is not None:
        where.append("(f.created_at, f.id) < (%(ts)s::timestamptz, %(fid)s::uuid)")
        params["ts"], params["fid"] = after
    sql = f"""SELECT {_COLUMNS}, f.user_sub, a.question, a.as_of::text AS as_of, a.abstained
              FROM feedback f JOIN answers a ON a.run_id = f.run_id
              WHERE {" AND ".join(where)}
              ORDER BY f.created_at DESC, f.id DESC LIMIT %(limit)s"""  # noqa: S608 - fixed predicates, values bound
    async with state.services.pool.connection() as conn:
        cur = await conn.execute(sql, params)
        names = [d.name for d in cur.description or []]
        rows = [dict(zip(names, r, strict=True)) for r in await cur.fetchall()]
    page = rows[:limit]
    items = [
        TriageItem.model_validate({**r, "in_test_split": _test_split(state, r["question"])}).model_dump(
            mode="json"
        )
        for r in page
    ]
    next_cursor = None
    if len(rows) > limit:
        last = page[-1]
        token = f"{last['created_at'].isoformat()}|{last['id']}"
        next_cursor = base64.urlsafe_b64encode(token.encode()).decode()
    return {"items": items, "next_cursor": next_cursor}


@router.patch("/feedback/{feedback_id}", response_model=FeedbackItem)
async def triage_feedback(
    feedback_id: uuid.UUID,
    req: TriageRequest,
    principal: Principal = Depends(require_role("content_admin")),
    state: AppState = Depends(get_state),
) -> dict[str, Any]:
    async with state.services.pool.connection() as conn, conn.transaction():
        cur = await conn.execute(
            f"""SELECT {_COLUMNS}, a.question FROM feedback f JOIN answers a ON a.run_id = f.run_id
                WHERE f.id = %s FOR UPDATE OF f""",  # noqa: S608 - constant column list
            (feedback_id,),
        )
        row = await cur.fetchone()
        if row is None:
            raise not_found("feedback")
        names = [d.name for d in cur.description or []]
        record = dict(zip(names, row, strict=True))
        if req.status == "added_to_dev_set" and _test_split(state, record.pop("question")):
            raise Problem(
                422,
                "Unprocessable Content",
                "this question belongs to the held-out test split and cannot be added to the dev set",
                "test_split_triage",
            )
        record.pop("question", None)
        previous = record["status"]
        await conn.execute("UPDATE feedback SET status = %s WHERE id = %s", (req.status, feedback_id))
        record["status"] = req.status
        await append_audit(
            conn,
            actor_sub=principal["sub"],
            actor_role=principal["role"],
            action="feedback_triage",
            target=str(feedback_id),
            details={"from": previous, "to": req.status, "split": req.split, "run_id": str(record["run_id"])},
        )
    return _item(record)
