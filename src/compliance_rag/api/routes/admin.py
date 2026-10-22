"""Admin: ACL changes, ingestion jobs and index lag."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from compliance_rag.api.deps import get_state, require_role
from compliance_rag.api.errors import Problem, not_found
from compliance_rag.api.schemas import AclAccepted, IndexLag, JobPage
from compliance_rag.api.state import AppState
from compliance_rag.retrieval.types import Principal
from compliance_rag.validation import DOCUMENT_ID_PATTERN, Group, JobKind, JobStatus
from compliance_rag.worker.acl import UnknownDocument, change_acl, index_lag

router = APIRouter(prefix="/v1", tags=["admin"])
log = structlog.get_logger(__name__)


class AclRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    groups: list[Group] = Field(min_length=1)


@router.put("/documents/{document_id}/acl", status_code=202, response_model=AclAccepted)
async def put_acl(
    req: AclRequest,
    document_id: str = Path(pattern=DOCUMENT_ID_PATTERN),
    principal: Principal = Depends(require_role("content_admin")),
    state: AppState = Depends(get_state),
) -> JSONResponse:
    try:
        change = await change_acl(
            state.services.ingest_deps(), document_id, list(req.groups), principal["sub"], principal["role"]
        )
    except UnknownDocument as exc:
        raise not_found("document") from exc
    except ValueError as exc:
        raise Problem(422, "Unprocessable Content", str(exc), "validation") from exc
    queue = await state.queue() if not change.indexes_synced else None
    if queue is not None:
        try:
            await queue.enqueue_job("sync_acl", change.job_id, _job_id=f"acl:{change.job_id}")
        except Exception as exc:  # committed and audited; the reconcile cron retries unfinished syncs
            log.warning("acl_sync_enqueue_failed", job_id=change.job_id, error=type(exc).__name__)
    return JSONResponse(
        {
            "job_id": change.job_id,
            "document_id": document_id,
            "groups": change.groups,
            "indexes_synced": change.indexes_synced,
        },
        status_code=202,
    )


@router.get("/ingestion-jobs", response_model=JobPage)
async def list_jobs(
    status: JobStatus | None = None,
    kind: JobKind | None = None,
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


@router.get("/index/lag", response_model=IndexLag)
async def get_index_lag(
    principal: Principal = Depends(require_role("content_admin")), state: AppState = Depends(get_state)
) -> dict[str, Any]:
    return await index_lag(state.services.ingest_deps())
