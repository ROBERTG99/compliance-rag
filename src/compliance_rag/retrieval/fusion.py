"""Reciprocal Rank Fusion (k = CRAG_RRF_K, default 60)."""

from __future__ import annotations

from compliance_rag.retrieval.types import Candidate


def rrf_fuse(ranked_lists: list[list[Candidate]], k: int = 60) -> list[Candidate]:
    """Fuse ranked lists by ``sum(1 / (k + rank))`` (rank starts at 1); merges leg scores per chunk."""
    fused: dict[str, Candidate] = {}
    for ranked in ranked_lists:
        for rank, cand in enumerate(ranked, start=1):
            cid = cand["chunk_id"]
            if cid not in fused:
                fused[cid] = {**cand, "rrf": 0.0}
            entry = fused[cid]
            entry["rrf"] += 1.0 / (k + rank)
            for score_key in ("bm25", "cosine"):
                if cand.get(score_key) is not None and entry.get(score_key) is None:
                    entry[score_key] = cand[score_key]
    return sorted(fused.values(), key=lambda c: (-c["rrf"], c["chunk_id"]))
