"""`crag reindex` / `make reindex`: rebuild the search indexes from Postgres, the source of truth.

Every chunk row (with its ACL, validity window and visibility) is re-written to OpenSearch and, when
configured, Qdrant under the same ids, so the operation is idempotent. With ``reembed`` the embeddings are
recomputed first (the LSA embedder is refitted on the corpus in seed order and registered in `index_meta`).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

from compliance_rag.embed.lsa import LocalLSAEmbedder
from compliance_rag.embed.registry import save_embedder
from compliance_rag.ingest.pipeline import IngestDeps
from compliance_rag.retrieval.types import ChunkRecord

BATCH = 1000

# seed order (document, version, ordinal) keeps an LSA refit identical to the one `crag seed` performs
SELECT_SQL = """
SELECT c.chunk_id, c.version_id::text, c.document_id, v.version, d.title, d.domain, c.ordinal,
       c.section_path, c.text, c.char_start, c.char_end, c.token_count, c.injection_score,
       c.acl_groups, c.valid_from, c.valid_to, c.visible, c.embedding
FROM chunks c
JOIN document_versions v ON v.id = c.version_id
JOIN documents d ON d.document_id = c.document_id
ORDER BY c.document_id, v.version, c.ordinal
"""


@dataclass(frozen=True)
class ReindexReport:
    chunks: int
    bm25: bool
    qdrant: bool
    reembedded: bool
    seconds: float


def _record(row: tuple[Any, ...]) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=str(row[0]).strip(),
        version_id=row[1],
        document_id=row[2],
        version=int(row[3]),
        title=row[4],
        domain=row[5],
        ordinal=int(row[6]),
        section_path=row[7],
        text=row[8],
        char_start=int(row[9]),
        char_end=int(row[10]),
        token_count=int(row[11]),
        injection_score=float(row[12]),
        acl_groups=list(row[13]),
        valid_from=row[14],
        valid_to=row[15],
        visible=bool(row[16]),
        embedding=np.asarray(
            row[17].to_numpy() if hasattr(row[17], "to_numpy") else row[17], dtype=np.float32
        ),
    )


async def _load(deps: IngestDeps) -> list[ChunkRecord]:
    async with deps.pool.connection() as conn:
        rows = await (await conn.execute(SELECT_SQL)).fetchall()
    return [_record(r) for r in rows]


async def reindex(
    deps: IngestDeps,
    *,
    bm25: bool = True,
    qdrant: bool = True,
    reembed: bool = False,
    recreate: bool = False,
    log: Callable[[str], None] = print,
) -> ReindexReport:
    """``recreate`` drops the OpenSearch index and the Qdrant collection first, so entries whose chunk no
    longer exists in Postgres disappear (searches fail until the rebuild finishes)."""
    started = time.perf_counter()
    records = await _load(deps)
    log(f"loaded {len(records)} chunks from Postgres")
    if reembed and records:
        texts = [f"{r.section_path}\n{r.text}" for r in records]
        lsa = deps.embedder if isinstance(deps.embedder, LocalLSAEmbedder) else None
        refit = lsa is not None
        if lsa is not None:
            await asyncio.to_thread(lsa.fit, texts)
        vectors = await asyncio.to_thread(deps.embedder.embed_documents, texts)
        for record, vector in zip(records, vectors, strict=True):
            record.embedding = np.asarray(vector, dtype=np.float32)
        for i in range(0, len(records), BATCH):
            await deps.pg.upsert(records[i : i + BATCH])
        log("re-embedded every chunk in Postgres")
        if refit:  # registered only once the vectors it produced are stored
            await save_embedder(deps.pool, deps.objects, deps.embedder)
            log(
                f"registered LSA embedder {deps.embedder.fingerprint()}; restart the API and worker to load it"
            )
    use_qdrant = qdrant and deps.qdrant is not None
    if recreate:
        if bm25:
            await deps.bm25.drop()
            await deps.bm25.init()
        if use_qdrant:
            assert deps.qdrant is not None
            if await deps.qdrant.client.collection_exists(deps.qdrant.collection):
                await deps.qdrant.drop_collection()
            await deps.qdrant.ensure_collection()
    for i in range(0, len(records), BATCH):
        batch = records[i : i + BATCH]
        if bm25:
            await deps.bm25.bulk_index(batch)
        if use_qdrant:
            assert deps.qdrant is not None
            await deps.qdrant.upsert(batch)
    if bm25:
        await deps.bm25.refresh()
    targets = ", ".join(n for n, on in (("OpenSearch", bm25), ("Qdrant", use_qdrant)) if on) or "nothing"
    log(f"indexed {len(records)} chunks into {targets}")
    return ReindexReport(len(records), bm25, use_qdrant, reembed, time.perf_counter() - started)
