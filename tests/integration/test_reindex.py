"""`crag reindex`: rebuild OpenSearch and Qdrant from Postgres, keeping ACL, validity and visibility (T-40)."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import date

import pytest

from compliance_rag.auth.personas import persona_principal
from compliance_rag.ingest.pipeline import IngestDeps
from compliance_rag.ingest.reindex import reindex
from compliance_rag.ingest.seed import seed_corpus
from compliance_rag.retrieval.vector.qdrant import QdrantStore

pytestmark = pytest.mark.integration
AS_OF = date(2026, 10, 16)


async def test_reindex_fills_qdrant_and_rebuilds_bm25_from_postgres(
    ingest_deps: IngestDeps, qdrant_url: str
) -> None:
    await seed_corpus(ingest_deps, only={"KYC-0042", "CMP-0215"}, log=lambda _m: None)
    async with ingest_deps.pool.connection() as conn:
        # one hidden chunk must stay hidden in both indexes
        hidden = await (
            await conn.execute("SELECT chunk_id FROM chunks ORDER BY chunk_id LIMIT 1")
        ).fetchone()
        assert hidden is not None
        await conn.execute("UPDATE chunks SET visible = false WHERE chunk_id = %s", (hidden[0],))
        total = (await (await conn.execute("SELECT count(*) FROM chunks")).fetchone() or [0])[0]
    await ingest_deps.bm25.drop()
    await ingest_deps.bm25.init()
    store = QdrantStore(qdrant_url, collection=f"reindex-{uuid.uuid4().hex[:8]}")
    await store.ensure_collection()
    deps = replace(ingest_deps, qdrant=store)
    try:
        report = await reindex(deps, log=lambda _m: None)
        assert report.chunks == total and report.qdrant and report.bm25
        assert await ingest_deps.bm25.count() == total
        counted = await store.client.count(store.collection, exact=True)
        assert counted.count == total

        cmp_text = "litigation hold complaint files preserved"
        query = ingest_deps.embedder.embed_query(cmp_text)
        legal = await store.search(query, persona_principal("legal"), AS_OF, k=20)
        support = await store.search(query, persona_principal("support"), AS_OF, k=20)
        assert any(c["document_id"] == "CMP-0215" for c in legal)
        assert all(c["document_id"] != "CMP-0215" for c in support)
        # validity at as_of: only KYC-0042 v3 is in force on 2026-10-16
        kyc = await store.search(
            ingest_deps.embedder.embed_query("proof of address"), persona_principal("analyst"), AS_OF, k=50
        )
        assert {c["version"] for c in kyc if c["document_id"] == "KYC-0042"} == {3}
        everyone = await store.search(query, persona_principal("admin"), AS_OF, k=500)
        assert hidden[0] not in {c["chunk_id"] for c in everyone}
        bm25_hits = await ingest_deps.bm25.search(
            "proof of address", persona_principal("admin"), AS_OF, k=500
        )
        assert hidden[0] not in {c["chunk_id"] for c in bm25_hits}

        again = await reindex(deps, log=lambda _m: None)  # idempotent: same ids, no duplicates
        assert again.chunks == total
        assert (await store.client.count(store.collection, exact=True)).count == total
    finally:
        await store.drop_collection()
        await store.close()


async def test_reembed_refits_the_same_lsa_model_in_seed_order(ingest_deps: IngestDeps) -> None:
    import numpy as np

    await seed_corpus(ingest_deps, only={"KYC-0042"}, log=lambda _m: None)
    before = ingest_deps.embedder.fingerprint()
    async with ingest_deps.pool.connection() as conn:
        old = await (
            await conn.execute("SELECT chunk_id, embedding FROM chunks ORDER BY chunk_id")
        ).fetchall()
    report = await reindex(ingest_deps, qdrant=False, reembed=True, log=lambda _m: None)
    assert report.reembedded and report.chunks == len(old)
    assert ingest_deps.embedder.fingerprint() == before
    async with ingest_deps.pool.connection() as conn:
        new = await (
            await conn.execute("SELECT chunk_id, embedding FROM chunks ORDER BY chunk_id")
        ).fetchall()
    assert [r[0] for r in new] == [r[0] for r in old]
    for (_, a), (_, b) in zip(old, new, strict=True):
        assert np.allclose(a.to_numpy(), b.to_numpy(), atol=1e-5)
