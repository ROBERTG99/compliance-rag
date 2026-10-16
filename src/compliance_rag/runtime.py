"""Process-wide service container shared by the API, the worker and the CLI."""

from __future__ import annotations

from dataclasses import dataclass, field

from psycopg_pool import AsyncConnectionPool

from compliance_rag.db.pool import create_pool
from compliance_rag.embed.base import Embedder
from compliance_rag.embed.registry import load_embedder
from compliance_rag.ingest.objectstore import ObjectStore, S3ObjectStore
from compliance_rag.ingest.pipeline import IngestDeps
from compliance_rag.retrieval.bm25 import BM25Index
from compliance_rag.retrieval.vector.pgvector import PgVectorStore
from compliance_rag.retrieval.vector.qdrant import QdrantStore
from compliance_rag.settings import Settings


@dataclass
class Services:
    settings: Settings
    pool: AsyncConnectionPool
    objects: ObjectStore
    bm25: BM25Index
    pg: PgVectorStore
    embedder: Embedder
    qdrant: QdrantStore | None = None
    extras: dict[str, object] = field(default_factory=dict)

    def ingest_deps(self) -> IngestDeps:
        return IngestDeps(
            pool=self.pool, objects=self.objects, bm25=self.bm25, embedder=self.embedder, qdrant=self.qdrant
        )

    async def reload_embedder(self) -> None:
        self.embedder = await load_embedder(self.settings, self.pool, self.objects)

    async def close(self) -> None:
        await self.bm25.close()
        if self.qdrant is not None:
            await self.qdrant.close()
        await self.pool.close()


def object_store(settings: Settings) -> S3ObjectStore:
    return S3ObjectStore(
        settings.s3_endpoint_url or None,
        settings.s3_access_key.get_secret_value(),
        settings.s3_secret_key.get_secret_value(),
        settings.s3_bucket,
        settings.s3_region,
    )


async def build_services(
    settings: Settings, *, with_qdrant: bool | None = None, pool_size: int = 10
) -> Services:
    pool = await create_pool(settings.psycopg_url, min_size=1, max_size=pool_size)
    objects = object_store(settings)
    bm25 = BM25Index(
        settings.opensearch_url,
        settings.opensearch_index,
        settings.opensearch_alias,
        timeout_s=max(1.0, settings.leg_timeout_ms / 1000 * 4),
    )
    use_qdrant = settings.vector_store == "qdrant" if with_qdrant is None else with_qdrant
    qdrant = (
        QdrantStore(settings.qdrant_url, settings.qdrant_collection, settings.embed_dim)
        if use_qdrant
        else None
    )
    embedder = await load_embedder(settings, pool, objects)
    return Services(
        settings=settings,
        pool=pool,
        objects=objects,
        bm25=bm25,
        pg=PgVectorStore(pool),
        embedder=embedder,
        qdrant=qdrant,
    )
