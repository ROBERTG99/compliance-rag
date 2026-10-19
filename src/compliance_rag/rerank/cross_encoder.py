"""Optional cross-encoder reranker (sentence-transformers is not installed by default)."""

from __future__ import annotations

from datetime import date
from typing import Any

from compliance_rag.rerank.feature import FeatureReranker
from compliance_rag.retrieval.types import Candidate


class CrossEncoderReranker:
    name = "cross_encoder"

    def __init__(
        self, fallback: FeatureReranker, model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    ) -> None:
        self.fallback = fallback
        self.model_name = model
        self._model: Any | None = None
        try:  # pragma: no cover - optional dependency
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(model)
        except Exception:
            self._model = None

    def rerank(self, question: str, candidates: list[Candidate], as_of: date) -> list[Candidate]:
        if self._model is None:
            return self.fallback.rerank(question, candidates, as_of)
        scores = self._model.predict([(question, c["text"]) for c in candidates])  # pragma: no cover
        out = [{**c, "rerank": float(s)} for c, s in zip(candidates, scores, strict=True)]  # pragma: no cover
        return sorted(out, key=lambda c: -c["rerank"])  # type: ignore  # pragma: no cover
