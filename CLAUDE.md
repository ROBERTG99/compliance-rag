# compliance-rag — guide for Claude Code

Compliance assistant for the fictional tenant "Northwind Payments": answers policy questions with
verified, version-valid citations, per-document ACL and hybrid retrieval (OpenSearch BM25 +
pgvector/Qdrant, RRF, reranking). The model only composes answers; ACL, validity, retrieval,
fusion, reranking, citation verification and abstention are deterministic code.

Architecture: `docs/architecture.md`. Decisions: `docs/DECISIONS.md` and ADRs in `docs/adr/`.
Known gaps: `docs/KNOWN_LIMITATIONS.md`.

## Map

```text
src/compliance_rag/
  api/        FastAPI app, routes (ask, documents, admin, feedback, evals), SSE, limits, errors
  auth/       OIDC JWT validation, Principal mapping (roles -> groups)
  graph/      LangGraph RAG graph: nodes, state, citation verifier, claim streaming
  retrieval/  BM25 (OpenSearch), vector stores (pgvector, Qdrant), filters, hybrid + RRF
  rerank/     FeatureReranker (logistic), Cohere on Bedrock, optional cross-encoder
  embed/      LocalLSAEmbedder (offline default), Titan, OpenAI adapters
  ingest/     LangChain loaders, structure-aware chunker, pipeline, object store
  guard/      context guard (injection), output guard (canaries/URLs), PII redaction
  llm/        gateway (only provider-SDK importer), FakeLLM, cassettes, routing.yaml
  worker/     Arq worker: ingest_document, sync_acl, reindex_all, crons
  db/         SQLAlchemy engine, repositories, audit hash chain
  obs/        OpenTelemetry, structlog, Prometheus metrics, step records
  evals/      evalgate targets, metrics and graders for this system
  cli.py      `crag` CLI
apps/dev-oidc/   dev OIDC issuer with 4 personas
web/             React + Vite SPA
prompts/         versioned prompts (`<name>.v<N>.md`)
data/generator/  seeded synthetic corpus generator (seed 2026)
evals/           datasets/ suites/ rubrics/ redteam/ reports/ REPORT.md
migrations/      Alembic
deploy/          grafana/ prometheus/ otel/ opensearch/
docker/          Dockerfiles
scripts/         bench, fit_reranker, time_up, demo, seed, evals
third_party/     vendored evalgate subset
tests/           unit/ integration/ contract/ e2e/ harness/ perf/
```

## Make targets

| Target | Purpose |
|---|---|
| `make bootstrap` | uv sync, pnpm install, `.env`, tools |
| `make up` / `make down` | compose stack with healthchecks (+ seed) |
| `make check-fast` | ruff + mypy + unit/harness tests (< 60 s) |
| `make test` | unit + integration + contract (+ coverage gates) |
| `make test-docker` | every suite inside `compose.test.yaml` |
| `make e2e` | Playwright + axe against the stack |
| `make eval` / `make eval-ablation` / `make redteam` | offline evals, ablation, red-team |
| `make bench` | performance budgets |
| `make lint` / `make typecheck` / `make security` | check groups |
| `make verify` / `make verify-clean` | the single gate / in a fresh clone |
| `make corpus` / `make seed` / `make fit-reranker` / `make reindex` | data and models |

## Conventions

- Provider SDK imports (`anthropic`, `openai`, Bedrock runtime) live only in `src/compliance_rag/llm/gateway.py` (import-linter contract).
- ACL inside every query: every retrieval function takes a `Principal`; no unfiltered search exists. A counted post-check backs it up.
- Unauthorized resources return 404 (no existence leakage); abstentions for restricted and unknown topics are byte-identical (minus `run_id`, timings).
- Only verified claims stream to clients.
- Settings via `compliance_rag.settings.Settings` (`CRAG_` prefix); `.env.example` documents every variable.
- Conventional Commits; small verified increments.

## Testing rules

- Test first; the test must fail before the change.
- Offline always: no API keys; FakeLLM, LSA embedder and cassettes. The socket guard blocks public network.
- Never skip, xfail or weaken a test or threshold; record gaps in `docs/KNOWN_LIMITATIONS.md`.
- Integration tests use testcontainers (or `CRAG_TEST_*` URLs in Docker).

## Commit attribution

Do not add Co-Authored-By, Claude-Session or "Generated with Claude Code" trailers to commits or
pull requests. Never modify `git config user.*` or the `GIT_AUTHOR_*` / `GIT_COMMITTER_*` variables.

## Never do

- `terraform apply|destroy`, cloud deploys, creating/publishing/changing visibility of GitHub repos.
- Send messages to real recipients; commit secrets or real personal data (synthetic data only).
- Force-push; rewrite pushed history.
- Edit existing `evals/datasets/*.jsonl` files (add a new `.vN` file instead) or tune on the test split.
- Post-filter-only ACL, or any search path without the principal's filter in the query.
- Invent metrics: every number in docs comes from a command or report.
- Register a hook in `.claude/settings.json` before its script exists (a missing PreToolUse script blocks every tool call).

## Harness

- Subagents in `.claude/agents/` (`reviewer` before merging a change, `acl-auditor`, `retrieval-reviewer`, ...).
- Skills in `.claude/skills/` (`tdd`, `quality-gate`, `debug-retrieval`, ...). Hooks in `.claude/hooks/`.
- Path-scoped rules in `.claude/rules/`.
