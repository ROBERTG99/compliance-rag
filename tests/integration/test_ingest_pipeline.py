"""Async incremental versioning (FR-3, T-19)."""

from __future__ import annotations

from datetime import date

import pytest

from compliance_rag.ingest.pipeline import (
    DocumentMeta,
    IngestDeps,
    VersionConflict,
    ingest_document,
    register_upload,
)
from compliance_rag.retrieval.types import Principal
from data.generator.corpus import SEED, build_corpus
from data.generator.render import render_version

pytestmark = pytest.mark.integration
ANALYST: Principal = {"sub": "analyst@northwind.test", "role": "analyst", "groups": ["compliance", "all"]}
QUESTION = "maximum age of a proof-of-address document"


def _kyc0042():  # type: ignore[no-untyped-def]
    return next(p for p in build_corpus(SEED) if p.document_id == "KYC-0042")


def _meta(policy, version, valid_from: date) -> DocumentMeta:  # type: ignore[no-untyped-def]
    return DocumentMeta(
        policy.document_id,
        version.version,
        policy.title,
        policy.domain,
        policy.owner,
        valid_from,
        version.source_format,
        policy.acl_groups,
    )


async def _versions_of_hits(deps: IngestDeps, as_of: date) -> tuple[set[int], set[int]]:
    bm25 = {h["version"] for h in await deps.bm25.search(QUESTION, ANALYST, as_of, k=50)}
    vec = deps.embedder.embed_query(QUESTION)
    pg = {h["version"] for h in await deps.pg.search(vec, ANALYST, as_of, k=50)}
    return bm25, pg


async def test_new_version_supersedes_previous(ingest_deps: IngestDeps) -> None:
    policy = _kyc0042()
    v2, v3 = policy.versions[1], policy.versions[2]
    job2 = await register_upload(
        ingest_deps, _meta(policy, v2, date(2025, 1, 1)), render_version(policy, v2), "admin"
    )
    assert (await ingest_document(ingest_deps, job2.job_id)).status == "done"
    job3 = await register_upload(
        ingest_deps, _meta(policy, v3, date(2026, 3, 1)), render_version(policy, v3), "admin"
    )
    result = await ingest_document(ingest_deps, job3.job_id)
    assert result.status == "done" and result.chunk_count > 0

    async with ingest_deps.pool.connection() as conn:
        rows = await (
            await conn.execute(
                "SELECT version, status, valid_to FROM document_versions WHERE document_id = 'KYC-0042' ORDER BY version"
            )
        ).fetchall()
    assert rows == [(2, "active", date(2026, 3, 1)), (3, "active", None)]
    assert await _versions_of_hits(ingest_deps, date(2026, 2, 15)) == ({2}, {2})
    assert await _versions_of_hits(ingest_deps, date(2026, 10, 16)) == ({3}, {3})


async def test_upload_idempotent_and_conflict(ingest_deps: IngestDeps) -> None:
    policy = _kyc0042()
    v2 = policy.versions[1]
    blob = render_version(policy, v2)
    a = await register_upload(ingest_deps, _meta(policy, v2, date(2025, 1, 1)), blob, "admin")
    b = await register_upload(ingest_deps, _meta(policy, v2, date(2025, 1, 1)), blob, "admin")
    assert a.job_id == b.job_id and a.created and not b.created
    with pytest.raises(VersionConflict):
        await register_upload(ingest_deps, _meta(policy, v2, date(2025, 1, 1)), blob + b"\nchanged", "admin")


async def test_crash_between_stores_is_repaired_by_replay(ingest_deps: IngestDeps) -> None:
    policy = _kyc0042()
    v2, v3 = policy.versions[1], policy.versions[2]
    job2 = await register_upload(
        ingest_deps, _meta(policy, v2, date(2025, 1, 1)), render_version(policy, v2), "admin"
    )
    await ingest_document(ingest_deps, job2.job_id)

    async def crash(_: str) -> None:
        raise RuntimeError("simulated crash after Postgres commit")

    ingest_deps.after_pg_activation = crash
    job3 = await register_upload(
        ingest_deps, _meta(policy, v3, date(2026, 3, 1)), render_version(policy, v3), "admin"
    )
    with pytest.raises(RuntimeError):
        await ingest_document(ingest_deps, job3.job_id)
    await ingest_deps.bm25.refresh()
    # Postgres moved on, OpenSearch did not: BM25 still serves v2 today and nothing of v3
    bm25_today, pg_today = await _versions_of_hits(ingest_deps, date(2026, 10, 16))
    assert pg_today == {3} and bm25_today == {2}
    ingest_deps.after_pg_activation = None
    replay = await ingest_document(ingest_deps, job3.job_id)
    assert replay.status == "done"
    assert await _versions_of_hits(ingest_deps, date(2026, 10, 16)) == ({3}, {3})
    assert await _versions_of_hits(ingest_deps, date(2026, 2, 15)) == ({2}, {2})
    async with ingest_deps.pool.connection() as conn:
        row = await (
            await conn.execute("SELECT status, attempts FROM ingestion_jobs WHERE id = %s", (job3.job_id,))
        ).fetchone()
    assert row == ("done", 2)
