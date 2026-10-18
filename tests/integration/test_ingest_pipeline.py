"""Async incremental versioning (FR-3, T-19)."""

from __future__ import annotations

from datetime import date

import pytest

from compliance_rag.ingest.pipeline import (
    DocumentMeta,
    IngestDeps,
    VersionConflict,
    content_sha256,
    ingest_document,
    register_upload,
    version_id_for,
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


async def test_registered_version_id_is_derived_from_its_content(ingest_deps: IngestDeps) -> None:
    policy = _kyc0042()
    v1 = policy.versions[0]
    blob = render_version(policy, v1)
    job = await register_upload(ingest_deps, _meta(policy, v1, date(2024, 1, 1)), blob, "admin")
    assert job.version_id == version_id_for("KYC-0042", v1.version, content_sha256(blob))


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


async def test_explicit_valid_to_survives_activation(ingest_deps: IngestDeps) -> None:
    """A retired version (explicit valid_to, no successor) must stay closed in every store."""
    policy = _kyc0042()
    v1 = policy.versions[0]
    meta = DocumentMeta(
        policy.document_id,
        v1.version,
        policy.title,
        policy.domain,
        policy.owner,
        date(2024, 1, 1),
        v1.source_format,
        policy.acl_groups,
        valid_to=date(2025, 1, 1),
    )
    job = await register_upload(ingest_deps, meta, render_version(policy, v1), "admin")
    await ingest_document(ingest_deps, job.job_id)
    async with ingest_deps.pool.connection() as conn:
        row = await (
            await conn.execute("SELECT valid_to FROM document_versions WHERE id = %s", (job.version_id,))
        ).fetchone()
    assert row == (date(2025, 1, 1),)
    assert await _versions_of_hits(ingest_deps, date(2026, 10, 16)) == (set(), set())
    assert await _versions_of_hits(ingest_deps, date(2024, 6, 1)) == ({1}, {1})


async def test_reupload_with_different_acl_is_rejected(ingest_deps: IngestDeps) -> None:
    from compliance_rag.ingest.pipeline import AclConflict

    policy = _kyc0042()
    v2, v3 = policy.versions[1], policy.versions[2]
    await register_upload(
        ingest_deps, _meta(policy, v2, date(2025, 1, 1)), render_version(policy, v2), "admin"
    )
    narrowed = DocumentMeta(
        policy.document_id,
        v3.version,
        policy.title,
        policy.domain,
        policy.owner,
        date(2026, 3, 1),
        v3.source_format,
        ["legal"],
    )
    with pytest.raises(AclConflict):
        await register_upload(ingest_deps, narrowed, render_version(policy, v3), "admin")


async def test_reupload_after_job_retention_does_not_reindex_an_active_version(
    ingest_deps: IngestDeps,
) -> None:
    """Retention deletes finished jobs (and with them the idempotency key); identical bytes must stay a no-op."""
    policy = _kyc0042()
    v3 = policy.versions[2]
    meta, blob = _meta(policy, v3, date(2026, 3, 1)), render_version(policy, v3)
    first = await register_upload(ingest_deps, meta, blob, "admin")
    assert (await ingest_document(ingest_deps, first.job_id)).status == "done"
    async with ingest_deps.pool.connection() as conn:
        await conn.execute(
            "DELETE FROM ingestion_jobs WHERE id = %s", (first.job_id,)
        )  # purged after 30 days

    again = await register_upload(ingest_deps, meta, blob, "admin")
    assert not again.created  # nothing to enqueue
    async with ingest_deps.pool.connection() as conn:
        status = await (
            await conn.execute("SELECT status FROM ingestion_jobs WHERE id = %s", (again.job_id,))
        ).fetchone()
        hidden = await (
            await conn.execute(
                "SELECT count(*) FROM chunks WHERE version_id = %s AND NOT visible", (again.version_id,)
            )
        ).fetchone()
    assert status is not None and status[0] == "done"
    assert hidden is not None and hidden[0] == 0  # the version in force stays searchable
    assert 3 in (await _versions_of_hits(ingest_deps, date(2026, 10, 16)))[0]
