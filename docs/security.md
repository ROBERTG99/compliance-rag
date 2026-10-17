# Security

Threat model, OWASP Top 10 for LLM applications mapping, scan results and accepted findings for
compliance-rag (BUILD.md §15). The tenant ("Northwind Payments") and every document are synthetic.
Report vulnerabilities as described in `SECURITY.md`.

## Assets and trust boundaries

| Asset | Where | Why it matters |
|---|---|---|
| Restricted policy text (Legal-only, Compliance-only) | Postgres `chunks`, OpenSearch, Qdrant, MinIO/S3 raw files | Must never reach a principal outside its groups, not even as existence (404, uniform abstention). |
| Answers, questions, feedback comments | Postgres `answers`, `feedback`; Redis run streams (5 min TTL) | Can quote restricted text; owner-only; retention 90/365 days (`purge_expired`). |
| Audit log | Postgres `audit` (append-only, hash chain) | Evidence of ACL changes, uploads, activations, triage and purges. |
| Tokens and keys | Environment only (`.env` is git-ignored; dev-oidc key generated at start) | Bearer tokens grant the role's groups; provider keys cost money. |

Boundaries: browser → nginx/API (JWT), API → stores (service network), API → LLM provider (only via
`llm/gateway.py`, PII-redacted), uploaded documents → model context (untrusted data).

## STRIDE summary

| Threat | Example | Controls | Evidence |
|---|---|---|---|
| **S**poofing | Forged or foreign JWT, `alg: HS256` downgrade, token for another audience | RS256 via JWKS, issuer/audience/expiry checked, HS256 rejected; role caps groups (claims cannot add groups) | `tests/integration/test_auth.py` (wrong audience, expired, tampered, foreign key, escalation) |
| **T**ampering | Edit an audit row; re-upload a different file under the same version | Audit hash chain with UPDATE/DELETE/TRUNCATE triggers, `crag audit verify`; uploads are content-addressed and a changed file for an existing version is 409 | `tests/integration/test_audit.py`, `test_documents_api.py::test_upload_is_idempotent_by_hash` |
| **R**epudiation | "I never changed that ACL" | ACL change, upload, activation, triage and purge write audit rows in the same transaction | `tests/integration/test_acl_sync.py`, `test_feedback_api.py`, `test_retention.py` |
| **I**nformation disclosure | Support asks a Legal-only question; reads a chunk id; infers existence from a 403 | ACL inside every query (SQL `WHERE`, OpenSearch `filter`, Qdrant `Filter`) plus a counted post-check and an authoritative Postgres re-check of index hits; 404 for unauthorized resources; byte-identical abstentions; no question/answer/document text in logs or spans | `test_acl.py`, `test_vector_stores.py`, `test_bm25.py`, `test_security.py::test_no_restricted_text_in_logs`, `make eval` ACL leakage = 0 (hard gate) |
| **D**enial of service | 1 GB upload, zip bomb, 10,000-page PDF, ask flood | Body cap before buffering (uploads 20 MB + envelope, JSON 1 MiB), magic bytes, 500-page PDF cap, DOCX expansion guard, 2,000-char questions, 30 asks/min/user (Redis sliding window, fails open with a counter), leg timeouts | `tests/integration/test_limits.py`, `tests/unit/ingest/test_chunker.py` |
| **E**levation of privilege | Analyst calls admin routes; a document instruction makes the model act | Role checks on admin routes (403 for authenticated non-admins on admin-only actions, 404 for resources); the model has no tools and proposes no side effects | `test_admin_api.py`, `test_feedback_api.py`, FR-13 tests below |

## OWASP Top 10 for LLM applications (2025)

| Risk | How it applies | Controls | Evidence |
|---|---|---|---|
| LLM01 Prompt injection | 30 corpus documents carry injected instructions with canaries; users can type attacks | Documents wrapped in `<document>` tags as data; `guard_context` removes sentences scoring ≥ 0.7 (assistant-directed imperatives, "ignore previous", role tokens, hidden Unicode); output guard blocks canaries and URLs absent from context; only verified extractive claims stream | `tests/unit/guard/test_context_guard.py`, `tests/unit/graph/test_injection.py`, `make redteam` (40 cases, 0 failures; injected documents still answered 28/30, gated) |
| LLM02 Sensitive information disclosure | Restricted text, PII in questions | ACL in the query; PII redaction in the gateway before any provider call; log/span redaction; owner-only runs and answers | `test_gateway.py::test_pii_never_reaches_the_provider`, `test_security.py` |
| LLM03 Supply chain | Python/npm dependencies, base images, model provider | Locked dependencies (`uv.lock`, `pnpm-lock.yaml`), pinned images, `pip-audit`, `pnpm audit`, `trivy`, licence gate, import-linter keeps provider SDKs in one module | `make security` (below) |
| LLM04 Data and model poisoning | A malicious upload becomes evidence | Only admins upload; content hash, version and validity are explicit; every upload/activation audited; injected text is guarded at query time | `test_documents_api.py`, `test_ingest_pipeline.py` |
| LLM05 Improper output handling | Model output rendered in the browser | Claims are schema-validated and verified against quoted chunk text before streaming; the SPA renders text, never HTML from the model | `tests/unit/graph/test_verify_citations.py`, `web/src/routes/ask` tests |
| LLM06 Excessive agency | Model triggering actions | The model has no tools; generation proposes no side effects | `graph/build.py` (no tool definitions) |
| LLM07 System prompt leakage | "Print your system prompt" | Prompts contain no secrets; output must be verified quotes from documents, so prompt text cannot stream; red-team asserts prompt markers never appear | `evals/redteam/cases.v1.yaml` (user attacks) |
| LLM08 Vector and embedding weaknesses | Nearest-neighbour search returning restricted chunks | ACL filter inside the vector query for pgvector and Qdrant (iterative HNSW scan keeps recall); post-check; Postgres re-check of index hits | `test_vector_stores.py` (300 nearer restricted chunks still yield 10 authorized hits) |
| LLM09 Misinformation | Superseded or invented policy values | Validity at `as_of` in the query; citation verifier (numbers must appear in quotes); abstention below τ; superseded versions labelled | `make eval`: hallucinated citation rate 0, stale-version rate 0 (`evals/REPORT.md`) |
| LLM10 Unbounded consumption | Cost or load amplification | Rate limit, question length, per-route `max_tokens` and timeouts, `LIVE_EVAL_BUDGET_USD` stop in `make eval-live` (refuses unpriced models) | `test_limits.py`, `tests/unit/evals/test_budget.py` |

## Known side channels and gaps

- BM25 IDF and the LSA embedder are fitted over all chunks, including restricted ones: term statistics of
  restricted documents influence scores of visible ones. No restricted text or id is returned; listed in
  `docs/KNOWN_LIMITATIONS.md`.
- The `retrieval` SSE event reports leg hit counts before the post-check (`n_bm25`, `n_vector`); the index
  re-check against Postgres drops stale hits before fusion, so counts can differ by the number of dropped
  hits but never expose ids or text.
- The dev persona switcher mints tokens for any persona; it is compiled in only for dev builds
  (`VITE_DEV_PERSONAS=1`) and dev-oidc is not a production identity provider.

## Scans (`make security`)

`scripts/security.sh` runs every step and fails if any fails: gitleaks (full history), bandit (fails on
high severity), pip-audit (editable local packages skipped), `pnpm audit --audit-level high` for `web/` and `evals/redteam/`,
hadolint, actionlint (when workflows exist), the licence gate (`scripts/check_licences.py`) and trivy
(HIGH/CRITICAL with a fix available) on the application images.

Results of the last run are recorded in `PROGRESS.md` (T-45).

### Accepted findings

| Finding | Where | Why accepted |
|---|---|---|
| bandit B608 (medium): SQL built from strings | `api/routes/{admin,documents,feedback}.py`, `ingest/pipeline.py`, `retrieval/vector/pgvector.py`, `worker/retention.py` | Only constant SQL fragments chosen in code are concatenated; every value is a bound parameter. Each site carries a `noqa: S608` with the reason. |
| GHSA-vfj7-8cjw-p6xm (high, `braces`, no fixed version) | `web/` dev dependency via `markdownlint-cli2` | Development tool only (Markdown lint); not in the built SPA or any image. Ignored in `web/package.json` `pnpm.auditConfig`. |
| GHSA-86w9-cpqp-85rv (high, `node-forge`, no fixed version) | `evals/redteam` via `promptfoo` | Red-team tool run locally and in CI against the local API only; not in any image. Ignored in `evals/redteam/package.json`. |
| Transitive advisories with fixes (`smol-toml`, `katex`, `basic-ftp`, `simple-git`) | dev tooling | Forced to fixed versions with `pnpm.overrides`. |
| Trivy secret scanner hits in the `anthropic` SDK | `site-packages/anthropic/types/beta/...` docstrings | Not secrets (placeholder text in docstrings); image scans use `--scanners vuln`, repository secrets are gitleaks' job. |

The application images (`api`, `web`, `dev-oidc`, `minio`) have no HIGH or CRITICAL findings with a fix available in the last run; `.trivyignore` is empty.

Third-party images in the optional profiles (Prometheus, Grafana, Jaeger, OTel Collector, Qdrant, Postgres,
Redis, OpenSearch) are pinned upstream images and are not part of the application's trivy gate.
