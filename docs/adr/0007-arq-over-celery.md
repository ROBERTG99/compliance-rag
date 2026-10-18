# 0007. Arq over Celery for background jobs

## Status

Accepted

## Date

2026-10-16

## Context

Ingestion (parse, chunk, embed, index, activate), ACL synchronisation, re-indexing and a few periodic
jobs must run outside the request path. The rest of the code base is asyncio end to end: psycopg async
pools, httpx clients for OpenSearch and Qdrant, async object-store and Redis clients
(`.claude/rules/python.md`). Redis is already required for run event streams and the ask rate limiter
(`src/compliance_rag/api/sse.py:1-6`), so a broker adds no new service.

## Decision

Background work runs on Arq with Redis as the broker. `WorkerSettings` in
`src/compliance_rag/worker/main.py:149-165` registers the job functions `ingest_document`, `sync_acl`
and `reindex_all` and four crons, all `unique=True`: `poll_s3_inbox` (every 30 s), `refresh_lag_metric`
(every 15 s), `reconcile_acl` (every minute) and `purge_expired` (daily, 03:10 UTC). Jobs are coroutines
that reuse the same `Services` container as the API (`worker/main.py:20-27`). Failed jobs are
retried with exponential backoff (`Retry`) until the job's attempts in Postgres reach `MAX_ATTEMPTS`; the last
attempt raises `FinalIngestFailure`, which is not retried (`worker/main.py:49-52`, `ingest/pipeline.py:514`). Idempotency comes from the upload
key `sha256(kind|document_id|version|content_sha256)`, which is also the Arq `_job_id`
(`worker/main.py:100-104`, `docs/specs/000-build-spec.md` §4 on idempotency); activation is replay-safe.
The worker runs from the API image with its own metrics port, 8611 (`worker/main.py:17`).

## Alternatives considered

- **Celery.** Rejected: its task model is synchronous-first, so each task would need an event-loop
  bridge to use the async pools and clients, and a second, separate set of connection handling. It is a
  larger system (canvas, multiple brokers and result backends) than three jobs and four crons need.
  The spec lists Celery as the alternative rejected (§5 tech stack table).
- **FastAPI `BackgroundTasks`.** Rejected: tasks die with the API process, have no retry and no schedule,
  and uploads of up to 20 MB should survive a restart.
- **A Postgres job table polled by the API.** Rejected: the `ingestion_jobs` table already records
  status, but polling, locking and cron scheduling would have to be written by hand. Postgres remains the
  record of what has been done; Redis only carries the work.

## Consequences

Positive:

- Small and native to asyncio: a job function is an `async def` over the same repositories and stores as
  the API, with traced spans via `@traced_job` (`worker/main.py:42`).
- Crons are declared next to the jobs and de-duplicated across workers by `unique=True`.
- Covered end to end by `tests/integration/test_worker.py::test_worker_ingests_enqueued_job` and the
  ingestion race tests in `tests/integration/test_ingest_races.py`.

Negative:

- Redis is a single point for job delivery. The repo does not rely on Redis for truth: job rows live in
  Postgres, uploads are idempotent, a lost ACL enqueue is finished by the `reconcile_acl` cron
  (`worker/main.py:123-129`), and `purge_expired` and `poll_s3_inbox` re-derive their work from the
  database and the bucket. Redis loss does degrade run event resume, which falls back to process memory
  (`sse.py:1-6`).
- Fewer features than Celery (no workflow primitives, a smaller ecosystem). None are used here.
- Arq job spans are not linked to the API trace that enqueued them, because the trace context is not
  passed through the job payload (`docs/KNOWN_LIMITATIONS.md`, Observability row).
- `job_timeout` is 600 s (`worker/main.py:163`): an ingestion that runs longer is stopped by Arq.
