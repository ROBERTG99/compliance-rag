# 0001. pgvector as the default vector store, over Qdrant or Pinecone

## Status

Accepted

## Date

2026-10-16

## Context

The vector leg of hybrid retrieval needs approximate nearest-neighbour search over 384-dimension chunk
embeddings, and every query must carry the principal's ACL, validity window and visibility
(`docs/specs/000-build-spec.md` FR-5). Postgres is already the source of truth for documents, versions,
ACL and chunks, and the system must run with zero outbound network offline (NFR-9). Index copies in other
stores can lag behind a revocation, which is the failure that matters most for a compliance assistant.

## Decision

Postgres 16 with the `vector` extension is the default store (`CRAG_VECTOR_STORE=pgvector`,
`src/compliance_rag/settings.py:55`). Embeddings live in the `chunks` table next to `acl_groups`,
`valid_from`, `valid_to` and `visible`, with an HNSW cosine index and a GIN index on the ACL array
(`migrations/versions/0001_core.py:51-53`). The search statement embeds the shared predicate
`AccessFilter.SQL` in its `WHERE` clause (`src/compliance_rag/retrieval/vector/pgvector.py:15-30`) and
turns on `hnsw.iterative_scan` so a selective ACL does not starve the result list
(`vector/pgvector.py:84`). `QdrantStore` implements the same `VectorStore`
protocol behind compose profile `qdrant` and is selectable with `CRAG_VECTOR_STORE=qdrant`
(`vector/qdrant.py:20`); `make reindex` rebuilds it from Postgres.

## Alternatives considered

- **Qdrant as the default.** Rejected as default: it holds a second copy of ACL, validity and visibility
  that must be kept in sync through payload updates (`vector/qdrant.py:123-147`), so a revocation can be
  stale in the index for a while. It is kept as a supported alternative to prove the abstraction.
- **Pinecone (hosted vector database).** Rejected: a hosted service cannot run in the offline,
  no-API-key default (NFR-9), and would add a second ACL copy outside the deployment boundary. No adapter
  exists and none was benchmarked.
- **No vector store (BM25 only).** Rejected: the ablation shows the vector leg adds recall when fused
  (hybrid 0.830 against bm25 0.812 recall@10, `evals/REPORT.md` "Retrieval ablation").

## Consequences

Positive:

- One transactional store: ACL change, validity change and embedding live in the same row, so the
  authority for "may this principal read this chunk" is a single SQL predicate. The same predicate is
  reused to re-check hits from index copies (`vector/pgvector.py:32`, `retrieval/hybrid.py:146-167`).
- Parity with Qdrant on this corpus: both reach recall@10 0.756 and mrr@10 0.681 in the ablation, with
  p95 of 59 ms (pgvector) and 36 ms (Qdrant) (`evals/REPORT.md` "Retrieval ablation", single run on one
  dev machine).
- No extra service in the default stack.

Negative:

- Vector search shares CPU and buffer cache with transactional work, and the ablation latency favours
  Qdrant in that single run. The repo does not claim a scale ceiling: no corpus larger than the seeded
  one was measured.
- Cold caches are slow (first pgvector query about 2.1 s, `docs/KNOWN_LIMITATIONS.md` Retrieval row);
  the API warms up with `pg_prewarm` before it reports ready (`docs/DECISIONS.md`, 2026-10-17 row on
  warm-up).
- HNSW with a selective predicate can lose recall; iterative scans mitigate it, and
  `tests/integration/test_vector_stores.py::test_random_group_assignments_never_leak` guards the ACL side
  for both stores.
