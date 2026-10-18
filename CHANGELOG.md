# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project uses [Semantic Versioning](https://semver.org/). Task numbers (T-xx) refer to
[docs/specs/000-build-spec.md](docs/specs/000-build-spec.md); evidence per task is in [PROGRESS.md](PROGRESS.md).

## [0.1.0] - 2026-10-18

First complete version, verified on a fresh clone with no API keys ([docs/verification.md](docs/verification.md)).

### Added

- **Harness and tooling** (M0): `CLAUDE.md`, path-scoped rules, subagents, skills and hooks; uv workspace,
  Makefile, socket-guarded pytest; walking skeleton of API, web and compose stack with healthchecks.
- **Data** (M1): seeded synthetic corpus for "Northwind Payments" (policies with versions rendered as
  Markdown, HTML, DOCX and PDF, including canary injection documents); 300 evaluation questions and 80 judge
  labels built from it; core schema and a hash-chained, append-only audit log.
- **AI core** (M2): guarded loaders and article-aware chunker; offline LSA embedder with Titan and OpenAI
  adapters; pgvector and Qdrant stores and an OpenSearch BM25 leg, each with the ACL and validity filter
  inside the query; concurrent hybrid retrieval with RRF fusion and a counted post-check; feature reranker
  fitted on the dev split; context and output guards and PII redaction; LLM gateway with routing,
  cassettes and FakeLLM; citation verifier; LangGraph graph with abstention, follow-ups and verified claim
  streaming; versioned ingestion pipeline and Arq worker; dev OIDC issuer with four personas.
- **API** (M3): authenticated ask with SSE resume, documents (upload, S3 import and inbox, library,
  timeline, evidence), ACL changes with index sync, ingestion jobs and lag, feedback and triage, per-user
  rate limit, body limits, RFC 9457 errors and an OpenAPI contract tested with Schemathesis.
- **Web** (M4): React + Vite SPA in a regulatory-gazette design: Ask, Evidence, Library and Document,
  Ingestion jobs, Evaluation, Feedback triage; PKCE sign-in; Playwright journeys with axe checks,
  screenshots and a demo video.
- **Evaluations** (M5): vendored evalgate subset; `make eval` with thresholds and baseline gating,
  `make eval-ablation` over five retrieval configurations, `make redteam` with Promptfoo, `make eval-live`
  with a cost budget; `crag reindex` from Postgres.
- **Observability and security** (M6): OpenTelemetry tracing, JSON logs with correlation and run ids and
  text redaction, Prometheus metrics with alert rules and promtool tests, Grafana dashboard, optional
  Jaeger and Langfuse; daily retention purge; `make bench` against performance budgets; threat model and
  OWASP LLM mapping; `make security` (gitleaks, bandit, pip-audit, pnpm audit, hadolint, actionlint,
  licences, trivy) with pinned, rebuilt images free of high and critical findings.
- **Docker and CI** (M7): `make test-docker` runs every suite inside `compose.test.yaml`; GitHub workflows
  for CI, end-to-end tests, evals, image builds with a vulnerability scan, CodeQL and releases; coverage
  gates; `make verify-clean` in a fresh clone.
- **Docs** (M8): README, architecture, evaluation, runbook, security, design FAQ, ADRs 0001–0009,
  AI-development notes, contributing guide and security policy; `crag jobs replay-failed`.

### Fixed

Findings from the milestone reviews, each with a regression test; see the `fix(...)` commits and
[docs/DECISIONS.md](docs/DECISIONS.md). Highlights: Postgres re-check of index hits and ACL changes audited in
their transaction (M3); cached data cleared on every identity change in the web app (M4); budget refusal of
unpriced models and gating of answered injections (M5); purge of graph checkpoints with expired conversations
and aggregated metrics across API workers (M6); exception text kept out of logs and job rows, 503 when object
storage or the identity provider is down, quotes under the output guard, serialised JWKS fetches and checkpointer
migrations, tracebacks logged as text rendered from the exception itself, a worker healthcheck that no longer imports the worker, version ids derived from content so retrieval breaks score ties the same way on every seed, and NFR-2
tail latency (reduced;
still at its budget, see [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md)) (final review and verification, M9).
