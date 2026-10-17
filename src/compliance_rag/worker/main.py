"""Arq worker: ingest_document, sync_acl, reindex_all; crons poll_s3_inbox, refresh_lag_metric, purge_expired."""

from __future__ import annotations

from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings
from arq.worker import Retry

from compliance_rag.ingest import pipeline
from compliance_rag.obs.logging import configure_logging
from compliance_rag.obs.tracing import instrument_libraries, setup_tracing, traced_job
from compliance_rag.runtime import Services, build_services
from compliance_rag.settings import get_settings

WORKER_METRICS_PORT = 8611


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(settings.log_level, service="worker")
    setup_tracing("worker", settings.otel_exporter_otlp_endpoint)
    instrument_libraries()
    services = await build_services(settings)
    await services.objects.ensure_bucket()
    ctx["services"] = services
    try:
        from prometheus_client import start_http_server

        start_http_server(WORKER_METRICS_PORT)
    except OSError:  # port already bound (tests, second worker)
        pass


async def shutdown(ctx: dict[str, Any]) -> None:
    services: Services | None = ctx.get("services")
    if services is not None:
        await services.close()


@traced_job
async def ingest_document(ctx: dict[str, Any], job_id: str) -> dict[str, Any]:
    services: Services = ctx["services"]
    if not getattr(services.embedder, "fitted", True):
        await services.reload_embedder()
    try:
        result = await pipeline.ingest_document(services.ingest_deps(), job_id)
    except pipeline.EmbedderNotReady:
        raise
    except Exception as exc:
        tries = int(ctx.get("job_try", 1))
        if tries < pipeline.MAX_ATTEMPTS:
            raise Retry(defer=2**tries) from exc
        raise
    return {
        "job_id": result.job_id,
        "status": result.status,
        "chunks": result.chunk_count,
        "seconds": result.seconds,
    }


@traced_job
async def reindex_all(ctx: dict[str, Any], reembed: bool = False) -> dict[str, Any]:
    """Rewrite OpenSearch (and Qdrant when configured) from Postgres; ``reembed`` recomputes embeddings."""
    from compliance_rag.ingest.reindex import reindex

    services: Services = ctx["services"]
    report = await reindex(services.ingest_deps(), reembed=reembed, log=lambda _m: None)
    if reembed:
        await services.reload_embedder()
    return {"chunks": report.chunks, "qdrant": report.qdrant, "seconds": round(report.seconds, 1)}


@traced_job
async def purge_expired(ctx: dict[str, Any]) -> dict[str, int]:
    """Cron (daily, 03:10 UTC): retention for answers, feedback and finished jobs (BUILD.md §5)."""
    from compliance_rag.worker.retention import purge_expired as purge

    services: Services = ctx["services"]
    report = await purge(services.pool)
    return {"answers": report.answers, "feedback": report.feedback, "jobs": report.jobs}


@traced_job
async def poll_s3_inbox(ctx: dict[str, Any]) -> dict[str, int]:
    """Cron (every 30 s): register ``inbox/`` documents that have a sidecar ``.json`` and enqueue them."""
    from compliance_rag.ingest.pipeline import content_sha256, idempotency_key
    from compliance_rag.ingest.s3 import poll_inbox

    services: Services = ctx["services"]
    redis = ctx["redis"]

    async def enqueue_job(job: Any) -> None:
        async with services.pool.connection() as conn:
            row = await (
                await conn.execute(
                    "SELECT content_sha256 FROM document_versions WHERE id = %s", (job.version_id,)
                )
            ).fetchone()
        sha = str(row[0]) if row else content_sha256(job.job_id.encode())
        await redis.enqueue_job(
            "ingest_document",
            job.job_id,
            _job_id=idempotency_key("ingest", job.document_id, job.version, sha),
        )

    result = await poll_inbox(services.ingest_deps(), enqueue=enqueue_job)
    return {"registered": result.registered, "failed": result.failed, "waiting": result.waiting}


@traced_job
async def sync_acl(ctx: dict[str, Any], job_id: str) -> bool:
    from compliance_rag.worker.acl import sync_acl as do_sync

    services: Services = ctx["services"]
    if not await do_sync(services.ingest_deps(), job_id):
        tries = int(ctx.get("job_try", 1))
        if tries < pipeline.MAX_ATTEMPTS:
            raise Retry(defer=2**tries)
        return False
    return True


@traced_job
async def reconcile_acl(ctx: dict[str, Any]) -> int:
    """Cron (every minute): finish ACL syncs whose enqueue was lost or whose retries ran out."""
    from compliance_rag.worker.acl import reconcile_acl_sync

    services: Services = ctx["services"]
    return await reconcile_acl_sync(services.ingest_deps())


@traced_job
async def refresh_lag_metric(ctx: dict[str, Any]) -> dict[str, float | int]:
    """Cron (every 15 s): export ingestion lag to Prometheus."""
    from compliance_rag.obs.metrics import INGESTION_LAG
    from compliance_rag.worker.acl import index_lag

    services: Services = ctx["services"]
    lag = await index_lag(services.ingest_deps())
    INGESTION_LAG.labels(stat="p95").set(float(lag["p95_s"]))
    INGESTION_LAG.labels(stat="oldest_pending").set(float(lag["oldest_pending_s"]))
    return lag


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


class WorkerSettings:
    functions: ClassVar[list[Any]] = [ingest_document, sync_acl, reindex_all]
    cron_jobs: ClassVar[list[Any]] = [
        cron(poll_s3_inbox, second={0, 30}, run_at_startup=False, unique=True),
        cron(refresh_lag_metric, second={0, 15, 30, 45}, run_at_startup=True, unique=True),
        cron(reconcile_acl, second={20}, run_at_startup=True, unique=True),
        cron(purge_expired, hour={3}, minute={10}, second={0}, run_at_startup=False, unique=True),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = redis_settings()
    max_tries = pipeline.MAX_ATTEMPTS
    job_timeout = 600
    keep_result = 3600
    health_check_interval = 10


__all__ = ["WorkerSettings", "cron", "ingest_document"]
