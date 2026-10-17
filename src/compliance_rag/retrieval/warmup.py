"""Cache warm-up shared by the API (before readiness) and offline evals (before timing anything).

Cold, the first query per filter shape reads the HNSW index and BM25 segments from disk and exceeds the
250 ms leg budget on both legs; warm, legs take tens of milliseconds.
"""

from __future__ import annotations

import asyncio
import time
from datetime import date
from typing import Any

import structlog
from psycopg_pool import AsyncConnectionPool

from compliance_rag.auth.personas import PERSONAS, persona_principal
from compliance_rag.retrieval.hybrid import HybridRetriever

log = structlog.get_logger(__name__)
WARM_RELATIONS = ("chunks", "chunks_embedding_hnsw", "chunks_acl_gin", "chunks_validity")
WARM_QUERY = "What is the maximum age of a proof-of-address document?"


async def _warm_reranker(pool: AsyncConnectionPool, reranker: Any) -> int:
    """Preload the reranker's per-chunk caches from the visible chunks' stored embeddings and text."""
    async with pool.connection() as conn:
        rows = await (
            await conn.execute("SELECT chunk_id, section_path, text, embedding FROM chunks WHERE visible")
        ).fetchall()
    prepared = [
        (str(r[0]).strip(), r[1], r[2], r[3].to_numpy() if hasattr(r[3], "to_numpy") else r[3]) for r in rows
    ]
    return int(await asyncio.to_thread(reranker.warm, prepared))


async def warm_up(
    pool: AsyncConnectionPool,
    retriever: HybridRetriever | None,
    parallel: int = 1,
    reranker: Any | None = None,
) -> dict[str, Any]:
    """Best effort: ``pg_prewarm`` the chunk heap and indexes, then run each role's legs ``parallel`` times
    concurrently (so that many pool connections have served a query), then preload the reranker's per-chunk
    caches. Never raises."""
    started = time.perf_counter()
    blocks, errors = 0, []
    try:
        async with pool.connection() as conn:
            for rel in WARM_RELATIONS:
                row = await (await conn.execute("SELECT pg_prewarm(%s)", (rel,))).fetchone()
                blocks += int(row[0]) if row else 0
    except Exception as exc:
        errors.append(f"pg_prewarm: {type(exc).__name__}")
    roles = 0
    if retriever is not None:
        # one principal per role: the ACL filter differs by role, not by persona alias
        for persona in {role: name for name, (_, role) in PERSONAS.items()}.values():
            principal = persona_principal(persona)
            results = await asyncio.gather(
                *(retriever.warm(WARM_QUERY, principal, date.today()) for _ in range(max(1, parallel))),
                return_exceptions=True,
            )
            failed = [r for r in results if isinstance(r, BaseException)]
            if failed:
                errors.append(f"{persona}: {type(failed[0]).__name__}")
            else:
                roles += 1
    reranked = 0
    if reranker is not None and hasattr(reranker, "warm"):
        try:
            reranked = await _warm_reranker(pool, reranker)
        except Exception as exc:
            errors.append(f"reranker: {type(exc).__name__}")
    report = {
        "prewarmed_blocks": blocks,
        "roles": roles,
        "reranker_chunks": reranked,
        "errors": errors,
        "seconds": round(time.perf_counter() - started, 3),
    }
    log.info("warm_up", **report)
    return report
