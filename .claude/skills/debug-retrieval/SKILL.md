---
name: debug-retrieval
description: 'Find where retrieval goes wrong for eval questions: per-case results, per-stage fingerprints, HNSW against exact search.'
---

# Debug retrieval

There is no single-question debug command; use these against the running stack (`make up`), with
`OPENBLAS_CORETYPE=Haswell` exported (the Makefile does it for `make` targets).

1. Per-case results: `make eval` writes `evals/reports/runs/rag.json` and `retrieval.json` (test split); each
   case has its `scores` (`null` where a metric does not apply) and `output.retrieved`, the top 10 with rerank
   scores. Use them to count and compare runs, not to tune. Cases below full reciprocal rank:

   ```bash
   python3 -c "import json; c=json.load(open('evals/reports/runs/retrieval.json'))['cases']; print([x['id'] for x in c if (x['scores'].get('mrr@10') is not None) and x['scores']['mrr@10'] < 1])"
   ```

2. Which stage differs between two machines or two seeds:
   `uv run python scripts/retrieval_fingerprints.py > a.txt` on each, then compare the lines per stage
   (embedding, bm25, vector, fused, rerank); the first stage that differs is where to look.
3. Whether HNSW loses hits: `uv run python scripts/vector_recall.py` compares the configured pgvector query
   with exact search for every eval question.
4. One question by hand: `build_system()` from `compliance_rag.evals.system`, then
   `await system.retriever.retrieve(question, persona_principal(persona), as_of)` gives `bm25_hits`,
   `vector_hits`, `fused` (with `rrf`) and `degraded`; `system.reranker.rerank(question, fused[:50], as_of)`
   adds `rerank`. Compare the top score with `CRAG_ABSTAIN_TAU`.

Look at dev questions only; test-split cases may be counted, never inspected to tune anything.
