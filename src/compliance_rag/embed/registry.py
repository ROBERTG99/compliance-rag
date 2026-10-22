"""Persist and load the active embedder; ``index_meta['embedder']`` records what the index was built with."""

from __future__ import annotations

import json
from typing import Any

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from compliance_rag.embed import create_embedder
from compliance_rag.embed.base import Embedder, EmbedderMismatch
from compliance_rag.embed.lsa import LocalLSAEmbedder
from compliance_rag.ingest.objectstore import ObjectStore
from compliance_rag.settings import Settings


async def read_index_meta(pool: AsyncConnectionPool, key: str) -> dict[str, Any] | None:
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT value FROM index_meta WHERE key = %s", (key,))
        row = await cur.fetchone()
    if row is None:
        return None
    value = row[0]
    return value if isinstance(value, dict) else json.loads(value)


async def write_index_meta(pool: AsyncConnectionPool, key: str, value: dict[str, Any]) -> None:
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO index_meta (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            (key, Jsonb(value)),
        )


async def save_embedder(
    pool: AsyncConnectionPool, objects: ObjectStore, embedder: Embedder
) -> dict[str, Any]:
    meta = embedder.meta()
    if isinstance(embedder, LocalLSAEmbedder):
        key = f"models/lsa/{embedder.fingerprint()}.npz"
        await objects.put(key, embedder.to_bytes())
        meta["model_key"] = key
    await write_index_meta(pool, "embedder", meta)
    return meta


async def load_embedder(settings: Settings, pool: AsyncConnectionPool, objects: ObjectStore) -> Embedder:
    """Return the embedder matching ``index_meta``; refuse a configuration that differs."""
    meta = await read_index_meta(pool, "embedder")
    if meta is None:
        return create_embedder(settings.embedder, dim=settings.embed_dim)
    if meta.get("name") != settings.embedder or int(meta.get("dim", 0)) != settings.embed_dim:
        raise EmbedderMismatch(
            f"index built with {meta.get('name')}/{meta.get('dim')}, configured {settings.embedder}/"
            f"{settings.embed_dim}; set CRAG_EMBEDDER/CRAG_EMBED_DIM accordingly or run `make reindex`"
        )
    if meta["name"] == "lsa":
        embedder: Embedder = LocalLSAEmbedder.from_bytes(await objects.get(str(meta["model_key"])))
    else:
        embedder = create_embedder(meta["name"], dim=int(meta["dim"]))
    embedder.check_compatible(meta)
    return embedder
