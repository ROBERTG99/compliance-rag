"""evalgate targets: the full RAG graph and retrieval only, wired to the running stores.

Each describes its provenance (LLM, model ids, prompt and weight hashes) so reports say exactly what
produced the numbers; offline runs are labelled FakeLLM-produced.
"""

from __future__ import annotations

import hashlib
import time
from datetime import date
from pathlib import Path
from typing import Any

from compliance_rag.auth.personas import persona_principal
from compliance_rag.evals.system import System, answer_row, build_system
from compliance_rag.retrieval.warmup import warm_up
from compliance_rag.settings import Settings, get_settings

ROOT = Path(__file__).resolve().parents[3]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def provenance(settings: Settings, system: System | None) -> dict[str, Any]:
    live = settings.llm_provider != "fake"
    prompts = sorted((settings.root / "prompts").glob("*.md"))
    weights = settings.root / "src" / "compliance_rag" / "rerank" / "feature_weights.json"
    info: dict[str, Any] = {
        "llm": f"{settings.llm_provider} ({settings.model_generate})" if live else "FakeLLM (offline)",
        "models": f"generate={settings.model_generate}, condense={settings.model_fast}, judge={settings.model_judge}"
        if live
        else "none (deterministic FakeLLM)",
        "prompts": ", ".join(f"{p.name}={_sha(p)}" for p in prompts),
        "reranker": settings.reranker + (f" weights={_sha(weights)}" if weights.exists() else ""),
        "vector_store": settings.vector_store,
    }
    if system is not None:
        info["embedder"] = system.services.embedder.fingerprint()
    return info


class _Base:
    def __init__(self, settings: Settings | None = None, **system: Any) -> None:
        self.settings = settings or get_settings()
        self.system_options = system  # build_system flags: bm25, vector, vector_store, rerank (ablation)
        self.system: System | None = None

    async def setup(self) -> None:
        self.system = await build_system(self.settings, **self.system_options)
        # timings are steady-state: warm the caches the way the API does before it reports ready
        await warm_up(self.system.services.pool, self.system.retriever, parallel=8)

    async def close(self) -> None:
        if self.system is not None:
            await self.system.close()

    def describe(self) -> dict[str, Any]:
        info = provenance(self.settings, self.system)
        if self.system_options:
            info["configuration"] = ", ".join(f"{k}={v}" for k, v in self.system_options.items())
            if "vector_store" in self.system_options:
                info["vector_store"] = self.system_options["vector_store"]
            if self.system_options.get("rerank") is False:
                info["reranker"] = "none (RRF order)"
        return info


class RagTarget(_Base):
    """The whole graph; also re-fetches cited chunks from Postgres for the hallucination check."""

    async def __call__(self, row: dict[str, Any]) -> dict[str, Any]:
        assert self.system is not None
        output = await answer_row(self.system, row["input"])
        ids = sorted({c["chunk_id"] for claim in output.get("claims", []) for c in claim["citations"]})
        output["cited_texts"] = await self._chunk_texts(ids)
        return output

    async def _chunk_texts(self, ids: list[str]) -> dict[str, str]:
        if not ids:
            return {}
        assert self.system is not None
        async with self.system.services.pool.connection() as conn:
            rows = await (
                await conn.execute("SELECT chunk_id, text FROM chunks WHERE chunk_id = ANY(%s)", (ids,))
            ).fetchall()
        return {str(r[0]): str(r[1]) for r in rows}


class RetrievalTarget(_Base):
    """Retrieval, fusion and reranking only (no generation): recall, MRR and latency."""

    async def __call__(self, row: dict[str, Any]) -> dict[str, Any]:
        assert self.system is not None
        inp = row["input"]
        principal = persona_principal(inp.get("persona", "analyst"))
        as_of = date.fromisoformat(inp.get("as_of") or date.today().isoformat())
        started = time.perf_counter()
        result = await self.system.retriever.retrieve(inp["question"], principal, as_of)
        # same cut as the graph's rerank node: only the top leg_k fused candidates are reranked
        top = list(result.fused)[: self.settings.leg_k]
        ranked = self.system.reranker.rerank(inp["question"], top, as_of)
        elapsed = (time.perf_counter() - started) * 1000
        return {
            "retrieved": [
                {k: c.get(k) for k in ("chunk_id", "document_id", "version", "text", "acl_groups", "rerank")}
                for c in ranked[:10]
            ],
            "retrieval_ms": elapsed,
            "degraded": result.degraded,
        }
