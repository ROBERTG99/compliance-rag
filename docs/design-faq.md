# Design FAQ

Fifteen design questions with the code that answers them. References are `path:line` and were checked against
commit `ebe77de`. Numbers come from `evals/REPORT.md` (offline run, FakeLLM, test split), `evals/reports/bench.json`
or `PROGRESS.md`, and are named where they appear. Questions 14 and 15 are design answers for things that are not
implemented.

## 1. How is ACL enforced in each leg?

- One source of filters: `AccessFilter.for_principal` turns the principal's groups, `visible` and the `as_of` validity window into the predicate every backend uses, and refuses a principal with no groups (`src/compliance_rag/retrieval/filters.py:23-28`). Every `search` takes a `Principal`; there is no unfiltered search.
- pgvector: the predicate is the `WHERE` of the HNSW query (`src/compliance_rag/retrieval/filters.py:31`, `src/compliance_rag/retrieval/vector/pgvector.py:15-30`); `hnsw.iterative_scan` keeps recall when the filter removes many neighbours (`src/compliance_rag/retrieval/vector/pgvector.py:84`).
- BM25 on OpenSearch: the same clauses are the `bool.filter` of the query (`src/compliance_rag/retrieval/filters.py:37-52`, `src/compliance_rag/retrieval/bm25.py:185-192`).
- Qdrant: a payload `Filter` passed as `query_filter` (`src/compliance_rag/retrieval/filters.py:55-66`, `src/compliance_rag/retrieval/vector/qdrant.py:84-92`) over indexed payload fields (`src/compliance_rag/retrieval/vector/qdrant.py:36-44`).
- Counted post-check: fused hits are re-tested with `AccessFilter.allows`; a violation is dropped and increments `crag_acl_postcheck_violations_total` (`src/compliance_rag/retrieval/hybrid.py:169-181`, `src/compliance_rag/retrieval/filters.py:68-75`).
- Authoritative re-check: OpenSearch and Qdrant hold copies that can lag, so their hits are re-validated against Postgres in one query; if that fails the leg is dropped (`src/compliance_rag/retrieval/hybrid.py:146-167`, `src/compliance_rag/retrieval/vector/pgvector.py:131-136`, wired at `src/compliance_rag/api/state.py:59`).
- ACL changes commit in Postgres together with their audit row, then the indexes are updated; an index update that fails is retried by a one-minute cron (`src/compliance_rag/worker/acl.py:30-74`, `src/compliance_rag/worker/acl.py:131-144`, `src/compliance_rag/worker/main.py:154`).
- Tests: `tests/integration/test_vector_stores.py:105` (300 nearer restricted chunks still yield 10 authorized hits), `:142` (random group draws never leak), `tests/integration/test_bm25.py:57`, `tests/unit/retrieval/test_hybrid.py:110` and `:140`, `tests/integration/test_acl_sync.py:23` (an unsynced revocation is not served).
- Evidence: `acl_leakage` is 0.000 over 120 cases and is a hard gate (`evals/REPORT.md`, suite `rag`).
- Known gap: BM25 IDF and the LSA fit include restricted chunks, so term statistics (never text or ids) can influence scores (`docs/security.md`, "Known side channels and gaps").

## 2. Why can abstention not reveal restricted documents?

- The filter is inside the query (question 1), so for a principal without access the graph receives the same inputs as for an unknown topic: no hits, or hits below the threshold. Nothing about the restricted document reaches any node.
- `check_sufficiency` abstains with `no_valid_document` or `low_score` (`src/compliance_rag/graph/build.py:317-333`). The reason goes to metrics, the database and traces (`src/compliance_rag/graph/build.py:508-512`, `src/compliance_rag/api/runs.py:76`), never into the response.
- Every abstention response is one constant: fixed message, empty `claims` and `versions`, `confidence: null`, and `cost_usd: null` because cost would tell the causes apart (`src/compliance_rag/graph/respond.py:7-9`, `src/compliance_rag/graph/respond.py:43-53`).
- Unauthorized resources answer 404, not 403, so existence is not confirmed (`src/compliance_rag/api/errors.py:63-65`); runs and their event streams are owner-only (`src/compliance_rag/api/routes/ask.py:151-152`, `src/compliance_rag/api/routes/ask.py:178-194`).
- Test: `tests/integration/test_acl.py:24-39` asks a Legal-only question as legal (answered from CMP-0215) and as support, plus an unknown-topic question as support; the two support bodies are equal except `run_id`, `conversation_id` and `latency_ms`, and the evidence chunk is 404 for support.
- Unit test: `tests/unit/graph/test_graph.py:193-213` (abstentions with different causes build identical bodies).
- Evidence: category `acl_probe` has abstention accuracy 1.000 over 12 cases (`evals/REPORT.md`, "By question category").
- Limits: the integration test compares the non-streaming body (`stream: False`); the streamed path runs the same graph but has no equivalence test. Response time is not equalised and not measured. The term-statistics gap from question 1 applies.

## 3. What if one leg fails?

- Both legs run concurrently, each under `asyncio.wait_for` with `CRAG_LEG_TIMEOUT_MS` (default 250) (`src/compliance_rag/retrieval/hybrid.py:90-97`, `src/compliance_rag/settings.py:70`).
- `gather(..., return_exceptions=True)` keeps the healthy leg's hits; the failed or slow leg is listed in `degraded` and only its error type is logged, because messages can echo query text (`src/compliance_rag/retrieval/hybrid.py:124-134`).
- Fusion and reranking then run on the surviving leg alone; nothing falls back to an unfiltered path. If every leg failed, `RetrievalUnavailable` is raised (`src/compliance_rag/retrieval/hybrid.py:136-137`).
- The degraded state is visible to the caller: the `retrieval` SSE event and the answer's `degraded` field (`src/compliance_rag/graph/build.py:279-287`, `src/compliance_rag/graph/respond.py:39`). Total failure is a retryable 503 `retrieval_unavailable` (`src/compliance_rag/api/errors.py:118-127`) or an SSE `error` event (`src/compliance_rag/api/runs.py:173-177`).
- The Postgres re-check fails closed: if it cannot confirm the index hits, those legs are emptied and marked degraded (`src/compliance_rag/retrieval/hybrid.py:157-162`).
- An all-unknown-terms question embeds to the zero vector and skips the vector leg without marking it degraded (`src/compliance_rag/retrieval/hybrid.py:103-105`).
- Tests: `tests/unit/retrieval/test_hybrid.py:73` (BM25 timeout gives `degraded == ["bm25"]` and vector hits), `:83`, `:89` (both down raises), `:169` (re-check failure fails closed).
- Evidence and limits: `degraded_rate` is 0.000 in `evals/REPORT.md`, but no eval injects a failure. The ablation measures single-leg retrieval without reranking only (BM25 recall@10 0.812, vector 0.756, `evals/REPORT.md` "Retrieval ablation"); answer quality with one leg and the reranker on is untested. Missing BM25 scores lower the reranker features, so degraded runs may abstain more; that is read from `src/compliance_rag/rerank/feature.py:98-99`, not measured.
- Cold caches can push both legs over 250 ms after a restart; the API warms up first (`src/compliance_rag/retrieval/warmup.py`, `docs/KNOWN_LIMITATIONS.md` "Retrieval" row).

## 4. How are quotes verified?

- The model returns JSON claims, each with citations `{chunk_id, quote}` (`src/compliance_rag/graph/build.py:81-109`). A claim survives only if every citation passes `verify_claim` (`src/compliance_rag/graph/verify.py:87-118`).
- The cited chunk must be in the context given to the model (`src/compliance_rag/graph/verify.py:94-96`).
- The quote must be a substring of that chunk after NFKC and whitespace normalisation; the match is mapped back to offsets in the original text (`src/compliance_rag/graph/verify.py:22-23`, `src/compliance_rag/graph/verify.py:34-51`, `src/compliance_rag/graph/verify.py:70-84`).
- A match that starts or ends inside a number is rejected, so "EUR 1" cannot pass for "EUR 1,000" (`src/compliance_rag/graph/verify.py:54-67`).
- Every number or date in the claim text must appear in that claim's quotes (`src/compliance_rag/graph/verify.py:101-103`); the summary answer is replaced by the joined claims if it carries a number no verified claim has (`src/compliance_rag/graph/verify.py:121-127`).
- Each claim is verified as its JSON closes, before it is emitted (`src/compliance_rag/graph/build.py:384-388`), and the surviving claims are re-checked against the context at the end (`src/compliance_rag/graph/build.py:472-479`). Reasons: `schema_invalid`, `output_guard`, `chunk_not_in_context`, `quote_not_found`, `numeric_mismatch`, `retracted`.
- Tests: `tests/unit/graph/test_verify_citations.py:50` (fabricated quote), `:61`, `:71`, `:104` and `:119` (Hypothesis: whitespace-changed substrings pass, one-character mutations fail), `:129` (quote cut inside a number).
- Evidence: hallucinated citation rate 0.000 (hard gate) and citation precision 1.000, both over 95 citations; the metric re-reads the quoted text from Postgres (`evals/REPORT.md`, `src/compliance_rag/evals/metrics.py:160-172`, `src/compliance_rag/evals/target.py:79-91`).
- Limit: verification proves the quote exists and the numbers match. It does not prove that the claim's wording follows from the quote; a claim without numbers could misstate a quote. The offline FakeLLM quotes itself, so the eval cannot show this risk; a live run is needed.

## 5. How are stale citations avoided?

- Validity is part of every query: `valid_from <= as_of` and `valid_to` null or after `as_of`, plus `visible` (`src/compliance_rag/retrieval/filters.py:31`, `src/compliance_rag/retrieval/filters.py:37-66`). `as_of` defaults to today and a future date is 422 except for `content_admin` (`src/compliance_rag/api/runs.py:44-49`).
- Activation is one Postgres transaction: the new version becomes active, the version it supersedes is closed at the new `valid_from`, and the chunks become visible (`src/compliance_rag/ingest/pipeline.py:326-390`). A unique index allows one open version per document (`migrations/versions/0001_core.py:33-34`).
- A lagging index copy cannot serve a closed version because the Postgres re-check applies the same validity predicate (`src/compliance_rag/retrieval/hybrid.py:146-167`, `src/compliance_rag/retrieval/vector/pgvector.py:32`).
- The answer lists the cited versions and flags those with an end date as `superseded` (`src/compliance_rag/graph/respond.py:13-31`).
- Tests: `tests/integration/test_ingest_pipeline.py:49` (a new version supersedes the previous one in Postgres and OpenSearch), `:84` (crash between stores), `tests/integration/test_sse.py:73` (`as_of` 2025-12-31 returns version 2 marked superseded).
- Evidence: stale-version citation rate 0.000 over 94 cited versions (threshold below 0.01); the `version_sensitive` category scores 1.000 on 8 cases (`evals/REPORT.md`).
- The metric grades against the corpus generator's true validity windows, not the stores' copies, and counts an unknown version as stale (`src/compliance_rag/evals/metrics.py:129-145`).
- Limit: the citation verifier checks text, not dates; freshness rests on the filter. Validity is only as good as the `valid_from` and `valid_to` supplied at upload, and a document that is wrong about itself is not detected.

## 6. Why RRF k=60?

- Reciprocal Rank Fusion scores a chunk by `sum(1 / (k + rank))` over the legs it appears in, then breaks ties on `chunk_id` (`src/compliance_rag/retrieval/fusion.py:8-21`). The default `k = 60` is set in `src/compliance_rag/settings.py:67` (`CRAG_RRF_K`) and `src/compliance_rag/retrieval/hybrid.py:76`.
- Why rank fusion: BM25 scores are unbounded and corpus-dependent while cosine is bounded, so a weighted score sum needs normalisation and a tuned weight. Ranks need neither and still work when one leg is missing (question 3).
- Why 60: it is the conventional default for RRF. The ranks decay gently, so a chunk found by both legs beats a chunk ranked first by one leg only (`tests/unit/retrieval/test_hybrid.py:95-102`).
- Honest status: `k = 60` was not tuned on this corpus and no sweep over `k` exists in the repository (`docs/adr/0003-rrf-over-weighted-score-fusion.md`). Its effect is also bounded, because only the top `leg_k` fused candidates go to the reranker (`src/compliance_rag/graph/build.py:293`).
- What the ablation shows (`evals/REPORT.md`, "Retrieval ablation", 88 questions, differences of one or two questions are noise): hybrid recall@10 0.830 against 0.812 for BM25 and 0.756 for vector, but hybrid mrr@10 0.763 is below BM25 alone at 0.825.
- Reranking fixes the ordering: hybrid plus rerank reaches recall@10 0.920 and mrr@10 0.943 (same table). Fusion is a shortlist step here, not the ranking.
- To change it, set `CRAG_RRF_K` and add an ablation row; none has been run.

## 7. How were reranker weights fitted without test leakage?

- Weights come from `scripts/fit_reranker.py`, which reads the question file and keeps `split == "dev"` rows only (`scripts/fit_reranker.py:86-88`). Candidates come from the real hybrid retrieval; a candidate is positive when it holds a gold span (`scripts/fit_reranker.py:28-51`).
- `fit_weights` filters to dev again and raises if no dev row exists (`src/compliance_rag/rerank/feature.py:181-218`, `src/compliance_rag/rerank/feature.py:191-193`). The shipped file records the split, `n_questions`, `n_samples` and a hash of the dev ids (`src/compliance_rag/rerank/feature_weights.json`).
- The abstention threshold is calibrated on dev only: the intercept is shifted so that "top score below tau" best separates must-abstain from answerable dev questions (`scripts/fit_reranker.py:54-72`).
- Tests: `tests/unit/rerank/test_feature.py:82-103` (only dev rows are requested, the fit is deterministic, test-only input raises).
- Feedback cannot move a test question into dev: triage refuses any question whose normalised text is in a test split and fails closed without the registry (`src/compliance_rag/evals/splits.py:20-44`, `tests/unit/evals/test_splits.py:18`). Committed datasets are append-only by version (`.claude/rules/evals.md`).
- Reported numbers use the test split (120 cases, `evals/REPORT.md`); tuning numbers are in `PROGRESS.md` ("Dev-split tuning numbers": recall@10 0.962 on dev against 0.920 on test).
- Weak points: the split is stratified by question, not by document, and 52 of the 160 gold documents serve both splits (`docs/KNOWN_LIMITATIONS.md`, first "Evals" row). The features are document-agnostic, which limits the leak but does not remove it; a `questions.v2` split by document is the fix.
- Labels are by construction and unreviewed (same file). `docs/DECISIONS.md` ("`RetrievalTarget` reranks only the top `leg_k`") records the one time a first test run exposed a harness mismatch, fixed without changing any system parameter.

## 8. Why LSA offline?

- The default embedder is `LocalLSAEmbedder`: TF-IDF with truncated SVD, 384 dimensions, seed 2026 (`src/compliance_rag/embed/lsa.py:18-38`, `src/compliance_rag/embed/lsa.py:40-55`). It needs no key, no model download and no network, so tests, evals, the demo and CI run on a clean machine (`src/compliance_rag/settings.py:56`, `src/compliance_rag/settings.py:59`).
- Reproducibility is checked: two fits on the same corpus match within 1e-6 (`tests/unit/embed/test_lsa_embedder.py:20`, `PROGRESS.md` row T-16).
- The model is saved as `.npz` without pickle (`src/compliance_rag/embed/lsa.py:67-94`) and fingerprinted (`src/compliance_rag/embed/lsa.py:96-107`); the index records which embedder built it and the API refuses a mismatch (`src/compliance_rag/embed/registry.py:36-63`). The fingerprint appears in every eval report (`lsa-384-09a9d7d3f5ee4d53`, `evals/REPORT.md`).
- `crag reindex --reembed` refits it in seed order and reproduces the same model (`src/compliance_rag/ingest/reindex.py:91-107`, `tests/integration/test_reindex.py:71`).
- The test socket guard blocks public network access, so an accidental provider call fails the suite (`tests/conftest.py:26-56`).
- Cost: LSA is lexical and statistical, not a neural embedder. The vector leg is the weakest leg (recall@10 0.756 against 0.812 for BM25, `evals/REPORT.md` "Retrieval ablation"), so hybrid numbers say little about what a production embedder would add.
- The Titan and OpenAI adapters exist (`src/compliance_rag/embed/titan.py`, `src/compliance_rag/embed/openai_embed.py`) but are tested against synthetic fixtures only (`PROGRESS.md`, "Needs the maintainer").
- LSA and BM25 statistics are fitted over all chunks, including restricted ones (`docs/security.md`, "Known side channels and gaps").

## 9. How does streaming avoid unverified text?

- The model's JSON is parsed incrementally; a claim object is released only when its closing brace arrives (`src/compliance_rag/graph/stream.py:10-61`).
- For each released claim, `handle` runs in this order: schema check, claim cap, output guard, citation verification (`src/compliance_rag/graph/build.py:367-388`). Only then does it emit `claim` (`src/compliance_rag/graph/build.py:394`). A failure emits `claim_rejected` with a reason instead (`src/compliance_rag/graph/build.py:362-365`).
- `token` events are six-word slices of the already verified claim text, not raw model tokens (`src/compliance_rag/graph/build.py:395-398`).
- If the model refuses after claims were streamed, each one is retracted and the run abstains (`src/compliance_rag/graph/build.py:408-419`). If the final re-check drops a claim, it is retracted too (`src/compliance_rag/graph/build.py:472-483`).
- The final answer is assembled from exactly the streamed claims (`src/compliance_rag/graph/build.py:448-454`, `src/compliance_rag/graph/build.py:484-493`). The `final` event is the same stored response (`src/compliance_rag/api/runs.py:119-120`, `src/compliance_rag/api/runs.py:162-172`), and events are replayable with `Last-Event-ID` (`src/compliance_rag/api/sse.py:77-192`).
- Tests: `tests/unit/graph/test_graph.py:105` (only verified claims stream, claims come before tokens), `:277` (an invalid claim never reaches the stream and the final answer matches), `:292` (a canary never appears in claim or token events), `:305` (retraction), `tests/integration/test_sse.py:55-70` (every token is text of a verified claim).
- Cost: the first visible text waits for the first complete verified claim. `evals/reports/bench.json` (`nfr2_ttft`) has a last-run p95 of 231.5 ms and a worst of 289.7 ms over three runs, but with the FakeLLM, which delivers its whole answer at once (`src/compliance_rag/llm/gateway.py:285-289`). Time to first claim with a live model is not measured.

## 10. How are injected instructions handled?

- Layers, in order. At ingestion each chunk gets an `injection_score` (`src/compliance_rag/ingest/pipeline.py:297`, `src/compliance_rag/guard/context_guard.py:117-119`).
- At query time `guard_context` blanks every sentence scoring at least 0.7 (assistant-directed imperatives, "ignore previous", role tokens, hidden Unicode), keeping offsets stable (`src/compliance_rag/graph/build.py:307-315`, `src/compliance_rag/guard/context_guard.py:13`, `src/compliance_rag/guard/context_guard.py:95-114`, `src/compliance_rag/guard/context_guard.py:122-139`).
- Documents reach the model inside `<document>` tags with the closing tag escaped, and the prompt calls their content untrusted data (`src/compliance_rag/graph/build.py:164-172`, `prompts/generate_answer.v1.md:5`).
- The model has no tools and must return schema-valid JSON with verifiable quotes (`src/compliance_rag/graph/build.py:81-109`), so an obeyed instruction has nowhere to act and no unquoted text can stream (question 9).
- The output guard blocks canary tokens and URLs absent from the context, per claim (its text and every quote) and on the final answer (`src/compliance_rag/guard/output_guard.py:18-27`, `src/compliance_rag/graph/build.py:379-381`, `src/compliance_rag/graph/build.py:485`).
- Tests: `tests/unit/guard/test_context_guard.py:12` and `:44` (all 30 injected corpus documents are cleaned), `tests/unit/graph/test_injection.py:41-53` (with the guard on the fact survives; with it off the fact is lost), `tests/unit/graph/test_graph.py:292`.
- Evidence: `make redteam` ran 40 attacks with 0 failures, and 28 of 30 injected documents were still answered with their fact (`evals/REPORT.md`, "Red-team"). That count is gated against a baseline, so a missing context guard shows up.
- Limits: the guard is pattern-based, and its templates come from the same generator as the red-team documents (`PROGRESS.md` row T-23), so it is not shown to catch unseen phrasing (`tests/unit/guard/test_context_guard.py:9`). The FakeLLM obeys only `CANARY-` instructions, so the offline red-team says nothing about a real model's compliance (`docs/KNOWN_LIMITATIONS.md`, "Evals" rows). A live red-team run has not been done.

## 11. What happens on a crash between stores?

- Postgres is the source of truth; OpenSearch and Qdrant are rebuildable copies. An ingest job writes chunks as invisible to every store (`src/compliance_rag/ingest/pipeline.py:301`, `src/compliance_rag/ingest/pipeline.py:308-314`), commits activation in Postgres alone (`src/compliance_rag/ingest/pipeline.py:326-390`), then mirrors it with idempotent update-by-query calls (`src/compliance_rag/ingest/pipeline.py:416-431`).
- The job stays `activating` until every store is in sync (`src/compliance_rag/ingest/pipeline.py:481`, `src/compliance_rag/ingest/pipeline.py:485-498`). A replay resumes there; it rebuilds the activation from Postgres if the first run died after the commit (`src/compliance_rag/ingest/pipeline.py:434-447`).
- Replays are safe because chunk ids are deterministic (`src/compliance_rag/ingest/pipeline.py:103-104`), writes are upserts (`src/compliance_rag/retrieval/vector/pgvector.py:34-43`), and uploads are idempotent by content hash (`src/compliance_rag/ingest/pipeline.py:99-100`). The worker retries with backoff until the job's attempts in Postgres reach three; the last attempt raises `FinalIngestFailure` and is not retried, and `make replay-failed-jobs` re-queues failed jobs (`src/compliance_rag/worker/main.py:42-58`, `src/compliance_rag/ingest/pipeline.py:34`, `src/compliance_rag/ingest/pipeline.py:514`).
- Until the replay, queries stay correct: the Postgres re-check drops stale index hits and counts them in `crag_stale_index_hits_total` (`src/compliance_rag/retrieval/hybrid.py:146-167`).
- ACL changes follow the same rule, with the retry done by the `reconcile_acl` cron (`src/compliance_rag/worker/acl.py:30-74`, `src/compliance_rag/worker/acl.py:131-144`, `src/compliance_rag/worker/main.py:123-129`).
- Total loss of an index: `crag reindex` rewrites it from Postgres under the same ids (`src/compliance_rag/ingest/reindex.py:77-129`).
- Tests: `tests/integration/test_ingest_pipeline.py:84` (after a crash Postgres serves version 3 while BM25 still serves version 2; the replay brings both to version 3 with 2 attempts), `tests/integration/test_acl_sync.py:23`, `tests/integration/test_ingest_races.py:48`, `tests/integration/test_reindex.py:21`.
- Cost: in the window the new version is missing from the BM25 leg (a recall dip, not a leak). A job that exhausts its three attempts after the Postgres commit is marked `failed` (`src/compliance_rag/ingest/pipeline.py:500-515`) and needs a manual replay (`make replay-failed-jobs`, `Makefile:132-133`); unlike ACL syncs, no cron retries ingest jobs.

## 12. How is cost controlled?

- Abstain before generating: when no context survives or the top rerank score is below tau, the run ends with zero LLM calls (`src/compliance_rag/graph/build.py:317-333`, `tests/unit/graph/test_graph.py:88-102`). Retrieval, fusion, reranking and verification are deterministic code with no token cost.
- Bounded input: at most `topk_context` chunks reach the prompt (8) and at most 8 claims are kept (`src/compliance_rag/settings.py:68`, `src/compliance_rag/graph/build.py:54`, `src/compliance_rag/graph/build.py:311`, `src/compliance_rag/graph/build.py:375`); questions are limited to 2,000 characters (`src/compliance_rag/api/routes/ask.py:40`).
- Routes: the condense step runs only for follow-ups and uses the fast model (`src/compliance_rag/graph/build.py:201-202`, `src/compliance_rag/graph/build.py:514-515`); each route has its own model setting, effort, `max_tokens` and timeout (`src/compliance_rag/llm/routing.yaml:3-17`).
- Gateway: the stable system prefix is cache-marked, the SDK retries at most 3 times, and each call has a route timeout (`src/compliance_rag/llm/gateway.py:228`, `src/compliance_rag/llm/gateway.py:202`, `src/compliance_rag/llm/gateway.py:207`, `src/compliance_rag/llm/gateway.py:292`). Every call is the gateway's alone, so accounting cannot be bypassed (import-linter contract, `tests/harness/test_import_contract.py`).
- Accounting: token cost is estimated from list prices in `src/compliance_rag/llm/routing.yaml`, exported as `crag_llm_cost_usd_total` and stored per answer (`src/compliance_rag/llm/gateway.py:86-105`, `src/compliance_rag/llm/gateway.py:376-380`, `src/compliance_rag/obs/metrics.py:17`, `src/compliance_rag/api/runs.py:78`). Abstention bodies hide the cost (`src/compliance_rag/graph/respond.py:52`).
- Load: 30 asks per user per minute in a Redis sliding window that fails open and counts bypasses (`src/compliance_rag/api/limits.py:36-59`, `src/compliance_rag/settings.py:81`, `tests/integration/test_limits.py:32`, `:46`).
- Evals: `make eval-live` stops before the next question would pass `LIVE_EVAL_BUDGET_USD` (default 2.0) and refuses unpriced models (`scripts/eval_live.py:36-40`, `scripts/eval_live.py:53-73`, `scripts/eval_live.py:80-83`, `src/compliance_rag/settings.py:89`, `tests/unit/evals/test_budget.py:24`).
- Default mode is the FakeLLM, which costs 0.0 (`src/compliance_rag/llm/gateway.py:376-379`).
- Not done: the serving path has no spend ceiling per user or tenant, only the request rate. No live run exists, so there is no measured cost per answer; the 4,000 in and 2,000 out token figures in `scripts/eval_live.py:27` are assumptions.

## 13. Why are offline evals meaningful?

- They test the deterministic parts end to end against the seeded stack: ACL, validity, retrieval, fusion, reranking, verification and abstention are code, not model behaviour. The report says so itself (`evals/REPORT.md`, preface).
- Grading uses corpus ground truth, not the stores: ACL leakage checks retrieved, cited and listed documents plus the restricted id and span; stale citations use the true validity windows (`src/compliance_rag/evals/metrics.py:60-83`, `src/compliance_rag/evals/metrics.py:109-126`, `src/compliance_rag/evals/metrics.py:129-145`).
- Hard gates: `acl_leakage` and `hallucinated_citation_rate` must be 0; both are 0.000 over 120 and 95 cases. Other thresholds and a regression check against a baseline are in `evals/suites/rag.yaml` and `evals/REPORT.md` ("Gate").
- The checks can fail. `tests/unit/evals/test_metrics.py:37` shows the leak metric catches a leak; `tests/unit/graph/test_injection.py:48` shows the red-team fails when the context guard is removed, because the FakeLLM is deliberately injectable (`src/compliance_rag/llm/fake.py:3-6`); `tests/perf/test_injected_delay.py:28` shows the latency budgets fail when 400 ms is injected.
- Tuning used the dev split and reports use the test split (question 7); a metric with nothing to count has no value rather than 1.0 (`tests/unit/evals/test_metrics.py:181`).
- They are visible about weak spots: multi_hop has key-fact accuracy 0.625 and recall@10 0.812 (`evals/REPORT.md`, "By question category").
- What they do not show: live-model quality or faithfulness (no live run, Ragas not wired: `docs/KNOWN_LIMITATIONS.md`, `PROGRESS.md` "Needs the maintainer"); the FakeLLM answers by extracting sentences, so key-fact accuracy (0.886) measures that composer.
- Labels are by construction and unreviewed, 52 of 160 gold documents serve both splits, and ablation differences of one or two questions are noise (`docs/KNOWN_LIMITATIONS.md`, `evals/REPORT.md`).
- Latency in the report is one question at a time; throughput under load is `make bench` (`evals/reports/bench.json`).

## 14. What changes for multi-tenancy?

- Not implemented. This is a design answer: the system serves one fictional tenant, and nothing below exists in the code.
- Identity: add a verified `tenant_id` to `Principal` (`src/compliance_rag/retrieval/types.py:15-18`) and map it from a token claim in `src/compliance_rag/auth/jwt.py:122-129`. Roles and groups are fixed constants today (`src/compliance_rag/auth/personas.py:7-12`) and the groups are a `CHECK` list (`migrations/versions/0001_core.py:37`); per-tenant groups need a table.
- The filter is the single choke point: add a mandatory tenant term to the SQL, OpenSearch and Qdrant predicates and to `allows` in `src/compliance_rag/retrieval/filters.py:31-75`. Add `tenant_id` to `documents` and `chunks`, and Postgres row-level security as a second barrier.
- Indexes: index or alias per tenant for OpenSearch (`src/compliance_rag/retrieval/bm25.py:20`, `src/compliance_rag/retrieval/bm25.py:57-66`), a tenant payload index or collection for Qdrant (`src/compliance_rag/retrieval/vector/qdrant.py:36-44`).
- Statistics: BM25 IDF and the LSA fit are corpus-wide, which is today's side channel; across tenants it would be a leak. Fit and register one embedder per tenant (`src/compliance_rag/embed/registry.py:36-63`, which keeps a single `embedder` row).
- Storage and keys: tenant-prefixed raw keys and idempotency keys (`src/compliance_rag/ingest/pipeline.py:99-100`, `src/compliance_rag/ingest/pipeline.py:107`), tenant-scoped conversation threads (`src/compliance_rag/graph/build.py:582`), Redis keys (`src/compliance_rag/api/sse.py:100`, `src/compliance_rag/api/limits.py:41`) and retention.
- Audit and cost: one hash chain under one advisory lock (`src/compliance_rag/db/audit.py:18-78`) becomes a chain per tenant; rate limits and spend ceilings become per tenant.
- Evals: `corpus_truth` (`src/compliance_rag/evals/metrics.py:74-83`) needs a tenant dimension and a cross-tenant leakage hard gate, modelled on `tests/integration/test_vector_stores.py:142`.
- Unchanged: the graph, the citation verifier and the guards.

## 15. How would this scale to 1M chunks?

- Not implemented or measured. This is a design answer. The seeded corpus has 22,717 chunks and seeds in 112.5 s (`docs/DECISIONS.md`, "`crag seed` is a bulk loader"), so 1M chunks is about 44 times larger (arithmetic). The worst NFR-1 retrieval p95 at today's size is 130.9 ms against a 300 ms budget (`evals/reports/bench.json`, `nfr1_retrieval`). No extrapolation is attempted.
- pgvector: HNSW is built with `m = 16`, `ef_construction = 64` and searched with `ef_search = 100` (`migrations/versions/0001_core.py:51-52`, `src/compliance_rag/retrieval/vector/pgvector.py:49`, `src/compliance_rag/retrieval/vector/pgvector.py:84-85`). Raw float32 vectors at that size are about 1.5 GB (1,000,000 x 384 x 4 bytes) before graph overhead. Recall under selective ACL filters must be re-measured; options are partitioning by domain or group, quantisation, or the existing Qdrant store (`src/compliance_rag/retrieval/vector/qdrant.py`).
- OpenSearch: today one shard and no replicas (`deploy/opensearch/crag-chunks-v1.json:3-4`). It needs shards, replicas and lifecycle management. The merge-to-one-segment step used for reproducible BM25 statistics becomes expensive (`src/compliance_rag/retrieval/bm25.py:109-123`).
- Reranker cache: every API worker preloads all visible chunk vectors at start-up (`src/compliance_rag/rerank/feature.py:139-154`); it already costs about 2.2 GB for three workers (`docs/KNOWN_LIMITATIONS.md`, "API" rows) and the LRU is sized below 1M (`src/compliance_rag/rerank/feature.py:107`). Drop the preload and embed only the 50 candidates on demand (`src/compliance_rag/rerank/feature.py:121-137`); rerank cost stays bounded by `leg_k` (`src/compliance_rag/settings.py:69`, `src/compliance_rag/graph/build.py:293`).
- Embeddings: an LSA refit is a full-corpus job (60,000-term TF-IDF plus SVD, `src/compliance_rag/embed/lsa.py:18-26`) and `reindex` loads every row into memory (`src/compliance_rag/ingest/reindex.py:71-74`). Stream in batches, and use a pretrained embedder (question 8); switching is a re-embedding migration guarded by the fingerprint check.
- Ingestion: run more workers and parallelise the sequential index writes (`src/compliance_rag/ingest/pipeline.py:308-314`, `src/compliance_rag/worker/main.py:149-165`); the Postgres re-check stays cheap because it sees at most the candidate ids (`src/compliance_rag/retrieval/hybrid.py:146-167`).
- Evaluation: 300 labelled questions cannot show recall against 44 times more distractors; a larger labelled set, a split by document and a fresh bench run are needed first. The pg_prewarm warm-up (`migrations/versions/0004_prewarm.py`) grows with the table.
