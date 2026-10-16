---
name: run-ablation
description: 'Run the five-configuration retrieval ablation and update the report table.'
---

# Run the ablation

1. `make up` and `docker compose --profile qdrant up -d --wait qdrant`.
2. `make eval-ablation` runs BM25, vector-pgvector, vector-qdrant, hybrid and hybrid+rerank on the test split and writes recall@10, MRR@10 and p95 into `evals/reports/ablation.json` and the `evals/REPORT.md` table.
3. Compare with the previous table; explain any regression in `docs/evaluation.md`.
