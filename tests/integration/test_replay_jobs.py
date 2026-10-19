"""`crag jobs replay-failed` re-queues failed ingestion jobs (runbook, `make replay-failed-jobs`)."""

from __future__ import annotations

from datetime import date

import pytest

from compliance_rag.ingest.pipeline import (
    MAX_ATTEMPTS,
    DocumentMeta,
    FinalIngestFailure,
    IngestDeps,
    RegisteredJob,
    ingest_document,
    register_upload,
    replay_failed_jobs,
)
from data.generator.corpus import SEED, build_corpus
from data.generator.render import render_version

pytestmark = pytest.mark.integration


async def _failed_job(deps: IngestDeps, document_id: str) -> RegisteredJob:
    policy = next(p for p in build_corpus(SEED) if p.document_id == document_id)
    v = policy.versions[0]
    meta = DocumentMeta(
        policy.document_id,
        v.version,
        policy.title,
        policy.domain,
        policy.owner,
        date.fromisoformat(v.valid_from),
        v.source_format,
        policy.acl_groups,
    )
    job = await register_upload(deps, meta, render_version(policy, v), "admin@northwind.test")
    async with deps.pool.connection() as conn:
        await conn.execute(
            "UPDATE ingestion_jobs SET status = 'failed', attempts = 3, error = 'boom', finished_at = now() "
            "WHERE id = %s",
            (job.job_id,),
        )
        await conn.execute("UPDATE document_versions SET status = 'failed' WHERE id = %s", (job.version_id,))
    return job


async def _state(deps: IngestDeps, job_id: str) -> tuple[str, int, str | None, object, str]:
    async with deps.pool.connection() as conn:
        row = await (
            await conn.execute(
                "SELECT j.status, j.attempts, j.error, j.finished_at, v.status FROM ingestion_jobs j "
                "JOIN document_versions v ON v.id = j.version_id WHERE j.id = %s",
                (job_id,),
            )
        ).fetchone()
    assert row is not None
    return row[0], row[1], row[2], row[3], row[4]


async def test_replay_requeues_failed_jobs_once(ingest_deps: IngestDeps) -> None:
    job = await _failed_job(ingest_deps, "AML-0107")
    enqueued: list[str] = []

    async def enqueue(job_id: str) -> None:
        enqueued.append(job_id)

    replayed = await replay_failed_jobs(ingest_deps.pool, enqueue)

    assert job.job_id in replayed and enqueued == replayed
    assert await _state(ingest_deps, job.job_id) == ("queued", 0, None, None, "pending")
    assert await replay_failed_jobs(ingest_deps.pool, enqueue) == []  # nothing failed any more


async def test_replay_restores_failed_state_when_the_queue_is_down(ingest_deps: IngestDeps) -> None:
    job = await _failed_job(ingest_deps, "AML-0014")

    async def enqueue(_job_id: str) -> None:
        raise ConnectionError("redis down")

    with pytest.raises(ConnectionError):
        await replay_failed_jobs(ingest_deps.pool, enqueue)

    status, attempts, error, finished_at, version_status = await _state(ingest_deps, job.job_id)
    assert (status, version_status) == ("failed", "failed")
    assert attempts == 3 and error == "boom" and finished_at is not None


async def test_replay_resumes_a_job_that_failed_after_activation(ingest_deps: IngestDeps) -> None:
    # the last attempt failed while syncing the indexes, after the Postgres activation had committed: the
    # replay must resume at activation, not re-parse and re-index a version that is already live
    job = await _failed_job(ingest_deps, "AML-0021")
    assert (await ingest_document(ingest_deps, job.job_id)).status == "done"
    async with ingest_deps.pool.connection() as conn:
        await conn.execute(
            "UPDATE ingestion_jobs SET status = 'failed', error = 'ConnectionError: opensearch' WHERE id = %s",
            (job.job_id,),
        )
    visible_before = await _visible_chunks(ingest_deps, job.version_id)
    enqueued: list[str] = []

    async def enqueue(job_id: str) -> None:
        enqueued.append(job_id)

    await replay_failed_jobs(ingest_deps.pool, enqueue)
    status, attempts, _, _, version_status = await _state(ingest_deps, job.job_id)
    assert (status, attempts, version_status) == ("activating", 0, "active")

    assert (await ingest_document(ingest_deps, job.job_id)).status == "done"
    assert await _visible_chunks(ingest_deps, job.version_id) == visible_before > 0


async def _visible_chunks(deps: IngestDeps, version_id: str) -> int:
    async with deps.pool.connection() as conn:
        row = await (
            await conn.execute("SELECT count(*) FROM chunks WHERE version_id = %s AND visible", (version_id,))
        ).fetchone()
    assert row is not None
    return int(row[0])


async def test_the_last_attempt_raises_a_final_failure(ingest_deps: IngestDeps) -> None:
    job = await _failed_job(ingest_deps, "AML-0028")
    async with ingest_deps.pool.connection() as conn:  # one attempt left, as after earlier failed tries
        await conn.execute(
            "UPDATE ingestion_jobs SET status = 'queued', attempts = %s WHERE id = %s",
            (MAX_ATTEMPTS - 1, job.job_id),
        )

    async def crash(_: str) -> None:
        raise RuntimeError("simulated crash after Postgres commit")

    ingest_deps.after_pg_activation = crash
    with pytest.raises(FinalIngestFailure):
        await ingest_document(ingest_deps, job.job_id)
    ingest_deps.after_pg_activation = None
    status, attempts, error, _, _ = await _state(ingest_deps, job.job_id)
    assert (status, attempts) == (
        "failed",
        MAX_ATTEMPTS,
    ) and error == "RuntimeError"  # the type, never the message
