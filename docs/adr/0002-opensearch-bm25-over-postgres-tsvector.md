# 0002. OpenSearch BM25 over Postgres tsvector for the lexical leg

## Status

Accepted

## Date

2026-10-16

## Context

Compliance questions are full of exact terms: product names, document codes such as `KYC-0042`, limits
and thresholds. A lexical leg complements the dense leg, which in offline mode is a small LSA embedding
(ADR 0006). The leg has to apply the same ACL, validity and visibility filter as every other backend
(`src/compliance_rag/retrieval/filters.py:1-5`) and meet the 250 ms leg budget
(`src/compliance_rag/settings.py:70`).

## Decision

The BM25 leg runs on OpenSearch (`src/compliance_rag/retrieval/bm25.py`, `BM25Index`). The index mapping
in `deploy/opensearch/crag-chunks-v1.json` sets BM25 similarity (`k1` 1.2, `b` 0.75) and the `english`
analyzer on `text`, `title` and `section_path`. The query is a `multi_match` over
`text`, `title^2` and `section_path^1.5` with the filters in the `bool.filter` clause
(`bm25.py:186-191`), built from `AccessFilter.opensearch()` (`filters.py:37-52`). Writes and updates go
through an alias, retry version conflicts and raise on failures (`bm25.py:222-238`).

## Alternatives considered

- **Postgres `tsvector` with `ts_rank`.** Rejected: it would remove a service, but `ts_rank` is not BM25.
  It has no inverse document frequency weighting of the BM25 kind and no length normalisation parameters,
  so the ranking signal the fusion step expects would be different in kind. The spec chose OpenSearch for
  "real BM25 analyzers" (`docs/specs/000-build-spec.md` §5 tech stack table). No `tsvector` variant was built
  or measured, so this ADR makes no quantitative claim against it.
- **BM25 inside the vector store only (Qdrant sparse vectors).** Rejected: it would tie the lexical leg
  to the optional vector store, which is not the default (ADR 0001).
- **Dense-only retrieval.** Rejected: in the ablation the BM25 leg alone reaches recall@10 0.812 and
  mrr@10 0.827, ahead of the pgvector leg alone at 0.756 and 0.681 (`evals/REPORT.md` "Retrieval
  ablation").

## Consequences

Positive:

- Real BM25 statistics and analyzers, and the lowest leg latency in the ablation (p95 19 ms against 59 ms
  for pgvector, `evals/REPORT.md` "Retrieval ablation").
- Independent failure domain: if OpenSearch is slow or down the dense leg still answers and the response
  lists `degraded: ["bm25"]` (`src/compliance_rag/retrieval/hybrid.py:124-139`,
  `tests/unit/retrieval/test_hybrid.py::test_leg_timeout_degrades_gracefully`).

Negative:

- A second copy of ACL, validity and visibility exists in the index and can lag Postgres. The repo
  treats Postgres as authoritative: every index hit is re-checked against it in one query per ask, drops
  are counted in `crag_stale_index_hits_total`, and if the check fails the index legs are dropped
  (`hybrid.py:146-167`, `docs/DECISIONS.md` 2026-10-17 row on index re-checks). ACL changes are applied
  synchronously and retried by a cron until the index confirms (`src/compliance_rag/worker/main.py:123-129`).
- Deleted documents still count in BM25 term statistics, so a reindex force-merges until no deleted
  copies remain (`bm25.py:109-123`, `docs/DECISIONS.md` 2026-10-16 row on the 60 s client timeout).
- More operational weight (JVM heap, disk watermarks, mapping migrations). The strict mapping is
  extended in place by `crag search init` (`bm25.py:92-95`).
