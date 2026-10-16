"""Bulk seed: idempotent by corpus fingerprint, chunks visible only after activation (T-33 groundwork)."""

from __future__ import annotations

import pytest

from compliance_rag.ingest.pipeline import IngestDeps
from compliance_rag.ingest.seed import seed_corpus

pytestmark = pytest.mark.integration


async def test_seed_is_idempotent(ingest_deps: IngestDeps) -> None:
    only = {"KYC-0042", "CMP-0215"}
    first = await seed_corpus(ingest_deps, only=only, log=lambda _m: None)
    assert first.status == "seeded" and first.versions == 5 and first.chunks > 0
    second = await seed_corpus(ingest_deps, only=only, log=lambda _m: None)
    assert second.status == "already_seeded" and second.chunks == first.chunks
    async with ingest_deps.pool.connection() as conn:
        rows = await (
            await conn.execute("SELECT count(*) FILTER (WHERE NOT visible), count(*) FROM chunks")
        ).fetchone()
        versions = await (
            await conn.execute(
                "SELECT document_id, version, status, valid_to FROM document_versions ORDER BY 1, 2"
            )
        ).fetchall()
    assert rows is not None and rows[0] == 0 and rows[1] == first.chunks
    assert [v[2] for v in versions] == ["active"] * 5
    open_versions = [v for v in versions if v[3] is None]
    assert {(v[0], v[1]) for v in open_versions} == {("KYC-0042", 3), ("CMP-0215", 2)}
    assert await ingest_deps.bm25.count() == first.chunks
