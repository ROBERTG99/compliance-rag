"""The system under evaluation, wired to the real stores with the offline FakeLLM (or cassettes/live).

Used by the evalgate python target, the reranker fit (dev only) and the retrieval ablation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from compliance_rag.auth.personas import persona_principal
from compliance_rag.graph.build import GraphDeps, build_graph, run_graph
from compliance_rag.graph.respond import build_response
from compliance_rag.llm.gateway import Gateway
from compliance_rag.rerank import Reranker, create_reranker
from compliance_rag.retrieval.hybrid import HybridRetriever
from compliance_rag.runtime import Services, build_services
from compliance_rag.settings import Settings, get_settings


@dataclass
class System:
    services: Services
    retriever: HybridRetriever
    reranker: Reranker
    graph: Any
    settings: Settings

    async def close(self) -> None:
        await self.services.close()


class IdentityReranker:
    """Keeps the fused (RRF) order; used by the hybrid-without-rerank ablation."""

    name = "none"

    def rerank(self, question: str, candidates: list[Any], as_of: date) -> list[Any]:
        return [{**c, "rerank": 1.0} for c in candidates]


async def build_system(
    settings: Settings | None = None,
    *,
    bm25: bool = True,
    vector: bool = True,
    vector_store: str | None = None,
    rerank: bool = True,
    gateway: Gateway | None = None,
) -> System:
    settings = settings or get_settings()
    store = vector_store or settings.vector_store
    services = await build_services(settings, with_qdrant=store == "qdrant")
    vector_leg: Any = services.qdrant if store == "qdrant" else services.pg
    retriever = HybridRetriever(
        services.bm25 if bm25 else None,
        vector_leg if vector else None,
        services.embedder,
        rrf_k=settings.rrf_k,
        leg_k=settings.leg_k,
        timeout_ms=settings.leg_timeout_ms,
        authority=services.pg,  # as in the API: index hits are re-checked against Postgres
    )
    reranker: Reranker = (
        create_reranker(settings.reranker, embedder=services.embedder) if rerank else IdentityReranker()
    )
    graph = build_graph(
        GraphDeps(retriever, reranker, gateway or Gateway(settings), settings), InMemorySaver()
    )
    return System(services, retriever, reranker, graph, settings)


async def answer_row(system: System, row_input: dict[str, Any]) -> dict[str, Any]:
    """Run one eval question through the graph; returns the response plus the top-10 ranked chunks."""
    principal = persona_principal(row_input["persona"])  # every row names its persona and date
    started = time.perf_counter()
    state = await run_graph(
        system.graph,
        question=row_input["question"],
        principal=principal,
        as_of=row_input["as_of"],
    )
    response = build_response(state)
    ranked = state.get("reranked") or []
    retrieval_ms = sum(s["latency_ms"] for s in state["steps"] if s["node"] in {"retrieve", "fuse", "rerank"})
    return {
        **response,
        "retrieved": [
            {
                "chunk_id": c["chunk_id"],
                "document_id": c["document_id"],
                "version": c["version"],
                "text": c["text"],
                "valid_from": c["valid_from"],
                "valid_to": c["valid_to"],
                "rerank": c.get("rerank"),
                "acl_groups": c["acl_groups"],
            }
            for c in ranked[:10]
        ],
        "context_ids": [c["chunk_id"] for c in state.get("context") or []],
        "abstain_reason": state.get("abstain_reason"),
        "retrieval_ms": retrieval_ms,
        # what the run cost even when it abstained (the response hides cost on abstentions)
        "llm_cost_usd": float(state.get("cost_usd") or 0.0),
        "total_ms": (time.perf_counter() - started) * 1000,
        "steps": state["steps"],
    }
