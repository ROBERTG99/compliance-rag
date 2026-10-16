"""Rerankers: FeatureReranker (default), Cohere Rerank on Bedrock, optional cross-encoder."""

from __future__ import annotations

from datetime import date
from typing import Any, Protocol

from compliance_rag.rerank.feature import FeatureReranker, FeatureWeights
from compliance_rag.retrieval.types import Candidate


class Reranker(Protocol):
    name: str

    def rerank(self, question: str, candidates: list[Candidate], as_of: date) -> list[Candidate]: ...


def create_reranker(
    name: str, embedder: Any | None = None, model_id: str = "cohere.rerank-v3-5:0"
) -> Reranker:
    feature = FeatureReranker(FeatureWeights.load(), embedder=embedder)
    if name == "feature":
        return feature
    if name == "cohere":
        from compliance_rag.llm.gateway import bedrock_runtime_client
        from compliance_rag.rerank.cohere import CohereRerankBedrock

        return CohereRerankBedrock(bedrock_runtime_client(), model_id, feature)
    if name == "cross_encoder":
        from compliance_rag.rerank.cross_encoder import CrossEncoderReranker

        return CrossEncoderReranker(feature)
    raise ValueError(f"unknown reranker {name!r}")
