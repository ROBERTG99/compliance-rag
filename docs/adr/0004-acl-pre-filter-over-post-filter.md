# 0004. ACL as a pre-filter inside every query, over post-filtering

## Status

Accepted

## Date

2026-10-16

## Context

Each document carries `acl_groups`; a principal may read a chunk only if the groups overlap, the chunk's
version is valid at `as_of` and the chunk is visible. Restricted text must never reach a prompt, a
citation, a log or a response, and a restricted topic must be indistinguishable from an unknown one
(`CLAUDE.md` conventions). Retrieval runs against three backends (Postgres, OpenSearch, Qdrant), each with
its own query language.

## Decision

The principal's filter is part of the query, never applied afterwards:

- One definition, `AccessFilter`, renders the predicate for every backend: SQL
  (`src/compliance_rag/retrieval/filters.py:31`), OpenSearch `bool.filter` (`filters.py:37-52`) and
  Qdrant `Filter` (`filters.py:55-66`). A principal without groups raises `PermissionError`
  (`filters.py:25-27`).
- Every search function takes a `Principal` and builds the filter itself
  (`retrieval/bm25.py:179`, `retrieval/vector/pgvector.py:80`, `retrieval/vector/qdrant.py:84`); no
  unfiltered search exists. `HybridRetriever.run_legs` validates the principal before any I/O
  (`retrieval/hybrid.py:117`).
- Defence in depth, counted: index hits are re-checked against Postgres, the authoritative copy
  (`hybrid.py:146-167`), and fused hits pass `AccessFilter.allows`; any violation is dropped and
  counted in `crag_acl_postcheck_violations_total` (`hybrid.py:169-181`).
- Unauthorized resources answer 404, and abstentions for restricted and unknown topics are
  byte-identical apart from `run_id` and timings (`src/compliance_rag/graph/respond.py:1`,
  `tests/unit/graph/test_graph.py::test_abstention_bodies_are_identical_for_different_causes`).

## Alternatives considered

- **Post-filter only (retrieve top k, then drop what the principal cannot read).** Rejected: a restricted
  chunk is then already in memory and one forgotten call site leaks it. With a selective ACL the filter
  can also empty the shortlist, so a legitimate answer is lost even though readable chunks exist. This
  is on the never-do list in `CLAUDE.md`.
- **Per-group indexes or collections.** Rejected: groups overlap and change at runtime (ACL updates), so
  documents would be duplicated across indexes and every revocation would touch several of them.
- **Check ACL only in the API layer.** Rejected: the retrieval, rerank and context-guard steps would
  already have processed restricted text, and the model would see it.

## Consequences

Positive:

- A restricted chunk cannot enter candidates, fusion, the reranker or the prompt. The hard gate
  `acl_leakage` is 0.000 over 120 test cases in both eval suites (`evals/REPORT.md` suites `rag` and
  `retrieval`), graded against corpus ground truth rather than the stores' own copies
  (`docs/DECISIONS.md`, 2026-10-17 row on eval ground truth).
- The filter is tested per backend, including random group assignments
  (`tests/integration/test_vector_stores.py::test_acl_filter_inside_query` and
  `::test_random_group_assignments_never_leak`, `tests/integration/test_bm25.py::test_restricted_chunk_never_returned`).

Negative:

- A selective predicate hurts approximate nearest-neighbour recall. pgvector uses iterative HNSW scans to
  compensate (`vector/pgvector.py:84`); there is no measurement here of the residual loss.
- The same rule is written three times (SQL, OpenSearch, Qdrant). The repo keeps one source file for all
  three and runs the same behavioural tests on both vector stores.
- Index copies of the ACL can lag a revocation. ACL changes commit together with their audit row, are
  pushed synchronously, and a minute-cron retries failed index updates
  (`src/compliance_rag/worker/main.py:123-129`, `docs/DECISIONS.md` 2026-10-16 row on synchronous ACL
  changes and 2026-10-17 row on index re-checks). Until the index catches up, the Postgres re-check
  drops the stale hit and counts it in `crag_stale_index_hits_total`; if the re-check itself fails, the
  index legs are dropped (fail closed, `hybrid.py:157-162`).
