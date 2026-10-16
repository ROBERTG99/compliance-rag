"""ACL changes (FR-11): Postgres first (document_acl + denormalised chunks.acl_groups in one transaction),
then OpenSearch and Qdrant. ``sync_acl`` re-applies the stored ACL to the indexes and is idempotent."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass

from compliance_rag.ingest.pipeline import IngestDeps

VALID_GROUPS = {"all", "compliance", "legal", "support"}


class UnknownDocument(KeyError):
    pass


@dataclass(frozen=True)
class AclChange:
    job_id: str
    document_id: str
    groups: list[str]
    previous: list[str]
    indexes_synced: bool


async def change_acl(deps: IngestDeps, document_id: str, groups: list[str], actor: str) -> AclChange:
    groups = sorted(set(groups))
    if not groups or not set(groups) <= VALID_GROUPS:
        raise ValueError("groups must be a non-empty subset of all, compliance, legal, support")
    key = hashlib.sha256(f"acl_sync|{document_id}|{','.join(groups)}|{uuid.uuid4()}".encode()).hexdigest()
    async with deps.pool.connection() as conn, conn.transaction():
        row = await (
            await conn.execute("SELECT 1 FROM documents WHERE document_id = %s FOR UPDATE", (document_id,))
        ).fetchone()
        if row is None:
            raise UnknownDocument(document_id)
        prev = await (
            await conn.execute(
                "SELECT coalesce(array_agg(group_name ORDER BY group_name), '{}') FROM document_acl WHERE document_id = %s",
                (document_id,),
            )
        ).fetchone()
        await conn.execute("DELETE FROM document_acl WHERE document_id = %s", (document_id,))
        for g in groups:
            await conn.execute(
                "INSERT INTO document_acl (document_id, group_name, granted_by) VALUES (%s, %s, %s)",
                (document_id, g, actor),
            )
        await conn.execute("UPDATE chunks SET acl_groups = %s WHERE document_id = %s", (groups, document_id))
        job = await (
            await conn.execute(
                "INSERT INTO ingestion_jobs (idempotency_key, kind, document_id, status, requested_by) "
                "VALUES (%s, 'acl_sync', %s, 'indexing', %s) RETURNING id",
                (key, document_id, actor),
            )
        ).fetchone()
    assert job is not None
    synced = await sync_acl(deps, str(job[0]))
    return AclChange(str(job[0]), document_id, groups, list(prev[0] if prev else []), synced)


async def sync_acl(deps: IngestDeps, job_id: str) -> bool:
    """Mirror the document's current ACL into OpenSearch and Qdrant; returns True when both are in sync."""
    async with deps.pool.connection() as conn:
        row = await (
            await conn.execute(
                """UPDATE ingestion_jobs SET attempts = attempts + 1 WHERE id = %s
               RETURNING document_id, (SELECT array_agg(group_name ORDER BY group_name) FROM document_acl a
                                        WHERE a.document_id = ingestion_jobs.document_id)""",
                (job_id,),
            )
        ).fetchone()
    if row is None:
        raise KeyError(job_id)
    document_id, groups = row[0], list(row[1] or [])
    try:
        await deps.bm25.update_acl(document_id, groups)
        if deps.qdrant is not None:
            await deps.qdrant.update_acl(document_id, groups)
    except Exception as exc:
        async with deps.pool.connection() as conn:
            await conn.execute(
                "UPDATE ingestion_jobs SET error = %s WHERE id = %s",
                (f"{type(exc).__name__}: {exc}"[:2000], job_id),
            )
        return False
    async with deps.pool.connection() as conn:
        await conn.execute(
            "UPDATE ingestion_jobs SET status = 'done', finished_at = now(), error = NULL WHERE id = %s",
            (job_id,),
        )
    return True


async def index_lag(deps: IngestDeps) -> dict[str, float | int]:
    """p50/p95 seconds from enqueue to finish over the last 24 h, the pending count and the oldest pending age."""
    async with deps.pool.connection() as conn:
        row = await (
            await conn.execute(
                """SELECT
                 coalesce(percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM finished_at - enqueued_at))
                   FILTER (WHERE status = 'done' AND finished_at > now() - interval '24 hours'), 0),
                 coalesce(percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch FROM finished_at - enqueued_at))
                   FILTER (WHERE status = 'done' AND finished_at > now() - interval '24 hours'), 0),
                 count(*) FILTER (WHERE status NOT IN ('done', 'failed')),
                 coalesce(max(extract(epoch FROM now() - enqueued_at)) FILTER (WHERE status NOT IN ('done', 'failed')), 0)
               FROM ingestion_jobs"""
            )
        ).fetchone()
    assert row is not None
    return {
        "p50_s": round(float(row[0]), 3),
        "p95_s": round(float(row[1]), 3),
        "pending": int(row[2]),
        "oldest_pending_s": round(float(row[3]), 3),
    }
