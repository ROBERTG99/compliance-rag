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


async def warm_up(
    pool: AsyncConnectionPool, retriever: HybridRetriever | None, parallel: int = 1
) -> dict[str, Any]:
    """Best effort: ``pg_prewarm`` the chunk heap and indexes, then run each role's legs ``parallel`` times
    concurrently (so that many pool connections have served a query). Never raises."""
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
    report = {
        "prewarmed_blocks": blocks,
        "roles": roles,
        "errors": errors,
        "seconds": round(time.perf_counter() - started, 3),
    }
    log.info("warm_up", **report)
    return report
