# Runbook

Operating the local stack: start-up, health, reindexing, key rotation, job replay, retention and the alerts.
Everything here is local (Docker Compose); there is no cloud deployment.

## Start, stop, health

```bash
make up                 # build if needed, start with healthchecks, migrate and seed; prints the time taken
make down               # stop (volumes kept); `make clean` also removes volumes and caches
curl localhost:8610/readyz   # 200 when Postgres, Redis, OpenSearch and the embedder are ready
docker compose ps       # every long-running service should be "healthy"
```

The API warms its caches before reporting ready (Postgres `pg_prewarm`, one search per role, the reranker's
per-chunk caches); a cold API would answer its first questions with `retrieval_unavailable`. The API runs
`API_WORKERS` uvicorn processes (default 3); `/metrics` aggregates all of them.

Profiles: `qdrant` (vector store alternative and ablation), `observability` (start with
`OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318` to export traces; Grafana on 8690, Prometheus 8691,
Jaeger 8692), `langfuse` (8693; set `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` to the profile's dev project keys
from `compose.yaml`; the containers use `http://langfuse:3000`), `live` (a second API on 8614 with `DEMO_MODE=live`; needs a provider key).

## Reindexing

```bash
make reindex
```

Recomputes the embeddings (refitting the offline LSA embedder on the current corpus), drops and rebuilds the
OpenSearch index (and Qdrant when it is running) from Postgres, then restarts the API and worker so they load
the newly registered embedder. Searches fail while the indexes are being rebuilt. Postgres is the source of
truth: `crag reindex` without `--reembed` only rewrites the indexes, and `--recreate` also removes entries
whose chunk no longer exists.

## Key rotation

- **Dev OIDC signing key**: generated at dev-oidc start-up; restarting `dev-oidc` rotates it. The API fetches
  the JWKS again for an unknown `kid`, so existing sessions simply sign in again.
- **Provider keys** (`ANTHROPIC_API_KEY`, Bedrock credentials): environment only, never in files under
  version control or in logs. Rotate at the provider, update the environment, restart `api`, `worker` (and
  `api-live`).
- **MinIO and database passwords** are local dev values in `compose.yaml`; for any shared environment they
  must come from the environment instead.

## Ingestion jobs

The Ingestion jobs screen (admin) and `GET /v1/ingestion-jobs` list jobs with status, attempts and errors;
`GET /v1/index/lag` shows the pending count and lag. A job retries with backoff up to its attempt limit.

```bash
make replay-failed-jobs   # re-queue every failed ingestion job (idempotent steps, safe to repeat)
```

ACL changes are applied to Postgres at once (with their audit row); index updates that failed stay pending
and the worker's `reconcile_acl` cron retries them every minute. Until then the API's Postgres re-check keeps
revoked documents out of answers.

## Retention

The worker's `purge_expired` cron (daily, 03:10 UTC) deletes answers older than 90 days (unless they still
carry feedback), feedback older than 365 days, finished jobs older than 30 days, and the graph checkpoints of
conversations with no answer left. The audit log is never purged; each purge appends one audit row. Verify
the audit chain with `docker compose exec api crag audit verify`.

## Alerts

Rules in `deploy/prometheus/alerts.yml` (tested by `promtool test rules` in `make lint`).

### Retrieval is slow

`CragRetrievalSlow`: retrieval p95 (legs + fusion + rerank) above 300 ms over an hour. Check the per-leg
panel in Grafana: OpenSearch heap and disk (`curl localhost:8640/_cluster/health`), Postgres load, and
whether the API restarted recently (cold caches). The degraded-leg log event `retrieval_leg_failed` names the
leg.

### Ingestion lag

`CragIngestionLag`: the p95 of finished jobs, or the oldest pending job, is above 5 minutes. Look at the jobs
screen for failures, the worker logs, and Redis (the queue).

### Worker down

`CragWorkerDown`: Prometheus cannot scrape the worker. `docker compose ps worker`, then `docker compose logs
worker`; ingestion, ACL sync and retention are stalled until it is back.

### ACL violation

`CragAclViolation` pages: a retrieval backend returned a hit outside the principal's groups. The post-check
dropped it, so nothing leaked, but a filter is wrong or an index copy is stale. Compare the document's ACL in
Postgres with OpenSearch/Qdrant, run `make reindex`, and investigate the filter code path before closing.

### Citation rejects

`CragCitationRejects`: more than 20% of generated claims failed verification over an hour. Usually a model or
prompt change; check `crag_claims_rejected_total` by reason and the recent prompt versions.
