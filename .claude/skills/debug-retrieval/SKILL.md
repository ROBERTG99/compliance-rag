---
name: debug-retrieval
description: 'Explain retrieval for one question: per-leg hits, filter clauses, RRF ranks and per-feature rerank scores.'
---

# Debug retrieval

Run against the stack:

```bash
uv run crag debug-retrieval "What is the maximum age of a proof-of-address document?" --persona analyst --as-of 2026-10-16
```

It prints:
- the principal and the exact filter clauses sent to OpenSearch, pgvector (SQL) and Qdrant;
- BM25 and vector hits with scores and ranks;
- RRF ranks and fused scores;
- the FeatureReranker feature vector (bm25, cosine, jaccard, heading match, freshness) and final probability per candidate;
- whether the top score clears `CRAG_ABSTAIN_TAU`.

Use it on dev questions only when tuning.
