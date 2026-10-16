"""Admin: ACL changes, ingestion jobs and index lag (FR-14)."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from compliance_rag.api.deps import get_state, require_role
from compliance_rag.api.errors import Problem, not_found
from compliance_rag.api.state import AppState
from compliance_rag.db.audit import append_audit
from compliance_rag.retrieval.types import Principal
from compliance_rag.worker.acl import UnknownDocument, change_acl, index_lag

router = APIRouter(prefix="/v1", tags=["admin"])
Group = Literal["all", "compliance", "legal", "support"]


class AclRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    groups: list[Group] = Field(min_length=1)


@router.put("/documents/{document_id}/acl", status_code=202)
async def put_acl(
    document_id: str,
    req: AclRequest,
    principal: Principal = Depends(require_role("content_admin")),
    state: AppState = Depends(get_state),
) -> JSONResponse:
    try:
        change = await change_acl(
            state.services.ingest_deps(), document_id, list(req.groups), principal["sub"]
        )
    except UnknownDocument as exc:
        raise not_found("document") from exc
    except ValueError as exc:
        raise Problem(422, "Unprocessable Content", str(exc), "validation") from exc
    if not change.indexes_synced and state.arq is not None:
        await state.arq.enqueue_job("sync_acl", change.job_id, _job_id=f"acl:{change.job_id}")
    async with state.services.pool.connection() as conn:
        await append_audit(
            conn,
            actor_sub=principal["sub"],
            actor_role=principal["role"],
            action="acl_change",
            target=document_id,
            details={"from": change.previous, "to": change.groups, "job_id": change.job_id},
        )
    return JSONResponse(
        {
            "job_id": change.job_id,
            "document_id": document_id,
            "groups": change.groups,
            "indexes_synced": change.indexes_synced,
        },
        status_code=202,
    )


@router.get("/ingestion-jobs")
async def list_jobs(
    status: str | None = None,
    kind: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    principal: Principal = Depends(require_role("content_admin")),
    state: AppState = Depends(get_state),
) -> dict[str, Any]:
    where: list[str] = ["true"]
    params: dict[str, Any] = {"limit": limit}
    if status:
        where.append("j.status = %(status)s")
        params["status"] = status
    if kind:
        where.append("j.kind = %(kind)s")
        params["kind"] = kind
    sql = f"""SELECT j.id, j.kind, j.document_id, v.version, j.status, j.attempts, j.error, j.requested_by,
                     j.enqueued_at, j.finished_at, j.chunk_count
              FROM ingestion_jobs j LEFT JOIN document_versions v ON v.id = j.version_id
              WHERE {" AND ".join(where)} ORDER BY j.enqueued_at DESC LIMIT %(limit)s"""  # noqa: S608
    async with state.services.pool.connection() as conn:
        rows = await (await conn.execute(sql, params)).fetchall()
    keys = [
        "job_id",
        "kind",
        "document_id",
        "version",
        "status",
        "attempts",
        "error",
        "requested_by",
        "enqueued_at",
        "finished_at",
        "chunk_count",
    ]
    items = []
    for r in rows:
        item = dict(zip(keys, r, strict=True))
        item["job_id"] = str(item["job_id"])
        for k in ("enqueued_at", "finished_at"):
            item[k] = item[k].isoformat() if item[k] else None
        items.append(item)
    return {"items": items}


@router.get("/index/lag")
async def get_index_lag(
    principal: Principal = Depends(require_role("content_admin")), state: AppState = Depends(get_state)
) -> dict[str, Any]:
    return await index_lag(state.services.ingest_deps())
