"""Reranker caches (performance, T-46): identical scores, and embeddings never shared across embedders."""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np

from compliance_rag.rerank import feature
from compliance_rag.rerank.feature import FeatureReranker, extract_features
from compliance_rag.retrieval.types import make_candidate

AS_OF = date(2026, 10, 16)
TEXT = (
    "Article 5 — Controls\n\nThe daily spending limit on the Orion Prepaid Card is EUR 1,000. "
    "Staff record each decision in the case management system."
)


def _cand(cid: str, cosine: float | None = None) -> Any:
    return make_candidate(
        chunk_id=cid * 32,
        document_id="LIM-0007",
        version=2,
        text=TEXT,
        acl_groups=["all"],
        valid_from="2025-01-01",
        valid_to=None,
        bm25=4.0,
        cosine=cosine,
        title="Daily Spending Limits Policy — Orion Prepaid Card",
        section_path="Article 5 — Controls",
    )


def test_cached_features_equal_a_cold_computation() -> None:
    q = "What is the daily spending limit on the Orion Prepaid Card?"
    feature.sentence_terms.cache_clear()
    cold = extract_features(q, [_cand("a", 0.5)], AS_OF)
    warm = extract_features(q, [_cand("a", 0.5)], AS_OF)
    assert cold == warm and feature.sentence_terms.cache_info().hits >= 1


class CountingEmbedder:
    def __init__(self, name: str, scale: float) -> None:
        self.name, self.scale, self.calls = name, scale, 0

    def fingerprint(self) -> str:
        return self.name

    def embed_query(self, text: str) -> np.ndarray:
        return np.ones(4, dtype=np.float32) / 2

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        self.calls += len(texts)
        return np.full((len(texts), 4), self.scale / 2, dtype=np.float32)


def test_document_embeddings_are_cached_per_embedder_fingerprint() -> None:
    first = CountingEmbedder("lsa-A", 1.0)
    reranker = FeatureReranker(embedder=first)
    a = reranker.rerank("q", [_cand("a")], AS_OF)
    b = reranker.rerank("q", [_cand("a")], AS_OF)
    assert first.calls == 1 and a[0]["cosine"] == b[0]["cosine"] == 1.0
    other = CountingEmbedder("lsa-B", 0.5)  # a refitted embedder must not see the old vectors
    reranker.embedder = other
    c = reranker.rerank("q", [_cand("a")], AS_OF)
    assert other.calls == 1 and c[0]["cosine"] == 0.5


def test_warm_preloads_stored_vectors_so_queries_embed_nothing() -> None:
    embedder = CountingEmbedder("lsa-A", 1.0)
    reranker = FeatureReranker(embedder=embedder)
    cold = FeatureReranker(embedder=CountingEmbedder("lsa-A", 1.0)).rerank("q", [_cand("a")], AS_OF)
    stored = np.full(4, 0.5, dtype=np.float32)  # what the pipeline stored for this chunk
    loaded = reranker.warm([("a" * 32, "Article 5 — Controls", TEXT, stored)])
    assert loaded == 1
    warm = reranker.rerank("q", [_cand("a")], AS_OF)
    assert embedder.calls == 0 and warm[0]["rerank"] == cold[0]["rerank"]
