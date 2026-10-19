"""Arq worker runs ingest jobs enqueued with the idempotency key as job id (T-19)."""

from __future__ import annotations

from datetime import date

import pytest
from arq import create_pool as arq_pool
from arq.connections import RedisSettings
from arq.worker import Worker

from compliance_rag.embed.registry import load_embedder, save_embedder
from compliance_rag.ingest.pipeline import (
    DocumentMeta,
    IngestDeps,
    content_sha256,
    idempotency_key,
    register_upload,
)
from compliance_rag.runtime import Services
from compliance_rag.settings import Settings
from compliance_rag.worker import main as worker_main
from data.generator.corpus import SEED, build_corpus
from data.generator.render import render_version

pytestmark = pytest.mark.integration


async def test_worker_ingests_enqueued_job(ingest_deps: IngestDeps, redis_url: str) -> None:
    policy = next(p for p in build_corpus(SEED) if p.document_id == "AML-0107")
    v = policy.versions[2]
    blob = render_version(policy, v)
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
    job = await register_upload(ingest_deps, meta, blob, "admin@northwind.test")
    redis = await arq_pool(RedisSettings.from_dsn(redis_url))
    key = idempotency_key("ingest", meta.document_id, meta.version, content_sha256(blob))
    first = await redis.enqueue_job("ingest_document", job.job_id, _job_id=key)
    duplicate = await redis.enqueue_job("ingest_document", job.job_id, _job_id=key)
    assert first is not None and duplicate is None  # same idempotency key → no second job

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
        max_jobs=2,
    )
    await worker.main()
    await worker.close()
    async with ingest_deps.pool.connection() as conn:
        row = await (
            await conn.execute("SELECT status, chunk_count FROM ingestion_jobs WHERE id = %s", (job.job_id,))
        ).fetchone()
    assert row is not None and row[0] == "done" and row[1] > 0
    await redis.aclose()


async def test_embedder_registry_round_trip_and_mismatch(ingest_deps: IngestDeps) -> None:
    from compliance_rag.embed.base import EmbedderMismatch

    meta = await save_embedder(ingest_deps.pool, ingest_deps.objects, ingest_deps.embedder)
    settings = Settings(_env_file=None)
    loaded = await load_embedder(settings, ingest_deps.pool, ingest_deps.objects)
    assert loaded.fingerprint() == meta["fingerprint"]
    with pytest.raises(EmbedderMismatch):
        await load_embedder(
            Settings(_env_file=None, embedder="titan", embed_dim=512), ingest_deps.pool, ingest_deps.objects
        )
