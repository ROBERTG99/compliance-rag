# Known limitations

Gaps that are known and accepted for v0.1.0. Each entry says why and what would fix it.

| Area | Limitation | Why / mitigation |
|---|---|---|
| Evals | Dev/test split is stratified by question, not by document: 52 of the 160 gold documents serve both dev and test questions. | `questions.v1.jsonl` is append-only; the reranker uses document-agnostic features and τ is a single scalar, so the leakage surface is small. A `questions.v2.jsonl` split by document is the fix. |
| Evals | Labels are by construction; no human review yet. | "Maintainer review of 40 questions" is listed in `PROGRESS.md` → Needs the maintainer. |
| Audit | Removing the newest audit rows (tail truncation by a superuser) is not detectable from the chain alone. | Row and statement triggers block UPDATE/DELETE/TRUNCATE for the app; anchoring the latest hash externally (logs or a WORM store) would close it. |
| Providers | Titan and OpenAI embedding fixtures are synthetic, following the documented response shapes. | No provider keys in the build environment; `make record-fixtures` re-records them. |
| Dependencies | `langchain-community` is being sunset upstream; its loaders are kept because FR-2 names them. | Migrate to standalone loader packages when they cover PDF/DOCX/HTML. |
| Packaging | The corpus generator ships as a top-level `data` package in the wheel. | Only the API image installs it (for `crag seed`); rename to `compliance_rag_data` before publishing a wheel. |
| Harness | The pre-tool guard cannot see dataset writes made from inside a program (for example `python -c "open(...,'a')"`). | `tests/unit/data/test_questions.py` fails if the committed datasets drift from the generator. |
| Harness | Claude Code deny rules win over allow rules, so `Read(.env.example)` is blocked by `Read(.env.*)`. | Kept for safety; `.env.example` is readable with shell tools and documented in README. |
| Retrieval | With cold caches, both legs can exceed the 250 ms leg budget and the ask returns 503 `retrieval_unavailable` (`retryable: true`). Observed on the dev stack after a restart: first pgvector query ≈ 2.1 s and first BM25 query ≈ 150–250 ms for a new filter shape. | The API warms up before serving (`pg_prewarm` of the chunk heap and indexes, one retrieval per role; ≈ 2.8 s, 13,647 blocks on the seeded stack, from the `warm_up` log line). Page-cache eviction under memory pressure can still make a first query slow; clients retry on `retryable`. |
| Tests | Schemathesis runs every operation as `content_admin` only; non-admin authorisation is covered by targeted tests (`test_every_v1_operation_requires_a_token`, admin 403s, 404 ownership tests), not fuzzed. | A second parametrised run per role would double the contract suite's time. |
| Tests | Several integration tests mutate the session-scoped `api_env` (AML-0107 extra versions, KYC-0042 ACL changed and restored in `finally`), so ordering matters in principle. | Mutations are additive or restored; the demo test uses its own environment. A per-module environment would cost a seed per module. |
| Streaming | If Redis fails mid-run while a client is behind, events between the client's cursor and the last sequence written to Redis exist only in Redis and are skipped; numbering continues in memory and `final` (authoritative) still arrives. | §4.7 accepts no resume while Redis is down; copying the Redis tail into memory on failure is impossible once Redis is unreachable. |
| Web | The evidence viewer shows the cited chunk (with its section and validity), not the whole version text at 72ch; “Current version vN” links to the document timeline. | The API serves chunks (`GET /v1/chunks/{id}`), not assembled version text; a version-text endpoint would be needed. |
| Web | The citation quote travels in the evidence URL (`?quote=`), so it can appear in browser history. | nginx has `access_log off` and `Referrer-Policy: no-referrer`; router state or a claim lookup would avoid it. |
| Web | The jobs screen shows the latest 200 jobs with no “Load more”. | The API caps `limit` at 500; paging can follow the library's cursor pattern. |
