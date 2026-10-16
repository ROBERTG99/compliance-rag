# PROGRESS

## Needs the maintainer

- Switch `third_party/evalgate/` to `evalgate @ git+https://github.com/ROBERTG99/evalgate@v0.1.0` once that tag is published (the repository currently has no tag).
- Maintainer review of 40 questions from `evals/datasets/questions.v1.jsonl` (labels are by construction).

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
| T-21 | M2 | Rerankers (FR-7) | in progress | `uv run pytest tests/unit/rerank` → 7 passed (dev-only fit, deterministic weights, Cohere recorded shape + fallback, cross-encoder fallback); fitting against the seeded index pending |
| T-22 | M2 | LLM gateway, FakeLLM, cassettes | done | `uv run pytest tests/unit/llm tests/harness/test_import_contract.py` → 8 passed (refusal → LLMRefusal, max_tokens → LLMMaxTokens, 400 surfaces, 529 → GenerationUnavailable, adaptive thinking + effort + json_schema + cached system, cassette precedence + mismatch); `lint-imports` → contract KEPT |
| T-23 | M2 | Guards and PII redaction (FR-13) | done | `uv run pytest tests/unit/guard` → 15 passed (8 injection templates ≥ 0.7, filler/fact sentences < 0.7, 30 corpus canaries removed, output guard, PII redaction); PII spy: `tests/unit/llm/test_gateway.py::test_pii_never_reaches_the_provider` passes |
| T-24 | M2 | Citation verifier (FR-9) | done | `uv run pytest tests/unit/graph/test_verify_citations.py` → 7 passed (fabricated quote → claim_rejected, chunk_not_in_context, numeric_mismatch + answer rewrite, offsets, NFKC; Hypothesis 80+80 examples: whitespace-changed substrings accepted, 1-char mutations rejected) |
| T-25 | M2 | Graph, abstention, follow-up (FR-8) | todo | |
| T-26 | M3 | Dev OIDC and auth (FR-11) | todo | |
| T-27 | M3 | Ask and SSE (FR-10, FR-11) | todo | |
| T-28 | M3 | Documents and S3 inbox (FR-1) | todo | |
| T-29 | M3 | ACL sync, jobs, lag (FR-14, FR-11) | todo | |
| T-30 | M3 | Feedback and audit (FR-12) | todo | |
| T-31 | M3 | Limits and errors (NFR-6) | todo | |
| T-32 | M3 | OpenAPI and contract tests | todo | |
| T-33 | M3 | Seed and demo | todo | |
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
