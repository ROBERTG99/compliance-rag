"""Arq worker: ingest_document, sync_acl, reindex_all; crons poll_s3_inbox, refresh_lag_metric, purge_expired."""

from __future__ import annotations

from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings
from arq.worker import Retry

from compliance_rag.ingest import pipeline
from compliance_rag.runtime import Services, build_services
from compliance_rag.settings import get_settings

WORKER_METRICS_PORT = 8611


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
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


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


class WorkerSettings:
    functions: ClassVar[list[Any]] = [ingest_document]
    cron_jobs: ClassVar[list[Any]] = []
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = redis_settings()
    max_tries = pipeline.MAX_ATTEMPTS
    job_timeout = 600
    keep_result = 3600
    health_check_interval = 10


__all__ = ["WorkerSettings", "cron", "ingest_document"]
