# 0003. Reciprocal Rank Fusion over weighted score fusion

## Status

Accepted

## Date

2026-10-16

## Context

The two legs return scores on unrelated scales: OpenSearch BM25 scores are unbounded and depend on corpus
statistics, pgvector returns cosine similarity in a narrow band (`bm25.py:212` and
`vector/pgvector.py:101` both store them in the candidate). The fused list feeds a reranker and a
sufficiency check, and either leg can be missing when it fails or times out (`hybrid.py:124-139`).

## Decision

Fuse the two ranked lists with Reciprocal Rank Fusion: each chunk scores `sum(1 / (k + rank))` over the
legs it appears in, with `k = CRAG_RRF_K = 60` (`src/compliance_rag/retrieval/fusion.py:8-21`,
`src/compliance_rag/settings.py:67`). Ties break on `chunk_id`, so the order is deterministic
(`fusion.py:21`, `tests/unit/retrieval/test_hybrid.py::test_rrf_ties_are_deterministic`). The raw BM25
and cosine scores are carried along on the fused candidate (`fusion.py:18-20`) as features for the
reranker, not as fusion weights. The top `leg_k` fused candidates (50) go to the reranker
(`src/compliance_rag/graph/build.py:293`).

## Alternatives considered

- **Weighted sum of normalised scores** (`w * bm25_norm + (1 - w) * cosine`). Rejected: it needs a
  normalisation scheme for unbounded BM25 scores and a tuned weight `w`, and the result shifts whenever
  the corpus statistics change. With one leg missing the combined score changes meaning. No weighted
  variant was implemented or measured here, so this rejection is by design reasoning, not by a
  benchmark.
- **Using only the reranker on the union of hits.** Rejected: the reranker is the expensive, tuned stage
  and works on a bounded candidate list (50); fusion gives it a rank-based, deterministic shortlist.
- **A learned fusion model.** Rejected: more moving parts for a corpus this size, and tuning is limited
  to the dev split (`.claude/rules/evals.md`).

## Consequences

Positive:

- No score normalisation or fusion weight to tune; a degraded run with one leg still produces a sensible
  order (`tests/unit/retrieval/test_hybrid.py::test_vector_failure_degrades`).
- Fusion is cheap and testable by hand
  (`tests/unit/retrieval/test_hybrid.py::test_rrf_fusion_math_and_merge`).
- Hybrid improves recall over either leg alone: recall@10 0.830 against 0.812 (BM25) and 0.756 (vector),
  `evals/REPORT.md` "Retrieval ablation" (differences of one or two questions out of 88 are within noise,
  as that report says).

Negative:

- Rank-only fusion discards score magnitude. In the same ablation, hybrid mrr@10 is 0.763 while BM25
  alone is 0.825, so fusion without reranking does not improve ranking quality on this corpus. The
  reranker closes the gap: hybrid+rerank reaches recall@10 0.920 and mrr@10 0.943
  (`evals/REPORT.md` "Retrieval ablation").
- The `k = 60` constant is a default, not tuned on this corpus; it is a setting
  (`CRAG_RRF_K`) if a later ablation justifies another value.
- Fusion alone is not an abstention signal; that decision uses the reranker score against
  `CRAG_ABSTAIN_TAU` (`graph/build.py:317-333`).
