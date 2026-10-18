"""NFR-3: one offline document is ingested in under 60 s, and the ingestion lag p95 stays under 5 minutes."""

from __future__ import annotations

import time
from datetime import date

import pytest

from compliance_rag.ingest.pipeline import DocumentMeta, IngestDeps, ingest_document, register_upload
from data.generator.corpus import SEED, build_corpus
from data.generator.render import render_version

pytestmark = [pytest.mark.integration, pytest.mark.perf]


@pytest.mark.parametrize("fmt", ["md", "pdf", "docx", "html"])
async def test_one_document_under_60s(ingest_deps: IngestDeps, fmt: str) -> None:
    policy = max((p for p in build_corpus(SEED) if p.product), key=lambda p: len(p.current.articles))
    v = policy.current
    meta = DocumentMeta(
        policy.document_id,
        v.version,
        policy.title,
        policy.domain,
        policy.owner,
        date.fromisoformat(v.valid_from),
        fmt,
        policy.acl_groups,
    )
    started = time.perf_counter()
    job = await register_upload(ingest_deps, meta, render_version(policy, v, fmt), "admin")
    result = await ingest_document(ingest_deps, job.job_id)
    elapsed = time.perf_counter() - started
    assert result.status == "done" and result.chunk_count >= len(v.articles)
    assert elapsed < 60, f"{fmt}: {elapsed:.1f}s"


BURST = 24  # documents uploaded at once, as after a bulk import


async def test_ingestion_lag_p95_for_a_burst_through_the_worker(
    ingest_deps: IngestDeps, redis_url: str
) -> None:
    # lag = finished_at - enqueued_at per job, through Redis and the real Arq worker with its default concurrency
    from arq import create_pool as arq_pool
    from arq.connections import RedisSettings
    from arq.worker import Worker

    from compliance_rag.ingest.pipeline import content_sha256, idempotency_key
    from compliance_rag.runtime import Services
    from compliance_rag.settings import Settings
    from compliance_rag.worker import main as worker_main
    from tests.perf.budget import assert_budget

    redis = await arq_pool(RedisSettings.from_dsn(redis_url))
    job_ids = []
    for policy in build_corpus(SEED)[:BURST]:
        v = policy.current
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
        blob = render_version(policy, v)
        job = await register_upload(ingest_deps, meta, blob, "admin")
        key = idempotency_key("ingest", meta.document_id, meta.version, content_sha256(blob))
        await redis.enqueue_job("ingest_document", job.job_id, _job_id=key)
        job_ids.append(job.job_id)
    services = Services(
        settings=Settings(_env_file=None),
        pool=ingest_deps.pool,
        objects=ingest_deps.objects,
        bm25=ingest_deps.bm25,
        pg=ingest_deps.pg,
        embedder=ingest_deps.embedder,
    )
    worker = Worker(
        functions=[worker_main.ingest_document],
        redis_pool=redis,
        burst=True,
        poll_delay=0.1,
        ctx={"services": services},
        handle_signals=False,
    )
    await worker.main()
    await worker.close()
    await redis.aclose()
    async with ingest_deps.pool.connection() as conn:
        rows = await (
            await conn.execute(
                "SELECT status, extract(epoch FROM finished_at - enqueued_at) * 1000 FROM ingestion_jobs "
                "WHERE id = ANY(%s::uuid[])",
                (job_ids,),
            )
        ).fetchall()
    assert len(rows) == BURST and all(r[0] == "done" for r in rows), rows
    assert_budget(
        "NFR-3 ingestion lag",
        [float(r[1]) for r in rows],
        5 * 60 * 1000,
        key="nfr3_ingestion_lag",  # gitleaks:allow (a bench.json section name)
        documents=BURST,
        path="register_upload, Redis, Arq worker (default concurrency), testcontainers",
    )
