"""Hybrid retrieval (FR-7): BM25 and vector legs run concurrently with per-leg timeouts.

One failed or slow leg degrades the answer (``degraded`` lists it); both failing raises
``RetrievalUnavailable``. Every fused hit is re-checked against the principal's filter; a hit that
should not exist is dropped and counted in ``crag_acl_postcheck_violations_total``.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt

from compliance_rag.obs.metrics import ACL_POSTCHECK_VIOLATIONS, RETRIEVAL_SECONDS
from compliance_rag.retrieval.filters import AccessFilter
from compliance_rag.retrieval.fusion import rrf_fuse
from compliance_rag.retrieval.types import Candidate, Principal


class RetrievalUnavailable(RuntimeError):
    """Both retrieval legs failed."""


class BM25Leg(Protocol):
    async def search(self, query: str, principal: Principal, as_of: date, k: int = 50) -> list[Candidate]: ...


class VectorLeg(Protocol):
    name: str

    async def search(
        self, embedding: npt.NDArray[np.float32], principal: Principal, as_of: date, k: int
    ) -> list[Candidate]: ...


class QueryEmbedder(Protocol):
    def embed_query(self, text: str) -> npt.NDArray[np.float32]: ...


@dataclass
class HybridResult:
    bm25_hits: list[Candidate]
    vector_hits: list[Candidate]
    fused: list[Candidate]
    degraded: list[str]
    timings_ms: dict[str, float] = field(default_factory=dict)
    violations: int = 0

    @property
    def n_bm25(self) -> int:
        return len(self.bm25_hits)

    @property
    def n_vector(self) -> int:
        return len(self.vector_hits)

    @property
    def n_fused(self) -> int:
        return len(self.fused)


class HybridRetriever:
    def __init__(
        self,
        bm25: BM25Leg | None,
        vector: VectorLeg | None,
        embedder: QueryEmbedder,
        rrf_k: int = 60,
        leg_k: int = 50,
        timeout_ms: int = 250,
    ) -> None:
        self.bm25 = bm25
        self.vector = vector
        self.embedder = embedder
        self.rrf_k = rrf_k
        self.leg_k = leg_k
        self.timeout_s = timeout_ms / 1000

    async def _timed(self, leg: str, coro: Any) -> tuple[list[Candidate], float]:
        started = time.perf_counter()
        try:
            hits: list[Candidate] = await asyncio.wait_for(coro, timeout=self.timeout_s)
        finally:
            elapsed = time.perf_counter() - started
            RETRIEVAL_SECONDS.labels(leg=leg).observe(elapsed)
        return hits, elapsed * 1000

    async def _vector_leg(self, query: str, principal: Principal, as_of: date) -> list[Candidate]:
        assert self.vector is not None
        embedding = self.embedder.embed_query(query)
        return await self.vector.search(embedding, principal, as_of, self.leg_k)

    async def retrieve(self, query: str, principal: Principal, as_of: date) -> HybridResult:
        flt = AccessFilter.for_principal(principal, as_of)  # validates the principal before any I/O
        legs: dict[str, Any] = {}
        if self.bm25 is not None:
            legs["bm25"] = self._timed("bm25", self.bm25.search(query, principal, as_of, self.leg_k))
        if self.vector is not None:
            legs["vector"] = self._timed("vector", self._vector_leg(query, principal, as_of))
        started = time.perf_counter()
        results = await asyncio.gather(*legs.values(), return_exceptions=True)
        out: dict[str, list[Candidate]] = {"bm25": [], "vector": []}
        timings: dict[str, float] = {}
        degraded: list[str] = []
        for name, res in zip(legs, results, strict=True):
            if isinstance(res, BaseException):
                degraded.append(name)
            else:
                out[name], timings[name] = res
        if len(degraded) == len(legs):
            raise RetrievalUnavailable(f"all retrieval legs failed: {', '.join(degraded)}")
        fusion_started = time.perf_counter()
        fused = rrf_fuse([out["bm25"], out["vector"]], k=self.rrf_k)
        allowed = [c for c in fused if flt.allows(c["acl_groups"], c["valid_from"], c["valid_to"])]
        violations = len(fused) - len(allowed)
        if violations:
            ACL_POSTCHECK_VIOLATIONS.inc(violations)
        timings["fusion"] = (time.perf_counter() - fusion_started) * 1000
        timings["legs"] = (fusion_started - started) * 1000
        return HybridResult(out["bm25"], out["vector"], allowed, sorted(degraded), timings, violations)
