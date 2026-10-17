"""Everything the API process holds: services, graph, checkpointer, event store, token validator."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import structlog
from arq import ArqRedis
from arq import create_pool as create_arq_pool
from arq.connections import RedisSettings
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from redis.asyncio import Redis

from compliance_rag.api.limits import RateLimiter
from compliance_rag.api.sse import RunEvents
from compliance_rag.auth.jwt import JWKSCache, TokenValidator
from compliance_rag.auth.personas import PERSONAS, persona_principal
from compliance_rag.graph.build import GraphDeps, build_graph
from compliance_rag.llm.gateway import Gateway
from compliance_rag.rerank import create_reranker
from compliance_rag.retrieval.hybrid import HybridRetriever
from compliance_rag.runtime import Services, build_services
from compliance_rag.settings import Settings

log = structlog.get_logger(__name__)
WARM_RELATIONS = ("chunks", "chunks_embedding_hnsw", "chunks_acl_gin", "chunks_validity")
WARM_QUERY = "What is the maximum age of a proof-of-address document?"


@dataclass
class AppState:
    settings: Settings
    services: Services
    gateway: Gateway
    validator: TokenValidator
    events: RunEvents
    redis: Redis | None
    checkpoint_pool: AsyncConnectionPool
    checkpointer: AsyncPostgresSaver
    limiter: RateLimiter = field(default_factory=lambda: RateLimiter(None, 30))
    arq: ArqRedis | None = None
    graph: Any = None
    retriever: HybridRetriever | None = None
    background: set[asyncio.Task[Any]] = field(default_factory=set)

    def build_graph(self) -> None:
        s = self.services
        vector: Any = s.qdrant if self.settings.vector_store == "qdrant" and s.qdrant is not None else s.pg
        retriever = HybridRetriever(
            s.bm25,
            vector,
            s.embedder,
            rrf_k=self.settings.rrf_k,
            leg_k=self.settings.leg_k,
            timeout_ms=self.settings.leg_timeout_ms,
        )
        self.retriever = retriever
        reranker = create_reranker(self.settings.reranker, embedder=s.embedder)
        self.graph = build_graph(
            GraphDeps(retriever, reranker, self.gateway, self.settings), self.checkpointer
        )

    async def reload(self) -> None:
        """Reload the embedder (after seeding/reindexing) and rebuild the graph."""
        await self.services.reload_embedder()
        self.build_graph()

    async def warm_up(self) -> dict[str, Any]:
        """Best effort: load the chunk heap and indexes into shared buffers, then run each role's legs once.

        Without it the first asks after a restart read the HNSW index and BM25 segments from disk, exceed the
        250 ms leg budget on both legs and return 503 until the caches are warm.
        """
        started = time.perf_counter()
        blocks, errors = 0, []
        try:
            async with self.services.pool.connection() as conn:
                for rel in WARM_RELATIONS:
                    row = await (await conn.execute("SELECT pg_prewarm(%s)", (rel,))).fetchone()
                    blocks += int(row[0]) if row else 0
        except Exception as exc:  # warm-up must never stop the API from starting
            errors.append(f"pg_prewarm: {type(exc).__name__}")
        roles = 0
        if self.retriever is not None:
            # one principal per role: the ACL filter differs by role, not by persona alias
            for persona in {role: name for name, (_, role) in PERSONAS.items()}.values():
                try:
                    await self.retriever.warm(WARM_QUERY, persona_principal(persona), date.today())
                    roles += 1
                except Exception as exc:
                    errors.append(f"{persona}: {type(exc).__name__}")
        report = {
            "prewarmed_blocks": blocks,
            "roles": roles,
            "errors": errors,
            "seconds": round(time.perf_counter() - started, 3),
        }
        log.info("warm_up", **report)
        return report

    async def close(self) -> None:
        for task in list(self.background):
            task.cancel()
        await self.services.close()
        await self.checkpoint_pool.close()
        if self.redis is not None:
            await self.redis.aclose()
        if self.arq is not None:
            await self.arq.aclose()


async def build_state(settings: Settings, *, validator: TokenValidator | None = None) -> AppState:
    services = await build_services(settings)
    pool = AsyncConnectionPool(
        settings.psycopg_url,
        min_size=1,
        max_size=5,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await pool.open(wait=True, timeout=30)
    checkpointer = AsyncPostgresSaver(pool)  # type: ignore[arg-type]
    await checkpointer.setup()
    redis: Redis | None = Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=2)
    try:
        await redis.ping()  # type: ignore[union-attr]
    except Exception:
        await redis.aclose()  # type: ignore[union-attr]
        redis = None
    if validator is None:
        expected_issuer = settings.oidc_public_issuer or settings.oidc_issuer
        validator = TokenValidator(expected_issuer, settings.oidc_audience, JWKSCache(settings.oidc_issuer))
    state = AppState(
        settings=settings,
        services=services,
        gateway=Gateway(settings),
        validator=validator,
        events=RunEvents(redis, ttl_s=settings.sse_ttl_s),
        redis=redis,
        checkpoint_pool=pool,
        checkpointer=checkpointer,
        limiter=RateLimiter(redis, settings.rate_limit_per_min),
    )
    if redis is not None:
        try:
            state.arq = await create_arq_pool(RedisSettings.from_dsn(settings.redis_url), retry=0)
        except Exception:
            state.arq = None
    state.build_graph()
    return state
