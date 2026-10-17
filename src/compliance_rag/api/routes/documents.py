"""Documents: upload (FR-1), S3 import, authorised library and version timeline, chunk evidence."""

from __future__ import annotations

import base64
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Path, Query, Request, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from compliance_rag.api.deps import current_principal, get_state, require_role
from compliance_rag.api.errors import Problem, not_found
from compliance_rag.api.schemas import ChunkOut, DocumentDetail, DocumentPage
from compliance_rag.api.state import AppState
from compliance_rag.db.audit import append_audit
from compliance_rag.ingest.objectstore import ObjectNotFound
from compliance_rag.ingest.pipeline import RegisteredJob, idempotency_key, register_upload
from compliance_rag.ingest.s3 import DocumentMetadata, format_for
from compliance_rag.retrieval.types import Principal
from compliance_rag.validation import (
    DOCUMENT_ID_PATTERN,
    GROUP_LIST_PATTERN,
    Domain,
    Group,
    IsoDate,
    SafeText,
)

router = APIRouter(prefix="/v1", tags=["documents"])


class UploadAccepted(BaseModel):
    job_id: str
    document_id: str
    version: int


class FromS3Request(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: SafeText = Field(min_length=1, max_length=512)
    metadata: DocumentMetadata


async def _enqueue(state: AppState, job: RegisteredJob, sha: str) -> None:
    if state.arq is None:
        raise Problem(
            503,
            "Service Unavailable",
            "the ingestion queue is unavailable",
            "queue_unavailable",
            retryable=True,
        )
    key = idempotency_key("ingest", job.document_id, job.version, sha)
    await state.arq.enqueue_job("ingest_document", job.job_id, _job_id=key)


async def _register(
    state: AppState, principal: Principal, meta: DocumentMetadata, blob: bytes, source_format: str
) -> UploadAccepted:
    import hashlib

    if state.arq is None:  # BUILD.md §4.7: Redis down → upload 503
        raise Problem(
            503,
            "Service Unavailable",
            "the ingestion queue is unavailable",
            "queue_unavailable",
            retryable=True,
        )
    try:
        doc_meta = meta.to_meta(source_format)
    except ValueError as exc:
        raise Problem(422, "Unprocessable Content", str(exc), "validation") from exc
    try:
        job = await register_upload(state.services.ingest_deps(), doc_meta, blob, principal["sub"])
    except (ConnectionError, OSError) as exc:
        raise Problem(
            503, "Service Unavailable", "object storage is unavailable", "storage_unavailable", retryable=True
        ) from exc
    await _enqueue(state, job, hashlib.sha256(blob).hexdigest())
    if job.created:
        async with state.services.pool.connection() as conn:
            await append_audit(
                conn,
                actor_sub=principal["sub"],
                actor_role=principal["role"],
                action="document_upload",
                target=f"{job.document_id}@{job.version}",
                details={"job_id": job.job_id, "format": source_format, "size_bytes": len(blob)},
            )
    return UploadAccepted(job_id=job.job_id, document_id=job.document_id, version=job.version)


@router.post("/documents", status_code=202, response_model=UploadAccepted)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    document_id: str = Form(..., pattern=DOCUMENT_ID_PATTERN),
    version: int = Form(..., ge=1),
    title: SafeText = Form(..., min_length=1, max_length=300),
    domain: Domain = Form(...),
    owner: SafeText = Form(..., min_length=1, max_length=120),
    valid_from: IsoDate = Form(...),
    valid_to: IsoDate | None = Form(None),
    acl_groups: str = Form(
        ..., pattern=GROUP_LIST_PATTERN, description="comma-separated: all, compliance, legal, support"
    ),
    principal: Principal = Depends(require_role("content_admin")),
    state: AppState = Depends(get_state),
) -> UploadAccepted:
    limit = state.settings.max_upload_bytes
    fmt = format_for(file.filename or "")
    if fmt is None:
        raise Problem(
            415, "Unsupported Media Type", "upload a PDF, DOCX, HTML or Markdown file", "unsupported_document"
        )
    blob = await file.read(limit + 1)
    if len(blob) > limit:
        raise Problem(
            413,
            "Content Too Large",
            f"uploads are limited to {state.settings.max_upload_mb} MB",
            "upload_too_large",
        )
    if not blob:
        raise Problem(422, "Unprocessable Content", "empty file", "validation")
    try:
        meta = DocumentMetadata(
            document_id=document_id,
            version=version,
            title=title,
            domain=domain,
            owner=owner,
            valid_from=valid_from,
            valid_to=valid_to,
            acl_groups=acl_groups,
        )
    except ValidationError as exc:
        raise Problem(
            422,
            "Unprocessable Content",
            "invalid document metadata",
            "validation",
            errors=[{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()],
        ) from exc
    return await _register(state, principal, meta, blob, fmt)


@router.post("/documents:from-s3", status_code=202, response_model=UploadAccepted)
async def import_from_s3(
    req: FromS3Request,
    principal: Principal = Depends(require_role("content_admin")),
    state: AppState = Depends(get_state),
) -> UploadAccepted:
    fmt = format_for(req.key)
    if fmt is None:
        raise Problem(415, "Unsupported Media Type", "unsupported file extension", "unsupported_document")
    try:
        blob = await state.services.objects.get(req.key)
    except ObjectNotFound as exc:
        raise not_found("object") from exc
    if len(blob) > state.settings.max_upload_bytes:
        raise Problem(413, "Content Too Large", "object exceeds the upload limit", "upload_too_large")
    return await _register(state, principal, req.metadata, blob, fmt)


def _cursor_decode(cursor: str | None) -> str:
    if not cursor:
        return ""
    try:
        after = base64.urlsafe_b64decode(cursor.encode()).decode()
        if "\x00" in after:
            raise ValueError("NUL in cursor")
        return after
    except Exception as exc:
        raise Problem(422, "Unprocessable Content", "invalid cursor", "validation") from exc


@router.get("/documents", response_model=DocumentPage, response_model_exclude_unset=True)
async def list_documents(
    group: Group | None = None,
    domain: Domain | None = None,
    valid_at: IsoDate | None = None,
    q: SafeText | None = Query(None, max_length=200),
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    principal: Principal = Depends(current_principal),
    state: AppState = Depends(get_state),
) -> dict[str, Any]:
    groups = principal["groups"]
    if group is not None:
        if group not in groups:
            return {"items": [], "next_cursor": None}
        groups = [group]
    params: dict[str, Any] = {
        "groups": groups,
        "after": _cursor_decode(cursor),
        "limit": limit + 1,
        "today": date.today(),
    }
    where = [
        "EXISTS (SELECT 1 FROM document_acl a WHERE a.document_id = d.document_id AND a.group_name = ANY(%(groups)s))",
        "d.document_id > %(after)s",
    ]
    if domain:
        where.append("d.domain = %(domain)s")
        params["domain"] = domain
    if q:
        where.append("(d.title ILIKE %(q)s OR d.document_id ILIKE %(q)s)")
        params["q"] = f"%{q}%"
    if valid_at:
        where.append(
            "EXISTS (SELECT 1 FROM document_versions v WHERE v.document_id = d.document_id AND v.status = "
            "'active' AND v.valid_from <= %(valid_at)s AND (v.valid_to IS NULL OR v.valid_to > %(valid_at)s))"
        )
        params["valid_at"] = valid_at
    sql = f"""
        SELECT d.document_id, d.title, d.domain, d.owner,
               (SELECT array_agg(group_name ORDER BY group_name) FROM document_acl a WHERE a.document_id = d.document_id),
               (SELECT max(version) FROM document_versions v WHERE v.document_id = d.document_id AND v.status = 'active'
                  AND v.valid_from <= %(today)s AND (v.valid_to IS NULL OR v.valid_to > %(today)s)),
               (SELECT count(*) FROM document_versions v WHERE v.document_id = d.document_id)
        FROM documents d WHERE {" AND ".join(where)} ORDER BY d.document_id LIMIT %(limit)s"""  # noqa: S608
    async with state.services.pool.connection() as conn:
        rows = await (await conn.execute(sql, params)).fetchall()
    is_admin = principal["role"] == "content_admin"
    items = [
        {
            "document_id": r[0],
            "title": r[1],
            "domain": r[2],
            "owner": r[3],
            "current_version": r[5],
            "versions": int(r[6]),
            "restricted": "all" not in (r[4] or []),
            **({"acl_groups": list(r[4] or [])} if is_admin else {}),
        }
        for r in rows[:limit]
    ]
    next_cursor = (
        base64.urlsafe_b64encode(rows[limit - 1][0].encode()).decode() if len(rows) > limit else None
    )
    return {"items": items, "next_cursor": next_cursor}


async def _authorized_document(state: AppState, principal: Principal, document_id: str) -> tuple[Any, ...]:
    async with state.services.pool.connection() as conn:
        row = await (
            await conn.execute(
                """SELECT d.document_id, d.title, d.domain, d.owner,
                      (SELECT array_agg(group_name ORDER BY group_name) FROM document_acl a
                        WHERE a.document_id = d.document_id)
               FROM documents d WHERE d.document_id = %s AND EXISTS (SELECT 1 FROM document_acl a
                 WHERE a.document_id = d.document_id AND a.group_name = ANY(%s))""",
                (document_id, principal["groups"]),
            )
        ).fetchone()
    if row is None:
        raise not_found("document")
    return tuple(row)


@router.get("/documents/{document_id}", response_model=DocumentDetail, response_model_exclude_unset=True)
async def get_document(
    document_id: str = Path(pattern=DOCUMENT_ID_PATTERN),
    principal: Principal = Depends(current_principal),
    state: AppState = Depends(get_state),
) -> dict[str, Any]:
    doc = await _authorized_document(state, principal, document_id)
    async with state.services.pool.connection() as conn:
        rows = await (
            await conn.execute(
                """SELECT v.version, v.status, v.source_format, v.valid_from, v.valid_to, v.uploaded_at, v.activated_at,
                      v.size_bytes, (SELECT count(*) FROM chunks c WHERE c.version_id = v.id)
               FROM document_versions v WHERE v.document_id = %s ORDER BY v.version""",
                (document_id,),
            )
        ).fetchall()
    today = date.today()
    versions = [
        {
            "version": r[0],
            "status": r[1],
            "source_format": r[2],
            "valid_from": r[3].isoformat(),
            "valid_to": r[4].isoformat() if r[4] else None,
            "uploaded_at": r[5].isoformat(),
            "activated_at": r[6].isoformat() if r[6] else None,
            "size_bytes": r[7],
            "chunks": int(r[8]),
            "in_force": r[1] == "active" and r[3] <= today and (r[4] is None or today < r[4]),
        }
        for r in rows
    ]
    result: dict[str, Any] = {
        "document_id": doc[0],
        "title": doc[1],
        "domain": doc[2],
        "owner": doc[3],
        "restricted": "all" not in (doc[4] or []),
        "versions": versions,
    }
    if principal["role"] == "content_admin":
        result["acl_groups"] = list(doc[4] or [])
    return result


@router.get("/chunks/{chunk_id}", response_model=ChunkOut)
async def get_chunk(
    chunk_id: str,
    response: Response,
    principal: Principal = Depends(current_principal),
    state: AppState = Depends(get_state),
) -> dict[str, Any]:
    if len(chunk_id) != 32 or any(c not in "0123456789abcdef" for c in chunk_id):
        raise not_found("chunk")
    async with state.services.pool.connection() as conn:
        row = await (
            await conn.execute(
                """SELECT c.chunk_id, c.document_id, v.version, c.section_path, c.text, c.char_start, c.char_end,
                      c.valid_from, c.valid_to, d.title,
                      (SELECT max(cv.version) FROM document_versions cv WHERE cv.document_id = c.document_id
                         AND cv.status = 'active' AND cv.valid_to IS NULL)
               FROM chunks c JOIN document_versions v ON v.id = c.version_id JOIN documents d ON d.document_id = c.document_id
               WHERE c.chunk_id = %s AND c.visible AND c.acl_groups && %s::text[]""",
                (chunk_id, principal["groups"]),
            )
        ).fetchone()
        if row is None:
            raise not_found("chunk")
        await append_audit(
            conn,
            actor_sub=principal["sub"],
            actor_role=principal["role"],
            action="evidence_view",
            target=chunk_id,
            details={"document_id": row[1], "version": row[2]},
        )
    today = date.today()
    valid_to = row[8]
    response.headers["Cache-Control"] = "private, no-store"
    return {
        "chunk_id": row[0],
        "document_id": row[1],
        "version": row[2],
        "section_path": row[3],
        "text": row[4],
        "char_start": row[5],
        "char_end": row[6],
        "valid_from": row[7].isoformat(),
        "valid_to": valid_to.isoformat() if valid_to else None,
        "title": row[9],
        "current_version": row[10],
        "superseded": valid_to is not None and valid_to <= today,
    }
