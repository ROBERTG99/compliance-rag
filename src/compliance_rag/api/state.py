"""Everything the API process holds: services, graph, checkpointer, event store, token validator."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
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
from compliance_rag.graph.build import GraphDeps, build_graph
from compliance_rag.llm.gateway import Gateway
from compliance_rag.rerank import create_reranker
from compliance_rag.retrieval.hybrid import HybridRetriever
from compliance_rag.retrieval.warmup import warm_up
from compliance_rag.runtime import Services, build_services
from compliance_rag.settings import Settings

log = structlog.get_logger(__name__)


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
    reranker: Any = None  # the graph's reranker (warmed at start-up)
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
            authority=s.pg,
        )
        self.retriever = retriever
        reranker = create_reranker(self.settings.reranker, embedder=s.embedder)
        self.reranker = reranker
        self.graph = build_graph(
            GraphDeps(retriever, reranker, self.gateway, self.settings), self.checkpointer
        )

    async def reload(self) -> None:
        """Reload the embedder (after seeding/reindexing) and rebuild the graph."""
        await self.services.reload_embedder()
        self.build_graph()

    async def queue(self) -> ArqRedis | None:
        """The Arq pool, created on first use (or again after Redis comes back); None while unavailable."""
        if self.arq is None:
            try:
                self.arq = await asyncio.wait_for(
                    create_arq_pool(RedisSettings.from_dsn(self.settings.redis_url), retry=0), timeout=2.0
                )
            except Exception as exc:
                log.warning("queue_unavailable", error=type(exc).__name__)
                self.arq = None
        return self.arq

    async def warm_up(self) -> dict[str, Any]:
        """Before readiness: cold caches would 503 the first asks (see ``retrieval.warmup``)."""
        return await warm_up(self.services.pool, self.retriever, reranker=self.reranker)

    async def close(self) -> None:
        for task in list(self.background):
            task.cancel()
        await self.gateway.aclose()
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
    # always a client: each call fails open on its own (§4.7), so a Redis outage at start-up heals by itself
    redis = Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=2)
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
    await state.queue()  # best effort now; retried lazily on the next upload
    state.build_graph()
    return state
