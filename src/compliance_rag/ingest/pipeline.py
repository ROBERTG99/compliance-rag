"""Ingestion pipeline (FR-1, FR-3).

Stages for one job: parse → chunk → score → embed → index (visible=false) → activate.
Activation is one Postgres transaction (new version active, previous version closed at the new
``valid_from``, chunks visible). OpenSearch and Qdrant are synced afterwards with idempotent
update-by-query calls, so a crash between stores is repaired by replaying the job (the job stays in
``activating`` until every store is in sync).
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from psycopg_pool import AsyncConnectionPool

from compliance_rag.db.audit import append_audit
from compliance_rag.embed.base import Embedder
from compliance_rag.guard.context_guard import injection_score
from compliance_rag.ingest.chunker import Chunk, chunk_text
from compliance_rag.ingest.loaders import FORMATS, extract_text, sniff_format
from compliance_rag.ingest.objectstore import ObjectStore
from compliance_rag.retrieval.bm25 import BM25Index
from compliance_rag.retrieval.types import ChunkRecord
from compliance_rag.retrieval.vector.pgvector import PgVectorStore
from compliance_rag.retrieval.vector.qdrant import QdrantStore

MAX_ATTEMPTS = 3
EXTENSIONS = {"pdf": "pdf", "docx": "docx", "html": "html", "md": "md"}
VALID_GROUPS = {"all", "compliance", "legal", "support"}


MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # mirrors the document_versions.size_bytes CHECK (NFR-6)


class VersionConflict(ValueError):
    """(document_id, version) already exists with different content."""


class AclConflict(ValueError):
    """An upload names different groups than the document's ACL; ACL changes go through PUT /acl (sync_acl)."""


class EmbedderNotReady(RuntimeError):
    """The embedder has not been fitted; run `crag seed` or `make reindex` first."""


@dataclass(frozen=True)
class DocumentMeta:
    document_id: str
    version: int
    title: str
    domain: str
    owner: str
    valid_from: date
    source_format: str
    acl_groups: list[str]
    valid_to: date | None = None


@dataclass(frozen=True)
class RegisteredJob:
    job_id: str
    document_id: str
    version: int
    version_id: str
    created: bool


@dataclass
class IngestDeps:
    pool: AsyncConnectionPool
    objects: ObjectStore
    bm25: BM25Index
    embedder: Embedder
    qdrant: QdrantStore | None = None
    # test hook: called after the Postgres activation commit, before other stores are synced
    after_pg_activation: Callable[[str], Awaitable[None]] | None = None
    pg: PgVectorStore = field(init=False)

    def __post_init__(self) -> None:
        self.pg = PgVectorStore(self.pool)


def content_sha256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def idempotency_key(kind: str, document_id: str, version: int | str, sha: str) -> str:
    return hashlib.sha256(f"{kind}|{document_id}|{version}|{sha}".encode()).hexdigest()


def chunk_id_for(version_id: str, ordinal: int) -> str:
    return hashlib.sha256(f"{version_id}|{ordinal}".encode()).hexdigest()[:32]


def raw_key(document_id: str, version: int, fmt: str) -> str:
    return f"raw/{document_id}/v{version}.{EXTENSIONS[fmt]}"


async def register_upload(
    deps: IngestDeps, meta: DocumentMeta, blob: bytes, requested_by: str, actor_role: str | None = None
) -> RegisteredJob:
    """Store the raw file and create the pending version + queued job. Identical bytes → same job."""
    if meta.source_format not in FORMATS:
        raise ValueError(f"unsupported format {meta.source_format}")
    if not set(meta.acl_groups) <= VALID_GROUPS or not meta.acl_groups:
        raise ValueError("acl_groups must be a non-empty subset of all, compliance, legal, support")
    if not 0 < len(blob) <= MAX_UPLOAD_BYTES:
        raise ValueError(f"file size must be between 1 byte and {MAX_UPLOAD_BYTES} bytes")
    sniff_format(blob, meta.source_format)
    sha = content_sha256(blob)
    key = idempotency_key("ingest", meta.document_id, meta.version, sha)
    async with deps.pool.connection() as conn:
        cur = await conn.execute(
            "SELECT j.id, j.version_id FROM ingestion_jobs j WHERE j.idempotency_key = %s", (key,)
        )
        row = await cur.fetchone()
        if row:
            return RegisteredJob(str(row[0]), meta.document_id, meta.version, str(row[1]), created=False)
    s3_key = raw_key(meta.document_id, meta.version, meta.source_format)
    # the documents upsert below row-locks the document, so concurrent uploads are serialised and the raw
    # object is written only after the ACL and version checks pass (a 409 never replaces stored bytes)
    async with deps.pool.connection() as conn, conn.transaction():
        await conn.execute(
            """INSERT INTO documents (document_id, title, domain, owner) VALUES (%s, %s, %s, %s)
               ON CONFLICT (document_id) DO UPDATE SET title = EXCLUDED.title, domain = EXCLUDED.domain,
               owner = EXCLUDED.owner""",
            (meta.document_id, meta.title, meta.domain, meta.owner),
        )
        cur = await conn.execute(
            "SELECT array_agg(group_name ORDER BY group_name) FROM document_acl WHERE document_id = %s",
            (meta.document_id,),
        )
        acl_row = await cur.fetchone()
        current = sorted(acl_row[0]) if acl_row and acl_row[0] else []
        if not current:
            for group in sorted(set(meta.acl_groups)):
                await conn.execute(
                    "INSERT INTO document_acl (document_id, group_name, granted_by) VALUES (%s, %s, %s)",
                    (meta.document_id, group, requested_by),
                )
        elif current != sorted(set(meta.acl_groups)):
            raise AclConflict(
                f"{meta.document_id} is shared with {current}; change its ACL with PUT /v1/documents/{{id}}/acl"
            )
        cur = await conn.execute(
            "SELECT id, content_sha256, status FROM document_versions WHERE document_id = %s AND version = %s",
            (meta.document_id, meta.version),
        )
        existing = await cur.fetchone()
        if existing and existing[1] != sha:
            raise VersionConflict(f"{meta.document_id} v{meta.version} already exists with different content")
        if existing and existing[2] == "active":
            # same bytes, already in force, and its job was purged by retention: record a finished job (the
            # idempotency key again) instead of re-indexing, which would hide the version while it runs
            cur = await conn.execute(
                """INSERT INTO ingestion_jobs (idempotency_key, kind, document_id, version_id, status, requested_by,
                       attempts, finished_at, chunk_count)
                   VALUES (%s, 'ingest', %s, %s, 'done', %s, 0, now(),
                           (SELECT count(*) FROM chunks WHERE version_id = %s))
                   ON CONFLICT (idempotency_key) DO UPDATE SET idempotency_key = EXCLUDED.idempotency_key
                   RETURNING id""",
                (key, meta.document_id, existing[0], requested_by, existing[0]),
            )
            done = await cur.fetchone()
            assert done is not None
            return RegisteredJob(
                str(done[0]), meta.document_id, meta.version, str(existing[0]), created=False
            )
        if existing:
            version_id = str(existing[0])
        else:
            await deps.objects.put(s3_key, blob)
            cur = await conn.execute(
                """INSERT INTO document_versions (document_id, version, content_sha256, source_format, s3_key,
                       size_bytes, valid_from, valid_to, status)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending') RETURNING id""",
                (
                    meta.document_id,
                    meta.version,
                    sha,
                    meta.source_format,
                    s3_key,
                    len(blob),
                    meta.valid_from,
                    meta.valid_to,
                ),
            )
            vrow = await cur.fetchone()
            assert vrow is not None
            version_id = str(vrow[0])
        cur = await conn.execute(
            """INSERT INTO ingestion_jobs (idempotency_key, kind, document_id, version_id, status, requested_by)
               VALUES (%s, 'ingest', %s, %s, 'queued', %s)
               ON CONFLICT (idempotency_key) DO UPDATE SET idempotency_key = EXCLUDED.idempotency_key
               RETURNING id, (xmax = 0) AS inserted""",
            (key, meta.document_id, version_id, requested_by),
        )
        jrow = await cur.fetchone()
        assert jrow is not None
        if actor_role is not None and jrow[1]:  # the upload audit row commits with the registration
            await append_audit(
                conn,
                actor_sub=requested_by,
                actor_role=actor_role,
                action="document_upload",
                target=f"{meta.document_id}@{meta.version}",
                details={"job_id": str(jrow[0]), "format": meta.source_format, "size_bytes": len(blob)},
            )
    return RegisteredJob(str(jrow[0]), meta.document_id, meta.version, version_id, created=bool(jrow[1]))


async def _set_job(pool: AsyncConnectionPool, job_id: str, status: str, **extra: Any) -> None:
    sets = ["status = %s"]
    params: list[Any] = [status]
    for col, value in extra.items():
        sets.append(f"{col} = %s")
        params.append(value)
    if status in {"done", "failed"}:
        sets.append("finished_at = now()")
    params.append(job_id)
    async with pool.connection() as conn:
        await conn.execute(f"UPDATE ingestion_jobs SET {', '.join(sets)} WHERE id = %s", params)  # noqa: S608


async def _load_version(pool: AsyncConnectionPool, version_id: str) -> dict[str, Any]:
    async with pool.connection() as conn:
        cur = await conn.execute(
            """SELECT v.id, v.document_id, v.version, v.source_format, v.s3_key, v.valid_from, v.valid_to,
                      v.status, v.extracted_text, d.title, d.domain,
                      COALESCE((SELECT array_agg(group_name ORDER BY group_name) FROM document_acl a
                                WHERE a.document_id = v.document_id), '{}') AS acl_groups
               FROM document_versions v JOIN documents d ON d.document_id = v.document_id WHERE v.id = %s""",
            (version_id,),
        )
        row = await cur.fetchone()
        cols = [d.name for d in cur.description or []]
    if row is None:
        raise KeyError(version_id)
    out = dict(zip(cols, row, strict=True))
    out["id"] = str(out["id"])
    return out


@dataclass
class ParsedVersion:
    version: dict[str, Any]
    text: str
    chunks: list[Chunk]


async def parse_version(deps: IngestDeps, version_id: str) -> ParsedVersion:
    version = await _load_version(deps.pool, version_id)
    blob = await deps.objects.get(version["s3_key"])
    text = await asyncio.to_thread(extract_text, blob, version["source_format"])
    chunks = await asyncio.to_thread(chunk_text, text)
    async with deps.pool.connection() as conn:
        await conn.execute(
            "UPDATE document_versions SET extracted_text = %s, status = 'indexing' WHERE id = %s",
            (text, version_id),
        )
    return ParsedVersion(version=version, text=text, chunks=chunks)


def build_records(parsed: ParsedVersion, embedder: Embedder) -> list[ChunkRecord]:
    v = parsed.version
    if not parsed.chunks:
        return []
    if hasattr(embedder, "fitted") and not embedder.fitted:
        raise EmbedderNotReady("embedder is not fitted; run `crag seed` or `make reindex`")
    vectors = embedder.embed_documents([c.section_path + "\n" + c.text for c in parsed.chunks])
    return [
        ChunkRecord(
            chunk_id=chunk_id_for(v["id"], c.ordinal),
            version_id=v["id"],
            document_id=v["document_id"],
            version=int(v["version"]),
            title=v["title"],
            domain=v["domain"],
            ordinal=c.ordinal,
            section_path=c.section_path,
            text=c.text,
            char_start=c.char_start,
            char_end=c.char_end,
            token_count=c.token_count,
            injection_score=injection_score(c.text),
            acl_groups=list(v["acl_groups"]),
            valid_from=v["valid_from"],
            valid_to=v["valid_to"],
            visible=False,
            embedding=vectors[i],
        )
        for i, c in enumerate(parsed.chunks)
    ]


async def write_indexes(deps: IngestDeps, records: list[ChunkRecord]) -> None:
    if not records:
        return
    await deps.pg.upsert(records)
    await deps.bm25.bulk_index(records)
    if deps.qdrant is not None:
        await deps.qdrant.upsert(records)


@dataclass(frozen=True)
class Activation:
    version_id: str
    valid_to: date | None
    closed_version_id: str | None
    closed_valid_to: date | None
    document_id: str = ""


async def activate_in_postgres(pool: AsyncConnectionPool, version_id: str) -> Activation:
    """Make the version active and close the one it supersedes, atomically (replay-safe)."""
    async with pool.connection() as conn, conn.transaction():
        cur = await conn.execute(
            "SELECT document_id, valid_from, valid_to, status, version FROM document_versions WHERE id = %s FOR UPDATE",
            (version_id,),
        )
        row = await cur.fetchone()
        assert row is not None
        document_id, valid_from, own_valid_to, previous_status, version = row
        await conn.execute("SELECT 1 FROM documents WHERE document_id = %s FOR UPDATE", (document_id,))
        # the version this one supersedes: latest active version that starts earlier
        cur = await conn.execute(
            """SELECT id, valid_to FROM document_versions
               WHERE document_id = %s AND status = 'active' AND id <> %s AND valid_from < %s
               ORDER BY valid_from DESC LIMIT 1""",
            (document_id, version_id, valid_from),
        )
        prev = await cur.fetchone()
        # a later active version (out-of-order ingestion) bounds this one
        cur = await conn.execute(
            """SELECT min(valid_from) FROM document_versions
               WHERE document_id = %s AND status = 'active' AND id <> %s AND valid_from > %s""",
            (document_id, version_id, valid_from),
        )
        nxt = await cur.fetchone()
        # keep an explicit end date unless a later version starts earlier
        ends = [d for d in (nxt[0] if nxt else None, own_valid_to) if d is not None]
        new_valid_to = min(ends) if ends else None
        closed_id: str | None = None
        if prev is not None and (prev[1] is None or prev[1] > valid_from):
            closed_id = str(prev[0])
            await conn.execute(
                "UPDATE document_versions SET valid_to = %s WHERE id = %s", (valid_from, prev[0])
            )
            await conn.execute("UPDATE chunks SET valid_to = %s WHERE version_id = %s", (valid_from, prev[0]))
        await conn.execute(
            """UPDATE document_versions SET status = 'active', valid_to = %s,
                      activated_at = COALESCE(activated_at, now()) WHERE id = %s""",
            (new_valid_to, version_id),
        )
        # the chunks were built with the ACL read at parse time; an ACL change since then (serialised with
        # this transaction by the documents row lock) must reach them before they become visible
        await conn.execute(
            f"""UPDATE chunks SET visible = true, valid_to = %s, acl_groups = ({_CURRENT_ACL})
               WHERE version_id = %s""",  # noqa: S608 - constant SQL fragment
            (new_valid_to, document_id, version_id),
        )
        if previous_status != "active":  # replays of an activated version add no audit row
            await append_audit(
                conn,
                actor_sub="worker",
                actor_role="system",
                action="version_activate",
                target=f"{document_id}@{version}",
                details={
                    "version_id": version_id,
                    "valid_from": valid_from.isoformat(),
                    "valid_to": new_valid_to.isoformat() if new_valid_to else None,
                    "closed_version_id": closed_id,
                },
            )
    return Activation(
        version_id, new_valid_to, closed_id, valid_from if closed_id else None, str(document_id)
    )


_CURRENT_ACL = "SELECT coalesce(array_agg(group_name ORDER BY group_name), '{}') FROM document_acl WHERE document_id = %s"


async def _current_acl(pool: AsyncConnectionPool, document_id: str) -> list[str]:
    async with pool.connection() as conn:
        row = await (await conn.execute(_CURRENT_ACL, (document_id,))).fetchone()
    return list(row[0]) if row else []


async def _sync_document_acl(deps: IngestDeps, document_id: str) -> None:
    """Push the document's current ACL to the search indexes until it stops changing under us."""
    groups = await _current_acl(deps.pool, document_id)
    for _ in range(3):
        await deps.bm25.update_acl(document_id, groups)
        if deps.qdrant:
            await deps.qdrant.update_acl(document_id, groups)
        latest = await _current_acl(deps.pool, document_id)
        if latest == groups:
            return
        groups = latest
    raise RuntimeError(f"ACL of {document_id} kept changing during activation; the job will be retried")


async def sync_activation(deps: IngestDeps, act: Activation) -> None:
    """Idempotently mirror the Postgres activation into OpenSearch and Qdrant."""
    await deps.bm25.refresh()  # update-by-query only sees refreshed documents
    if act.document_id:
        await _sync_document_acl(deps, act.document_id)  # before the version becomes visible
    if act.closed_version_id and act.closed_valid_to:
        await deps.bm25.close_version(act.closed_version_id, act.closed_valid_to)
        if deps.qdrant:
            await deps.qdrant.close_version(act.closed_version_id, act.closed_valid_to)
    if act.valid_to:
        await deps.bm25.close_version(act.version_id, act.valid_to)
        if deps.qdrant:
            await deps.qdrant.close_version(act.version_id, act.valid_to)
    await deps.bm25.set_visible(act.version_id, True)
    if deps.qdrant:
        await deps.qdrant.set_visible(act.version_id, True)


async def _current_activation(pool: AsyncConnectionPool, version_id: str) -> Activation:
    """Rebuild the activation facts from Postgres (used when replaying an ``activating`` job)."""
    async with pool.connection() as conn:
        cur = await conn.execute(
            """SELECT v.valid_to, p.id, p.valid_to, v.document_id FROM document_versions v
               LEFT JOIN LATERAL (SELECT id, valid_to FROM document_versions p
                                  WHERE p.document_id = v.document_id AND p.valid_to = v.valid_from
                                  AND p.status = 'active' LIMIT 1) p ON true
               WHERE v.id = %s""",
            (version_id,),
        )
        row = await cur.fetchone()
    assert row is not None
    return Activation(version_id, row[0], str(row[1]) if row[1] else None, row[2], str(row[3]))


@dataclass(frozen=True)
class JobResult:
    job_id: str
    status: str
    chunk_count: int
    seconds: float


async def ingest_document(deps: IngestDeps, job_id: str) -> JobResult:
    started = time.perf_counter()
    async with deps.pool.connection() as conn:
        cur = await conn.execute(
            "UPDATE ingestion_jobs SET attempts = attempts + 1 WHERE id = %s RETURNING status, version_id, attempts",
            (job_id,),
        )
        row = await cur.fetchone()
    if row is None:
        raise KeyError(f"unknown job {job_id}")
    status, version_id, attempts = row[0], str(row[1]), int(row[2])
    if status == "done":
        return JobResult(job_id, "done", 0, 0.0)
    try:
        chunk_count = 0
        if status != "activating":
            await _set_job(deps.pool, job_id, "parsing", error=None)
            parsed = await parse_version(deps, version_id)
            await _set_job(deps.pool, job_id, "embedding")
            records = await asyncio.to_thread(build_records, parsed, deps.embedder)  # CPU / provider I/O
            chunk_count = len(records)
            await _set_job(deps.pool, job_id, "indexing", chunk_count=chunk_count)
            await write_indexes(deps, records)
            await _set_job(deps.pool, job_id, "activating")
            activation = await activate_in_postgres(deps.pool, version_id)
            if deps.after_pg_activation is not None:
                await deps.after_pg_activation(version_id)
        else:
            async with deps.pool.connection() as conn:
                cur = await conn.execute("SELECT status FROM document_versions WHERE id = %s", (version_id,))
                vrow = await cur.fetchone()
            if vrow and vrow[0] == "active":
                activation = await _current_activation(deps.pool, version_id)
            else:  # crashed inside the activation transaction: nothing was committed
                activation = await activate_in_postgres(deps.pool, version_id)
        await sync_activation(deps, activation)
        await deps.bm25.refresh()
        extra: dict[str, Any] = {"error": None}
        if chunk_count:
            extra["chunk_count"] = chunk_count
        await _set_job(deps.pool, job_id, "done", **extra)
        return JobResult(job_id, "done", chunk_count, time.perf_counter() - started)
    except Exception as exc:
        final = attempts >= MAX_ATTEMPTS
        async with deps.pool.connection() as conn:
            await conn.execute(
                "UPDATE ingestion_jobs SET error = %s, status = CASE WHEN %s THEN 'failed' ELSE status END, "
                "finished_at = CASE WHEN %s THEN now() ELSE finished_at END WHERE id = %s",
                (f"{type(exc).__name__}: {exc}"[:2000], final, final, job_id),
            )
            if final:
                await conn.execute(
                    "UPDATE document_versions SET status = 'failed' WHERE id = %s AND status <> 'active'",
                    (version_id,),
                )
        raise


async def replay_failed_jobs(
    pool: AsyncConnectionPool, enqueue: Callable[[str], Awaitable[None]]
) -> list[str]:
    """Re-queue every failed ingest job (``crag jobs replay-failed``); every pipeline step is idempotent.

    Each job is reset (attempts 0, no error) and its version back to ``pending`` before it is enqueued; a job
    whose version is already active (it failed while syncing the indexes) resumes at ``activating``. If the
    queue refuses a job, its failed state is restored so a later replay picks it up again.
    """
    async with pool.connection() as conn:
        rows = await (
            await conn.execute(
                "SELECT id FROM ingestion_jobs WHERE kind = 'ingest' AND status = 'failed' ORDER BY enqueued_at"
            )
        ).fetchall()
    replayed: list[str] = []
    for (job_id,) in rows:
        async with pool.connection() as conn, conn.transaction():
            saved = await (
                await conn.execute(
                    "SELECT j.attempts, j.error, j.finished_at, v.status FROM ingestion_jobs j "
                    "JOIN document_versions v ON v.id = j.version_id WHERE j.id = %s AND j.status = 'failed' "
                    "FOR UPDATE OF j",
                    (job_id,),
                )
            ).fetchone()
            if saved is None:  # replayed concurrently
                continue
            # a version already active failed while syncing the indexes: resume at activation
            await conn.execute(
                "UPDATE ingestion_jobs SET status = %s, attempts = 0, error = NULL, finished_at = NULL WHERE id = %s",
                ("activating" if saved[3] == "active" else "queued", job_id),
            )
            await conn.execute(
                "UPDATE document_versions SET status = 'pending' "
                "WHERE id = (SELECT version_id FROM ingestion_jobs WHERE id = %s) AND status = 'failed'",
                (job_id,),
            )
        try:
            await enqueue(str(job_id))
        except Exception:
            async with pool.connection() as conn, conn.transaction():
                await conn.execute(
                    "UPDATE ingestion_jobs SET status = 'failed', attempts = %s, error = %s, finished_at = %s "
                    "WHERE id = %s AND status IN ('queued', 'activating')",
                    (saved[0], saved[1], saved[2], job_id),
                )
                await conn.execute(
                    "UPDATE document_versions SET status = %s "
                    "WHERE id = (SELECT version_id FROM ingestion_jobs WHERE id = %s) AND status = 'pending'",
                    (saved[3], job_id),
                )
            raise
        replayed.append(str(job_id))
    return replayed
