"""Hybrid retrieval: concurrent legs, timeouts, RRF fusion, ACL post-check (FR-7, T-20)."""

from __future__ import annotations

import asyncio
from datetime import date

import numpy as np
import pytest

from compliance_rag.obs.metrics import ACL_POSTCHECK_VIOLATIONS
from compliance_rag.retrieval.fusion import rrf_fuse
from compliance_rag.retrieval.hybrid import HybridRetriever, RetrievalUnavailable
from compliance_rag.retrieval.types import Candidate, Principal, make_candidate

SUPPORT: Principal = {"sub": "s", "role": "support", "groups": ["support", "all"]}
AS_OF = date(2026, 10, 16)


def cand(
    cid: str, *, bm25: float | None = None, cosine: float | None = None, groups: list[str] | None = None
) -> Candidate:
    return make_candidate(
        chunk_id=cid,
        document_id="KYC-0001",
        version=1,
        text=f"text {cid}",
        acl_groups=groups or ["all"],
        valid_from="2025-01-01",
        valid_to=None,
        bm25=bm25,
        cosine=cosine,
    )


class FakeBM25:
    def __init__(self, hits: list[Candidate], delay: float = 0.0, fail: bool = False) -> None:
        self.hits, self.delay, self.fail = hits, delay, fail

    async def search(self, query: str, principal: Principal, as_of: date, k: int = 50) -> list[Candidate]:
        await asyncio.sleep(self.delay)
        if self.fail:
            raise ConnectionError("opensearch down")
        return self.hits[:k]


class FakeVector:
    name = "pgvector"

    def __init__(self, hits: list[Candidate], delay: float = 0.0, fail: bool = False) -> None:
        self.hits, self.delay, self.fail = hits, delay, fail

    async def search(
        self, embedding: np.ndarray, principal: Principal, as_of: date, k: int
    ) -> list[Candidate]:
        await asyncio.sleep(self.delay)
        if self.fail:
            raise ConnectionError("postgres down")
        return self.hits[:k]


class FakeEmbedder:
    def embed_query(self, text: str) -> np.ndarray:
        return np.ones(4, dtype=np.float32)


def retriever(bm25: FakeBM25, vector: FakeVector, timeout_ms: int = 250) -> HybridRetriever:
    return HybridRetriever(
        bm25=bm25, vector=vector, embedder=FakeEmbedder(), rrf_k=60, leg_k=50, timeout_ms=timeout_ms
    )


async def test_leg_timeout_degrades_gracefully() -> None:
    r = retriever(
        FakeBM25([cand("a", bm25=3.0)], delay=1.0), FakeVector([cand("b", cosine=0.9), cand("c", cosine=0.8)])
    )
    result = await r.retrieve("question", SUPPORT, AS_OF)
    assert result.degraded == ["bm25"]
    assert [c["chunk_id"] for c in result.fused] == ["b", "c"]
    assert result.n_bm25 == 0 and result.n_vector == 2


async def test_vector_failure_degrades() -> None:
    r = retriever(FakeBM25([cand("a", bm25=3.0)]), FakeVector([], fail=True))
    result = await r.retrieve("q", SUPPORT, AS_OF)
    assert result.degraded == ["vector"] and [c["chunk_id"] for c in result.fused] == ["a"]


async def test_both_legs_down_raises() -> None:
    r = retriever(FakeBM25([], fail=True), FakeVector([], delay=1.0))
    with pytest.raises(RetrievalUnavailable):
        await r.retrieve("q", SUPPORT, AS_OF)


def test_rrf_fusion_math_and_merge() -> None:
    bm25 = [cand("a", bm25=9.0), cand("b", bm25=5.0)]
    vec = [cand("b", cosine=0.9), cand("c", cosine=0.5)]
    fused = rrf_fuse([bm25, vec], k=60)
    assert [c["chunk_id"] for c in fused] == ["b", "a", "c"]
    b = fused[0]
    assert b["rrf"] == pytest.approx(1 / 62 + 1 / 61)
    assert b["bm25"] == 5.0 and b["cosine"] == 0.9


def test_rrf_ties_are_deterministic() -> None:
    fused = rrf_fuse([[cand("z")], [cand("y")]], k=60)
    assert [c["chunk_id"] for c in fused] == ["y", "z"]


async def test_postcheck_drops_and_counts_violations() -> None:
    before = ACL_POSTCHECK_VIOLATIONS._value.get()
    leaked = cand("leak", bm25=10.0, groups=["legal"])
    r = retriever(FakeBM25([leaked, cand("ok", bm25=1.0)]), FakeVector([]))
    result = await r.retrieve("q", SUPPORT, AS_OF)
    assert [c["chunk_id"] for c in result.fused] == ["ok"]
    assert ACL_POSTCHECK_VIOLATIONS._value.get() == before + 1


async def test_zero_query_embedding_skips_vector_leg() -> None:
    """An all-OOV question embeds to the zero vector; pgvector's cosine distance would be NaN."""

    class ZeroEmbedder:
        def embed_query(self, text: str) -> np.ndarray:
            return np.zeros(4, dtype=np.float32)

    vector = FakeVector([cand("b", cosine=float("nan"))])
    r = HybridRetriever(
        bm25=FakeBM25([cand("a", bm25=3.0)]),
        vector=vector,
        embedder=ZeroEmbedder(),
        rrf_k=60,
        leg_k=50,
        timeout_ms=250,
    )
    result = await r.retrieve("cafeteria menu", SUPPORT, AS_OF)
    assert [c["chunk_id"] for c in result.fused] == ["a"]
    assert result.degraded == [] and result.n_vector == 0
