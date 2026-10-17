# PROGRESS

## Needs the maintainer

- Switch `third_party/evalgate/` to `evalgate @ git+https://github.com/ROBERTG99/evalgate@v0.1.0` once that tag is published (the repository currently has no tag).
- Maintainer review of 40 questions from `evals/datasets/questions.v1.jsonl` (labels are by construction).
- Provider fixtures for Titan/OpenAI embeddings and Cohere rerank are synthetic (documented response shapes); re-record with `make record-fixtures` when keys are available.

## Resume here (handoff, 2026-10-17)

**State:** M0–M3 are done and reviewed ("ship"). M4 (T-34…T-38) is done; its review said "fix first" and every
blocker/should-fix is now fixed (`cee74cb`, `b57cf9c`) — **re-run the `reviewer` (and `ux-reviewer`) on M4 first**
(`git diff bdc5322..HEAD -- web tests/e2e docs/images docker compose.yaml`). M5 has started: T-39 is in progress
(see below). Branch `feat/practical-planck-8e2t30`, everything committed and pushed; working tree clean.

### Milestone reviews

| Milestone | Reviewer verdict | Notes |
|---|---|---|
| M0 | "ship" (after fixes) | Guard rewritten per review (segment tokeniser, identity/force-push variants, dataset false positives). |
| M1 | "ship" | Follow-ups applied (audit TRUNCATE trigger, float hashing, `make corpus` exports datasets, env.example both directions). Deferred items in `docs/KNOWN_LIMITATIONS.md`. |
| M2 | "ship" (re-review after `e847e0f`, `6047fd5`, `8cb824a`) | All five reviewer blockers and ACL-audit items 1, 3, 5, 7 fixed and verified (35 M2 integration tests). |
| M3 | "ship" (re-review after fixes `302e3d8`..`3f8d73e` and follow-ups) | Blockers fixed: SSE reads vs the Redis socket timeout (`302e3d8`), ACL change racing ingestion and 409 overwriting raw bytes (`561b7c1`). Should-fix 4–12, re-review follow-ups (activation-time ACL test, inbox audit, SSE bookkeeping sweep) and most nits fixed; full suite green after the question-length contract fix. Remaining nits in `docs/KNOWN_LIMITATIONS.md`. |
| M4 | "fix first" → fixes applied, **re-review pending** | Blocker: data/answers fetched under one persona stayed visible after an in-page persona switch → cache cleared on every identity change, ask run keyed by identity, 401/expiry sign-out (`cee74cb`, vitest + Playwright regression tests). Should-fix from `reviewer` and `ux-reviewer` fixed in `b57cf9c` (list below). `make e2e` → 8 passed (axe at 1280 and 375 px); `pnpm -C web exec vitest run` → 33 passed; screenshots regenerated. |

### M4 review fixes (`b57cf9c`) and what is left

- Fixed: persona switcher opt-in (`VITE_DEV_PERSONAS=1` build arg, compose sets it; documented in `docs/DEVELOPMENT.md`); SSE resume retries 502/503/504 and resets attempts on progress; Retry only for retryable problems (no Retry on 404/422); triage Retry re-sends the failed PATCH and success is announced; feedback “Thanks” is a focused `role=status`; visible comment label; citation chips ≥ 24 px with “[n] citation: DOC vN” names; “AI-generated” shown as soon as claims stream; abstention `role=status` rendered up front; skip link styled; `<main tabIndex=-1>` focused and `document.title` set per route; `--crag-control` token (≥ 3:1) for control borders; Inter/Source Serif 500 imported; ablation chart in responsive HTML (labels wrap) with explicit units by name suffix (`_ms`, `_usd`); focusable scroll regions for the jobs and ablation tables; jobs keep stale data with an inline error, pause toggle, “Updated …” time, `scope=col`, time zones; evidence text at 72ch on the serif element, highlight offsets on raw text, Back button; library search debounced; future versions labelled “Announced”.
- Left (recorded in `docs/KNOWN_LIMITATIONS.md` or still to do): evidence shows the cited chunk, not the whole version text; quote travels in the URL (`?quote=`); jobs list capped at 200 with no “Load more”; “Current version vN” links to the document timeline, not the version text; header stacks to ~190 px at 375 px; no question character counter; **evaluation screenshots show only the empty state until `make eval` writes `evals/reports/latest.json`** — re-run `make docs` after T-39.

### M5 / T-39 in progress (`cd95f4a`)

Done:
- `third_party/evalgate/` subset: `suite.py` (YAML suites, thresholds with `exclusive`, metric `aggregate` mean/ratio/max/p95, `unit`, `gate`, `hard`), `runner.py` (`evalgate.report.v1`, case errors fail the run, slim per-case output), `check.py` (thresholds + `--max-regression-pp` for rate metrics; hard gates allow no regression), `report.py` (markdown), `calibrate.py`, `cli.py` (`evalgate run|check|report|calibrate`). Tests: `tests/unit/evalgate/` (7).
- `FakeJudge` ignores citation markers (`[1]` is not a fact): offline agreement on `judge_labels.v1.jsonl` = 1.000 on 80 labels (labels are by construction, so this only shows consistency with the offline rules). `evals/rubrics/answer.yaml` (min_agreement 0.8) → `make calibrate-judge` should pass (not yet run via make).
- Metrics graded against **corpus ground truth** (`compliance_rag.evals.metrics.Truth`/`corpus_truth`): ACL leakage (retrieved, cited and versions documents plus restricted id/span, punctuation-insensitive; rows without persona raise), stale citations by true validity windows. Tests: `tests/unit/evals/test_metrics.py` (4).
- Suites `evals/suites/rag.yaml` (all §11 offline metrics; acl_leakage and hallucinated_citation_rate are hard gates) and `evals/suites/retrieval.yaml`; targets `compliance_rag.evals.target:RagTarget` / `RetrievalTarget` (provenance: LLM label, model ids, prompt and weight hashes, embedder fingerprint; cited chunks re-fetched from Postgres) with the shared cache warm-up (`retrieval/warmup.py`, also used by the API).

Next steps (in order):
1. Smoke-run against the running stack on **dev** first: `uv run evalgate run evals/suites/retrieval.yaml --split dev --limit 20 --out /tmp/x.json` (the first smoke run, before the warm-up was added, hit cold-cache `RetrievalUnavailable` on 9/20 cases; re-check it now passes), then `rag.yaml` on dev.
2. Write `scripts/run_evals.py` (`make eval`): run both suites on `--split test` into `evals/reports/runs/` (gitignored), `evalgate check --baseline evals/reports/baseline.json --max-regression-pp 1.0`, `evalgate report --md evals/REPORT.md` with a preface labelling the numbers FakeLLM-produced (offline), and write `evals/reports/latest.json` (`EvalsLatest`: generated_at, split, llm, metrics, ablation from `evals/reports/ablation.json` when present) for `GET /v1/evals/latest`.
3. First run → commit `evals/reports/baseline.json`, `evals/REPORT.md`, `evals/reports/latest.json`; check every §11 threshold (never tune on test — if a threshold fails, investigate on dev).
4. Optional per the ACL audit: add `violations` (post-check count) to the target output and assert 0 per case.
5. Then T-40 ablation (`scripts/ablation.py`, five configs incl. Qdrant profile), T-41 Promptfoo red-team, T-42 (`scripts/eval_live.py` budget stop test; live runs need keys → "Needs the maintainer"), M5 reviewer, re-shoot `make docs`.

### Still-open review notes (non-blocking)

- Side channel to document (T-45): BM25 IDF and the LSA embedder are fitted over all chunks including restricted ones → `docs/KNOWN_LIMITATIONS.md`.
- `retrieval` SSE event counts (`n_bm25`, `n_vector`) are pre-post-check counts; the Postgres re-check (`b10f6db`) now covers `visible` for index legs — document in `docs/security.md` (T-45/T-49).
- Earlier M2 notes: context-guard sentence removal shifts offsets inside guarded chunks; NFKC per-char vs whole-string normalisation in `locate`; wrap non-retryable `anthropic` 4xx in an `LLMError` subclass; a job failing during the OpenSearch/Qdrant sync on its last attempt should stay `activating` (or `make replay-failed-jobs` must repair it); `EmbedderNotReady` leaves a job in `embedding`.
- One more retrieval query per ask (Postgres re-check of index hits) counts toward NFR-1: watch it in `make bench` (M6).

### Environment notes for the next session (cloud container)

- Start Docker per Appendix A (the SessionStart hook does it): `mirror.gcr.io` registry mirror; MinIO image is built from source (`docker/minio.Dockerfile`), OpenSearch from the Docker Hub mirror, `public.ecr.aws`/ghcr.io blobs are blocked.
- Disk allowance is tight: image rebuilds fill it (it dropped to 3.2 GB free once). Before `docker compose up --build` run `docker builder prune -af` (frees ~8 GB); check with `df -h /`. A full disk made OpenSearch/Postgres fail and showed up as `retrieval_unavailable` 503s.
- Dev stack: `docker compose up -d --build --wait` (postgres, redis, opensearch, minio, dev-oidc, migrate, seed, api, worker, web). The seed is idempotent (`make seed` → `already_seeded: 400 documents, 1199 versions, 22717 chunks`). The demo has activated AML-0107 v4 in the dev stack. Web: http://localhost:8600 (persona switcher in the header), API http://localhost:8610, dev-oidc http://localhost:8612.
- Checks: `make check-fast`; web: `pnpm -C web typecheck && pnpm -C web exec eslint . && pnpm -C web exec vitest run`; e2e: `make e2e` (needs the stack; Playwright via `NODE_PATH=web/node_modules`, browsers in `/opt/pw-browsers`); screenshots/video: `make docs`; demo: `make demo`.
- Commit with `scripts/task_commit.sh "<message>"` (ruff fix/format, `make check-fast`, refuses on red, `git add -A`). For path-scoped commits never pipe `make check-fast` into `tail` (it hides the exit code — that let one red commit through, fixed in the next commit); use `if make check-fast >/dev/null 2>&1; then …`.
- Tools: gitleaks, actionlint, hadolint, trivy in `~/.local/bin` (`scripts/install_tools.sh`). Reading `.env*` is denied by the harness (also via grep).
- Dev-split tuning numbers (not reported results, FakeLLM): recall@10 0.962, MRR@10 0.973, key-fact 0.939, abstention 0.972–0.978, ACL leak 0, retrieval p95 ≈ 95–115 ms.

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
| T-32 | M3 | OpenAPI and contract tests | done | `uv run pytest tests/contract/test_schemathesis.py` → 19 operations × Schemathesis cases pass (all checks except `ignored_auth`, covered by a 401 test over every /v1 operation, and `positive_data_acceptance`, see DECISIONS), spec freshness test; `python scripts/export_openapi.py docs/openapi.json --check` → OK. Found and fixed: lax coercion (`stream: 0`, `valid_at=0`), `follow_up_of: ""` → 500, NUL bytes in text → 500, 405 `Allow` header, `GET /v1/evals/latest` missing. |
| T-33 | M3 | Seed and demo | done | `make seed` → `already_seeded: 400 documents, 1199 versions, 22717 chunks`; `make demo` → all §3.4 steps (main 1–7, secondary a–c) and `demo ok` against the compose stack; `uv run pytest tests/integration/test_demo.py tests/integration/test_seed.py` pass (demo in-process on its own environment). Found and fixed on the way: cold-cache 503s after restart (API warm-up), seed racing a restarted OpenSearch, leg failures were not logged. |
| T-34 | M4 | Tokens, shell, typed client | done | `pnpm -C web exec vitest run` → 11 passed (PKCE S256, claims decoding/expiry, persona switch hides admin nav, callback code exchange with state check, SSE parse/resume/no-retry-on-404); `tsc -b --noEmit` and `eslint .` clean; Chromium against the compose stack: Sign in → dev-oidc → callback → `analyst@northwind.test (analyst)`, persona → admin shows admin nav, Inter and Source Serif 4 loaded, no console errors. |
| T-35 | M4 | Ask screen (FR-10) | done | `pnpm -C web exec vitest run src/routes/ask` → 4 passed (claims before `final` in an `aria-live` region with focusable citation chips, final versions/as-of/AI label/confidence, retracted claim removed, uniform abstention banner, stream `error` and 429 problem with retry and `Retry-After`, feedback POST); Chromium against the stack: PoA question → claim [1], KYC-0042 v3, pipeline timings, no console errors. |
| T-36 | M4 | Evidence viewer (FR-9, FR-3) | done | `pnpm -C web exec vitest run src/routes/evidence` → 3 passed (whitespace-tolerant quote location, `<mark>` highlight, version badge, superseded note linking the current version, 404 problem with retry); Chromium: citation [1] → KYC-0042 v3 with the quote highlighted at 72ch; as_of 2025-12-31 → v2 with “superseded: valid until 2026-03-01 · Current version v3”. |
| T-37 | M4 | Admin and evaluation screens (FR-14, FR-12) | done | `pnpm -C web exec vitest run` → 26 passed (jobs: pending lag tiles, status/attempts/errors, filter reaches API, empty state; library: admin-only restricted badges, domain filter, cursor “Load more”, version timeline in force/superseded; evaluation: provenance, metrics table, per-metric ablation bars + table view, 404 → empty state; feedback: triage PATCH with `split: dev`, test-split items cannot be added; admin routes are not-found for other roles). Chromium against the stack as admin: lag tiles, 18 restricted badges on page 1, KYC-0042 v1–v3 timeline, 3 feedback cards, evaluation empty state, no console errors. |
| T-38 | M4 | Playwright, axe, screenshots | done | `make e2e` → 6 passed against the compose stack (main journey with keyboard citation → highlighted evidence and feedback, as_of 2025-12-31 superseded evidence, support abstention without CMP-0215, legal answer, admin routes not found for analyst, admin screens with live data), axe WCAG 2.2 AA with no serious/critical violations on every screen visited; `make docs` → 3 passed: 16 screenshots (8 screens × light/dark) and `docs/images/demo.webm`. Also fixed: the answer is kept when returning from the evidence viewer (run state lifted above the routes). |
| T-39 | M5 | evalgate suites and offline gate | done | `make eval` → rag PASS, retrieval PASS on the test split (120 cases each): recall@10 0.920, MRR@10 0.943, key-fact 0.886, citation precision 1.000, hallucinated 0, ACL leakage 0, stale 0, abstention 0.933, retrieval p95 ≈ 100 ms (`evals/REPORT.md`, FakeLLM); baseline written once with `--write-baseline`, second run passes `evalgate check` against it; `make calibrate-judge` → agreement 1.000 on 80 labels; `uv run pytest tests/unit/evals tests/unit/evalgate` pass. |
| T-40 | M5 | Ablation | done | `uv run pytest tests/unit/evals/test_ablation.py tests/integration/test_reindex.py` → 5 passed (five configurations; Qdrant rebuilt from Postgres keeps ACL/validity/visibility, idempotent; re-embed reproduces the LSA fingerprint); `make eval-ablation` (test split, 120 cases) → bm25 0.812/0.825/15 ms, vector-pgvector 0.733/0.664/65 ms, vector-qdrant 0.744/0.676/28 ms, hybrid 0.818/0.751/73 ms, hybrid+rerank 0.920/0.943/101 ms (recall@10/MRR@10/p95) in `evals/REPORT.md`. |
| T-41 | M5 | Red-team (FR-13) | todo | |
| T-42 | M5 | Judge calibration and live evals | in progress | Rubric `evals/rubrics/answer.yaml` and offline calibration (FakeJudge agreement 1.000 on 80 labels, `tests/unit/evalgate`) done; `scripts/eval_live.py` with budget stop still to do. |
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
