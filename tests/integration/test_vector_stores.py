"""Vector stores filter ACL, validity and visibility inside the query (FR-5, T-17)."""

from __future__ import annotations

import random
import uuid
from collections.abc import AsyncIterator
from datetime import date

import numpy as np
import pytest

from compliance_rag.db.pool import create_pool
from compliance_rag.retrieval.types import ChunkRecord, Principal
from compliance_rag.retrieval.vector.base import VectorStore
from compliance_rag.retrieval.vector.pgvector import PgVectorStore
from compliance_rag.retrieval.vector.qdrant import QdrantStore
from tests.fixtures_services import Database

pytestmark = pytest.mark.integration
DIM = 384
GROUPS = ["all", "compliance", "legal", "support"]
SUPPORT: Principal = {"sub": "support@northwind.test", "role": "support", "groups": ["support", "all"]}


def _unit(rng: np.random.Generator, base: np.ndarray | None = None, noise: float = 1.0) -> np.ndarray:
    v = rng.normal(size=DIM).astype(np.float32) * noise
    if base is not None:
        v = base + v
    return (v / np.linalg.norm(v)).astype(np.float32)


async def _seed_rows(db_url: str, records: list[ChunkRecord]) -> None:
    import psycopg

    async with await psycopg.AsyncConnection.connect(db_url, autocommit=True) as conn:
        for doc_id in sorted({r.document_id for r in records}):
            await conn.execute(
                "INSERT INTO documents (document_id, title, domain, owner) VALUES (%s, %s, 'kyc', 'o') ON CONFLICT DO NOTHING",
                (doc_id, f"Title {doc_id}"),
            )
        for r in {r.version_id: r for r in records}.values():
            await conn.execute(
                """INSERT INTO document_versions (id, document_id, version, content_sha256, source_format, s3_key,
                   size_bytes, valid_from, valid_to, status) VALUES (%s, %s, %s, %s, 'md', 'k', 1, %s, %s, 'indexing')""",
                (r.version_id, r.document_id, r.version, uuid.uuid4().hex * 2, r.valid_from, r.valid_to),
            )


def _records(
    n_restricted: int, n_allowed: int, query: np.ndarray, rng: np.random.Generator
) -> list[ChunkRecord]:
    out = []
    for i in range(n_restricted + n_allowed):
        restricted = i < n_restricted
        doc_id = f"LEG-{i:04d}" if restricted else f"KYC-{i:04d}"
        version_id = str(uuid.UUID(int=i + 1))
        emb = _unit(rng, query * 50, 0.01) if restricted else _unit(rng, query * 2, 1.0)
        out.append(
            ChunkRecord(
                chunk_id=uuid.UUID(int=10_000 + i).hex,
                version_id=version_id,
                document_id=doc_id,
                version=1,
                title=f"Title {doc_id}",
                domain="kyc",
                ordinal=0,
                section_path="Article 1 — Scope",
                text=f"chunk {i}",
                char_start=0,
                char_end=7,
                token_count=2,
                injection_score=0.0,
                acl_groups=["legal"] if restricted else ["support"],
                valid_from=date(2025, 1, 1),
                valid_to=None,
                visible=True,
                embedding=emb,
            )
        )
    return out


@pytest.fixture(params=["pgvector", "qdrant"])
async def store(
    request: pytest.FixtureRequest, migrated_db: Database
) -> AsyncIterator[tuple[VectorStore, str]]:
    if request.param == "pgvector":
        pool = await create_pool(migrated_db.url, min_size=1, max_size=4)
        try:
            yield PgVectorStore(pool), migrated_db.url
        finally:
            await pool.close()
    else:
        url = request.getfixturevalue("qdrant_url")
        qs = QdrantStore(url, collection=f"t_{uuid.uuid4().hex[:8]}", dim=DIM)
        await qs.ensure_collection()
        try:
            yield qs, migrated_db.url
        finally:
            await qs.drop_collection()
            await qs.close()


async def test_acl_filter_inside_query(store: tuple[VectorStore, str]) -> None:
    vs, db_url = store
    rng = np.random.default_rng(2026)
    query = _unit(rng)
    records = _records(n_restricted=300, n_allowed=40, query=query, rng=rng)
    await _seed_rows(db_url, records)
    await vs.upsert(records)
    hits = await vs.search(query, SUPPORT, date(2026, 10, 16), k=10)
    # a post-filter would have kept only restricted (nearest) chunks and returned < 10 hits
    assert len(hits) == 10
    assert all(set(h["acl_groups"]) & set(SUPPORT["groups"]) for h in hits)
    assert all(not h["document_id"].startswith("LEG-") for h in hits)
    assert hits == sorted(hits, key=lambda h: -(h["cosine"] or 0))


async def test_validity_and_visibility_filters(store: tuple[VectorStore, str]) -> None:
    vs, db_url = store
    rng = np.random.default_rng(7)
    query = _unit(rng)
    records = _records(0, 3, query, rng)
    records[0].valid_from, records[0].valid_to = date(2024, 1, 1), date(2025, 1, 1)  # superseded
    records[1].visible = False  # not yet activated
    await _seed_rows(db_url, records)
    await vs.upsert(records)
    ids = {h["chunk_id"] for h in await vs.search(query, SUPPORT, date(2026, 10, 16), k=10)}
    assert ids == {records[2].chunk_id}
    old = {h["chunk_id"] for h in await vs.search(query, SUPPORT, date(2024, 6, 1), k=10)}
    assert old == {records[0].chunk_id}
    await vs.set_visible(records[1].version_id, True)
    assert len(await vs.search(query, SUPPORT, date(2026, 10, 16), k=10)) == 2
    await vs.close_version(records[2].version_id, date(2026, 3, 1))
    ids = {h["chunk_id"] for h in await vs.search(query, SUPPORT, date(2026, 10, 16), k=10)}
    assert records[2].chunk_id not in ids
    await vs.update_acl(records[1].document_id, ["legal"])
    assert await vs.search(query, SUPPORT, date(2026, 10, 16), k=10) == []


async def test_random_group_assignments_never_leak(store: tuple[VectorStore, str]) -> None:
    vs, db_url = store
    rng = np.random.default_rng(11)
    prng = random.Random(11)
    query = _unit(rng)
    records = _records(0, 120, query, rng)
    for r in records:
        r.acl_groups = prng.sample(GROUPS, k=prng.randint(1, 2))
    await _seed_rows(db_url, records)
    await vs.upsert(records)
    for _ in range(25):
        groups = prng.sample(GROUPS, k=prng.randint(1, 3))
        principal: Principal = {"sub": "p", "role": "analyst", "groups": groups}
        for hit in await vs.search(_unit(rng), principal, date(2026, 10, 16), k=20):
            assert set(hit["acl_groups"]) & set(groups)
