# PROGRESS

## Needs the maintainer

- Switch `third_party/evalgate/` to `evalgate @ git+https://github.com/ROBERTG99/evalgate@v0.1.0` once that tag is published (the repository currently has no tag).
- Maintainer review of 40 questions from `evals/datasets/questions.v1.jsonl` (labels are by construction).
- Provider fixtures for Titan/OpenAI embeddings and Cohere rerank are synthetic (documented response shapes); re-record with `make record-fixtures` when keys are available.

## Resume here (handoff, 2026-10-16)

**State:** M0, M1 and M2 tasks are done (T-01…T-26 except as marked below); M3 has started (T-26 done). Next task: **T-27 Ask and SSE**. Branch `feat/practical-planck-8e2t30`, everything committed and pushed.

### Milestone reviews

| Milestone | Reviewer verdict | Notes |
|---|---|---|
| M0 | "ship" (after fixes) | Guard rewritten per review (segment tokeniser, identity/force-push variants, dataset false positives). |
| M1 | "ship" | Follow-ups applied (audit TRUNCATE trigger, float hashing, `make corpus` exports datasets, env.example both directions). Deferred items in `docs/KNOWN_LIMITATIONS.md`. |
| M2 | "ship" (re-review after `e847e0f`, `6047fd5`, `8cb824a`) | All five reviewer blockers and ACL-audit items 1, 3, 5, 7 fixed and verified (35 M2 integration tests). |

### M2 blockers (all fixed; kept for the record)

1. **Verifier — partial-number quotes** (`src/compliance_rag/graph/verify.py`, `locate`): a quote ending inside a number ("…limit is EUR 1" vs chunk "EUR 1,000") passes with claim "…EUR 1." → reject matches whose span starts/ends inside a digit run (digits joined by `,`/`.`); add that regression test to `tests/unit/graph/test_verify_citations.py`.
2. **Streamed claims vs final answer** (`graph/build.py` generate/verify nodes): build the final verified answer from the per-claim results (skip invalid claims instead of failing the whole `GeneratedAnswer` validation, e.g. quote < 12 chars, > 8 claims). On `refusal`/`max_tokens` claims may already have streamed: either buffer claims until the stream ends or emit an explicit retraction; test it. Also: report schema-invalid claims as their own reason (not `quote_not_found`), count `crag_claims_rejected_total` once, and keep citation `n` numbering identical between streamed and final claims.
3. **Output guard on claims** (`graph/build.py`): run `guard.output_guard.check_output` on every claim text before emitting `claim` (emit `claim_rejected` otherwise) and re-check the rebuilt answer. Add a canary-in-claim test (FR-13).
4. **Blocking provider calls in async code**: `embed_query` in `retrieval/hybrid.py` vector leg, the synchronous `rerank` node (`graph/build.py`), `rerank/cohere.py`, `FeatureReranker._fill_cosine`. Wrap in `asyncio.to_thread` (LSA is CPU-bound too) and route Titan/OpenAI embedding and Cohere rerank calls through gateway methods that redact PII and record usage/cost.
5. **Citation offsets for BM25 hits**: OpenSearch docs lack `char_start/char_end`, and `rrf_fuse` keeps the BM25 copy, so offsets are chunk-relative. Add `char_start`/`char_end` to the OpenSearch mapping (`deploy/opensearch/crag-chunks-v1.json` + the packaged copy in `src/compliance_rag/retrieval/`, they must stay identical), index and return them, and add a fused-path test. Note: changing the strict mapping requires re-creating the dev index (`docker compose down -v` or delete `crag-chunks-v1`, then `uv run crag seed --force`).

### Open ACL-audit items (fold into T-27 / T-39)

- **Conversation ownership (T-27):** `/v1/ask` with `follow_up_of` must load the `answers` row and return 404 unless `user_sub` matches; reuse its `conversation_id` server-side only. Never return or serialise raw graph state (it holds per-leg hits); also store `principal.sub` in graph `history` entries and ignore entries from another sub.
- **Uniform abstention body (T-27):** set `cost_usd` to `null` (or omit) in abstention bodies; real cost stays in `answers.cost_usd`. Extend the parity test to an abstention after generation (`no_verified_claims`).
- **`as_of` cap (T-27):** reject `as_of` later than today with 422 for every role except `content_admin` (announced-but-not-in-force versions).
- **Leak metric (T-39):** compute ACL leakage against ground truth (the corpus model's `acl_groups` and version validity, not the store's copy), require `persona` on every row, and assert `HybridResult.violations == 0` per case.
- **Post-check gaps:** `AccessFilter.allows` cannot check `visible` (Candidates do not carry it); `n_bm25`/`n_vector` in the `retrieval` event are pre-post-check counts. Document in `docs/security.md` or add the field.
- **Side channel to document (T-45):** BM25 IDF and the LSA embedder are fitted over all chunks, including restricted ones, so abstention timing/scores can shift slightly → `docs/KNOWN_LIMITATIONS.md`.
- Non-blocking reviewer notes still to handle: context-guard sentence removal shifts offsets inside guarded chunks; NFKC per-char vs whole-string normalisation in `locate`; wrap non-retryable `anthropic` 4xx in an `LLMError` subclass; `chunk_text`/`embed_documents` should run in `to_thread` in the worker; a job failing during the OpenSearch/Qdrant sync on its last attempt should stay `activating` (or `make replay-failed-jobs` must repair it); worker docstring lists unregistered functions (`sync_acl`, `reindex_all`, crons — T-28/T-29) and `EmbedderNotReady` leaves a job in `embedding`.

### T-27 plan (not started; no code written yet)

- `src/compliance_rag/api/`: `app.py` lifespan builds `Services` (`runtime.build_services`), `Gateway`, `HybridRetriever`, reranker, `AsyncPostgresSaver` (pool with `autocommit=True, prepare_threshold=0, row_factory=dict_row`, `await saver.setup()`), the compiled graph, Redis, and `auth.jwt.TokenValidator(issuer=CRAG_OIDC_PUBLIC_ISSUER or CRAG_OIDC_ISSUER, audience, JWKSCache(CRAG_OIDC_ISSUER))`; refuse to start on `EmbedderMismatch`.
- `api/errors.py` (RFC 9457 problem+json: 401 AuthError, 404, 409 VersionConflict/AclConflict, 413, 415, 422, 429, 503 `retrieval_unavailable`/`generation_unavailable`), `api/deps.py` (`current_principal`, `require_role`), `api/sse.py` (Redis Stream `crag:run:{run_id}`, explicit IDs `0-{seq}`, TTL 300 s, `: ping` every 15 s, `Last-Event-ID` replay, in-memory fallback when Redis is down), `api/routes/ask.py` (`POST /v1/ask` sync 200 / stream 202 `{run_id, events_url}`, `GET /v1/runs/{id}/events`, `GET /v1/runs/{id}` owner-only else 404), persist `answers` + `audit` (`ask`, details without question text), `/v1/me`, `/readyz` (503 when Postgres is down).
- Tests to write first: `tests/integration/test_sse.py::test_resume_with_last_event_id`, `tests/integration/test_acl.py::test_abstention_does_not_reveal_restricted_documents` (support vs Legal-only `CMP-0215` vs unknown topic; chunk 404 part lands with T-28), and update `tests/integration/test_skeleton.py::test_ask_returns_fake_answer` to the real authenticated API (the skeleton route in `api/routes/ask.py` is still the hard-coded walking skeleton).
- Fixture idea: a session-scoped API environment (migrated DB, OpenSearch index, MinIO bucket, Redis) seeded with `seed_corpus(only={...})` (≈20 documents incl. `KYC-0042`, `CMP-0215`, `AML-0107`), tokens from the in-process dev-oidc app (`apps/dev-oidc/dev_oidc/app.py`, see `tests/integration/test_auth.py`).

### Environment notes for the next session (cloud container)

- Start Docker per Appendix A (the SessionStart hook does it): `mirror.gcr.io` registry mirror; MinIO image is built from source (`docker/minio.Dockerfile`), OpenSearch from the Docker Hub mirror, `public.ecr.aws`/ghcr.io blobs are blocked.
- Disk allowance is tight (~13 GB free after cleanup): prune unused images/caches with `docker image prune`, `go clean -modcache` if needed. OpenSearch disk watermarks are disabled in compose and tests.
- Tools: gitleaks, actionlint, hadolint, trivy in `~/.local/bin` (`scripts/install_tools.sh`).
- Dev stack: `docker compose up -d --wait` (postgres, redis, opensearch, minio, dev-oidc, api skeleton, web skeleton), then `uv run crag seed` (≈113 s: 400 documents, 1,199 versions, 22,717 chunks).
- Commit with `scripts/task_commit.sh "<message>"` (formats, runs `make check-fast`, refuses to commit on red).
- Dev-only evaluation helper used while tuning (not committed): run `answer_row` over dev rows with `compliance_rag.evals.metrics`; last dev numbers: recall@10 0.962, MRR@10 0.973, key-fact 0.939, abstention 0.972, ACL leak 0, retrieval p95 ≈ 95–105 ms (FakeLLM, `src/compliance_rag/rerank/feature_weights.json` from `make fit-reranker`). These are dev-split numbers for tuning, not reported results.

## Bootstrap evidence

- Environment: Claude Code on the web (`CLAUDE_CODE_REMOTE=true`).
- Identity variables: `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`, `GIT_COMMITTER_NAME`, `GIT_COMMITTER_EMAIL` all set (ROBERTG99 <54124633+ROBERTG99@users.noreply.github.com>). Git config was not touched.
- `.claude/settings.json` and `.claude/rules/git-commits.md` were not pre-seeded; created and committed alone. Output of `git log -1 --format='%an <%ae> | %cn <%ce>%n%B'`:

```text
ROBERTG99 <54124633+ROBERTG99@users.noreply.github.com> | ROBERTG99 <54124633+ROBERTG99@users.noreply.github.com>
chore: configure commit attribution
```

## Tasks

| ID | Milestone | Title | Status | Evidence |
|---|---|---|---|---|
| T-01 | M0 | Bootstrap and attribution evidence | done | `uv run pytest tests/harness/test_repo_files.py` → 1 passed |
| T-02 | M0 | Python workspace and Makefile | done | `make check-fast` → ruff, mypy, 4 harness tests passed; socket guard test passes |
| T-03 | M0 | Web scaffold | done | `pnpm -C web test` → 1 passed; `pnpm -C web build` → built |
| T-04 | M0 | CLAUDE.md, AGENTS.md, settings, rules | done | `uv run pytest tests/harness/test_settings.py` → 4 passed; CLAUDE.md 98 lines |
| T-05 | M0 | Hooks | done | `uv run pytest tests/harness` → 39 passed (guard staged in a temp file before swap) |
| T-06 | M0 | Subagents and skills | done | `uv run pytest tests/harness/test_agents.py` → 3 passed (8 agents, 13 skills) |
| T-07 | M0 | Repository integrations | done | `uv run pre-commit run --all-files` → ruff, ruff-format, prettier, gitleaks, markdownlint passed |
| T-08 | M0 | Walking skeleton in Docker (FR-8) | done | `docker compose up -d --wait --build` → 6 services healthy in 19 s; `curl -X POST localhost:8600/v1/ask` → FakeLLM answer; `pytest tests/integration/test_skeleton.py` → 1 passed |
| T-09 | M1 | Settings and `.env.example` | done | `uv run pytest tests/unit/test_settings.py` → 4 passed; mypy clean |
| T-10 | M1 | Core migrations (FR-3, FR-5) | done | `uv run pytest tests/integration/test_migrations.py` → 4 passed (testcontainers pgvector:pg16; upgrade + downgrade) |
| T-11 | M1 | Ops migrations and audit chain (FR-12) | done | `uv run pytest tests/integration/test_audit.py` → 3 passed (UPDATE/DELETE rejected, tamper detected at seq 3, `crag audit verify` ok, 10 concurrent appends keep the chain) |
| T-12 | M1 | Corpus generator (FR-1) | done | `uv run pytest tests/unit/data/test_generator.py` → 5 passed; `crag corpus generate --no-render` twice → 400 policies, 1,199 versions, identical manifest 6060632b25b54897 (before T-13 injections; the model fingerprint changes with T-13, see T-13 row) |
| T-13 | M1 | Renderers and injection documents (FR-1, FR-13) | done | `uv run pytest tests/unit/data` → 11 passed (4 formats parse back with facts, byte-stable, 30 unique canaries); `crag corpus generate` twice → manifest b982aaa7999afe26 both runs, 17 s |
| T-14 | M1 | Questions and judge labels | done | `uv run pytest tests/unit/data/test_questions.py` → 5 passed (300 rows: dev 180/test 120, §11 mix; 80 judge labels; committed files equal the generator output) |
| T-15 | M2 | Loaders and chunker (FR-2) | done | `uv run pytest tests/unit/ingest/test_chunker.py` → 8 passed (4 formats respect article boundaries, Hypothesis offset round-trip 60 examples, long-article split, magic bytes) |
| T-16 | M2 | Embedders (FR-4) | done | `uv run pytest tests/unit/embed tests/contract/providers` → 8 passed (LSA fit twice max diff < 1e-6, npz round-trip, Titan/OpenAI request+response shapes against fixtures) |
| T-17 | M2 | Vector stores (FR-5) | done | `uv run pytest tests/integration/test_vector_stores.py` → 6 passed (pgvector + Qdrant: 300 nearer restricted chunks still yield 10 authorized hits, validity/visibility, 25 random group draws never leak) |
| T-18 | M2 | OpenSearch BM25 (FR-6) | done | `uv run pytest tests/integration/test_bm25.py tests/unit/retrieval` → 5 passed (Legal-only chunk matching every term absent for support); `crag search init` twice → created, already present |
| T-19 | M2 | Ingestion worker (FR-3) | done | `uv run pytest tests/integration/test_ingest_pipeline.py tests/integration/test_worker.py tests/perf/test_ingest_latency.py` → 9 passed (v2 closed at 2026-03-01 in PG + OpenSearch; crash after PG commit repaired by replay; Arq dedupes by idempotency key; md/pdf/docx/html each < 60 s) |
| T-20 | M2 | Hybrid retrieval and RRF (FR-7) | done | `uv run pytest tests/unit/retrieval/test_hybrid.py` → 6 passed (BM25 timeout → degraded ["bm25"], both down → RetrievalUnavailable, RRF k=60 math, deterministic ties, post-check counted) |
| T-21 | M2 | Rerankers (FR-7) | done | `uv run pytest tests/unit/rerank` → 7 passed (dev-only fit, deterministic weights, Cohere recorded shape + fallback, cross-encoder fallback); `make fit-reranker` twice → identical weights (sha256 OK); dev: recall@10 0.962, MRR@10 0.973, key-fact 0.939, abstention 0.972, ACL leak 0 |
| T-22 | M2 | LLM gateway, FakeLLM, cassettes | done | `uv run pytest tests/unit/llm tests/harness/test_import_contract.py` → 8 passed (refusal → LLMRefusal, max_tokens → LLMMaxTokens, 400 surfaces, 529 → GenerationUnavailable, adaptive thinking + effort + json_schema + cached system, cassette precedence + mismatch); `lint-imports` → contract KEPT |
| T-23 | M2 | Guards and PII redaction (FR-13) | done | `uv run pytest tests/unit/guard` → 15 passed (8 injection templates ≥ 0.7, filler/fact sentences < 0.7, 30 corpus canaries removed, output guard, PII redaction); PII spy: `tests/unit/llm/test_gateway.py::test_pii_never_reaches_the_provider` passes |
| T-24 | M2 | Citation verifier (FR-9) | done | `uv run pytest tests/unit/graph/test_verify_citations.py` → 7 passed (fabricated quote → claim_rejected, chunk_not_in_context, numeric_mismatch + answer rewrite, offsets, NFKC; Hypothesis 80+80 examples: whitespace-changed substrings accepted, 1-char mutations rejected) |
| T-25 | M2 | Graph, abstention, follow-up (FR-8) | done | `uv run pytest tests/unit/graph/test_graph.py` → 8 passed (low score abstains with 0 LLM calls, only verified claims stream, follow-up via checkpointer, refusal, identical abstention bodies, claim stream parser); `uv run pytest tests/integration/test_graph_offline.py` → 10/10 dev questions answered offline with AsyncPostgresSaver, follow-up reloads history |
| T-26 | M3 | Dev OIDC and auth (FR-11) | done | `uv run pytest tests/integration/test_auth.py` → 6 passed (wrong audience, expired, forged payload, foreign key, HS256 rejected; role caps groups; PKCE S256 single-use codes); `docker compose up dev-oidc` healthy, `/dev/token` mints RS256 |
| T-27 | M3 | Ask and SSE (FR-10, FR-11) | done | `uv run pytest tests/integration/test_sse.py tests/integration/test_acl.py tests/integration/test_skeleton.py` → 9 passed (Last-Event-ID 4 replays 5..N, only verified text in tokens, as_of 2025-12-31 → KYC-0042 v2 superseded, owner-only runs, restricted vs unknown abstention identical minus run_id/conversation_id/latency, follow-up ownership, future as_of 422, 401 problem+json) |
| T-28 | M3 | Documents and S3 inbox (FR-1) | done | `uv run pytest tests/integration/test_documents_api.py` → 6 passed (same bytes → same job_id, raw in S3, 21 MB → 413, fake PDF/EXE → 415, bad id → 422, changed bytes/ACL → 409, analyst → 403, from-s3 + 404, library/versions/evidence ACL → 404, cursor paging, valid_at, inbox sidecar poll); full `tests/integration` → 50 passed |
| T-29 | M3 | ACL sync, jobs, lag (FR-14, FR-11) | done | `uv run pytest tests/integration/test_admin_api.py` → 2 passed (3 queued jobs → `pending` +3, jobs filter, analyst → 403; KYC-0042 ACL → compliance: support absent from BM25 and pgvector, ask abstains, document 404, audit `acl_change`, restored) |
| T-30 | M3 | Feedback and audit (FR-12) | done | `uv run pytest tests/integration/test_feedback_api.py tests/unit/evals` → 4 passed (201 then 200 same id, 422 bad reason, 404 unknown/foreign run, comment kept out of audit; triage 403 for non-admin, `split: test` and test-split questions → 422 `test_split_triage`, audit chain verifies) |
| T-31 | M3 | Limits and errors (NFR-6) | done | `uv run pytest tests/integration/test_limits.py` → 3 passed (30 × 200 then 429 problem+json with `Retry-After`, other user unaffected; dead Redis → asks pass and `crag_ratelimit_bypass_total` +3; 2,001-char and blank question → 422; 20 MB + 1 → 413, non-PDF magic bytes → 415). Also fixed: an all-OOV question embedded to the zero vector and pgvector returned NaN cosine (`405b7c0`). |
| T-32 | M3 | OpenAPI and contract tests | todo | |
| T-33 | M3 | Seed and demo | in progress | `crag seed` bulk loader exists; `uv run pytest tests/integration/test_seed.py` → 1 passed (idempotent, invisible until activated); `scripts/seed.py`, `scripts/demo.py`, compose `seed` job pending |
| T-34 | M4 | Tokens, shell, typed client | todo | |
| T-35 | M4 | Ask screen (FR-10) | todo | |
| T-36 | M4 | Evidence viewer (FR-9, FR-3) | todo | |
| T-37 | M4 | Admin and evaluation screens (FR-14, FR-12) | todo | |
| T-38 | M4 | Playwright, axe, screenshots | todo | |
| T-39 | M5 | evalgate suites and offline gate | todo | |
| T-40 | M5 | Ablation | todo | |
| T-41 | M5 | Red-team (FR-13) | todo | |
| T-42 | M5 | Judge calibration and live evals | todo | |
| T-43 | M6 | Tracing, logs, step records | todo | |
| T-44 | M6 | Metrics, dashboard, alerts | todo | |
| T-45 | M6 | Threat model and scans (FR-11, FR-13) | todo | |
| T-46 | M6 | Performance budgets (NFR-1, NFR-2, NFR-8) | todo | |
| T-47 | M7 | Images and compose (NFR-7) | todo | |
| T-48 | M7 | CI workflows | todo | |
| T-49 | M8 | Documentation and demo capture | todo | |
| T-50 | M9 | Reviews and fixes | todo | |
| T-51 | M9 | Final verification | todo | |

## Global Definition of Done

- [ ] `make verify` passes from a fresh clone (§19) with no API keys set.
- [ ] `docker compose up -d --wait` brings every service to healthy; `make seed` and `make demo` run the scripted scenario end to end.
- [ ] `make test-docker` runs the full test suite inside containers and passes.
- [ ] Unit, integration, contract and E2E suites pass; line coverage is at least 85% on core packages and 70% overall.
- [ ] Offline evals meet every threshold in §11, and `evals/REPORT.md` is generated by script from the latest run.
- [ ] Lint, format and type checks are clean.
- [ ] Security scans report no high or critical findings, or each one is documented with a reason in `docs/security.md`.
- [ ] Every workflow in §17 exists and passes actionlint; if a GitHub remote exists and CI results can be observed, the pushed branch is green.
- [ ] Every screen in §13 is implemented with loading, empty, error and success states; axe reports no serious violations; Playwright captured the screenshots in `docs/images/`.
- [ ] The harness in §7 is complete: CLAUDE.md, AGENTS.md, settings, hooks with passing tests, rules, subagents, skills and `.mcp.json`.
- [ ] Every document in §18 exists, and every number in the README points to the command or report that produced it.
- [ ] The `reviewer` subagent's final verdict is "ship", and `security-review` findings are fixed or documented.
- [ ] `PROGRESS.md` has every task checked with evidence, and `docs/KNOWN_LIMITATIONS.md` lists what is not done.
- [ ] Every commit is authored and committed by the maintainer, and no commit message or pull request contains `Co-Authored-By`, `Claude-Session` or "Generated with Claude Code" (checked as in §19).
- [ ] `BUILD.md` lives at `docs/specs/000-build-spec.md`; all work is committed, and pushed when a remote exists.

Project-specific:

- [ ] Each of FR-1, FR-2, FR-3, FR-4, FR-5, FR-6, FR-7, FR-8, FR-9, FR-10, FR-11, FR-12, FR-13 and FR-14 passes its named test in §3.1.
- [ ] ACL leakage = 0 on all 300 eval cases and `crag_acl_postcheck_violations_total` = 0 after `make demo`.
- [ ] Hallucinated citation rate = 0 and stale-version citation rate < 0.01 in `evals/REPORT.md`.
- [ ] `make bench` meets NFR-1, NFR-2, NFR-3 and NFR-8.
- [ ] The ablation table is in `evals/REPORT.md`; `make redteam` reports 0 failures; `make up` is healthy in < 5 minutes.
