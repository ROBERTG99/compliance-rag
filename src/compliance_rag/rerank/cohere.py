"""Cohere Rerank v3.5 on Amazon Bedrock; any error falls back to the FeatureReranker."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from compliance_rag.rerank.feature import FeatureReranker
from compliance_rag.retrieval.types import Candidate


class CohereRerankBedrock:
    name = "cohere"

    def __init__(self, client: Any, model_id: str, fallback: FeatureReranker) -> None:
        self.client = client
        self.model_id = model_id
        self.fallback = fallback
        self.last_fallback = False

    def rerank(self, question: str, candidates: list[Candidate], as_of: date) -> list[Candidate]:
        if not candidates:
            return []
        try:
            body = json.dumps(
                {
                    "query": question,
                    "documents": [c["text"] for c in candidates],
                    "top_n": len(candidates),
                    "api_version": 2,
                }
            )
            resp = self.client.invoke_model(
                modelId=self.model_id, body=body, contentType="application/json", accept="application/json"
            )
            results = json.loads(resp["body"].read())["results"]
            out: list[Candidate] = []
            for r in results:
                c = Candidate(**candidates[int(r["index"])])
                c["rerank"] = float(r["relevance_score"])
                out.append(c)
            self.last_fallback = False
            return out
        except Exception:
            self.last_fallback = True
            return self.fallback.rerank(question, candidates, as_of)
