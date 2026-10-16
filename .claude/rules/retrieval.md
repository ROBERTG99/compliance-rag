---
paths: ["src/compliance_rag/retrieval/**", "src/compliance_rag/rerank/**", "src/compliance_rag/graph/**"]
---
# Retrieval

- Every retrieval query takes a `Principal`; no unfiltered search function exists.
- The ACL (`acl_groups` overlap), validity at `as_of` and `visible` filters live inside the query for every backend (SQL `WHERE`, OpenSearch `filter`, Qdrant `Filter`), built from `retrieval/filters.py`.
- Legs run concurrently with `CRAG_LEG_TIMEOUT_MS`; one failed leg degrades, both raise `RetrievalUnavailable`.
- Fusion is RRF with `CRAG_RRF_K`; reranker weights are fitted on dev only.
