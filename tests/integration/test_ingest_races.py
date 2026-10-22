"""Races between ingestion, ACL changes and conflicting uploads."""

from __future__ import annotations

from datetime import date

import pytest

from compliance_rag.ingest.pipeline import (
    DocumentMeta,
    IngestDeps,
    VersionConflict,
    activate_in_postgres,
    build_records,
    parse_version,
    raw_key,
    register_upload,
    sync_activation,
    write_indexes,
)
from compliance_rag.retrieval.types import Principal
from compliance_rag.worker.acl import change_acl
from data.generator.corpus import SEED, build_corpus
from data.generator.render import render_version

pytestmark = pytest.mark.integration
SUPPORT: Principal = {"sub": "support@northwind.test", "role": "support", "groups": ["support", "all"]}
QUESTION = "maximum age of a proof-of-address document"


def _kyc0042():  # type: ignore[no-untyped-def]
    return next(p for p in build_corpus(SEED) if p.document_id == "KYC-0042")


def _meta(policy, version, groups: list[str]) -> DocumentMeta:  # type: ignore[no-untyped-def]
    return DocumentMeta(
        policy.document_id,
        version.version,
        policy.title,
        policy.domain,
        policy.owner,
        date(2025, 1, 1),
        version.source_format,
        groups,
    )


async def test_acl_change_during_ingestion_reaches_the_new_version(ingest_deps: IngestDeps) -> None:
    policy = _kyc0042()
    v2 = policy.versions[1]
    job = await register_upload(ingest_deps, _meta(policy, v2, ["all"]), render_version(policy, v2), "admin")
    parsed = await parse_version(ingest_deps, job.version_id)  # reads the ACL: all
    await write_indexes(ingest_deps, build_records(parsed, ingest_deps.embedder))
    # the admin narrows the document while the job is between indexing and activation
    await change_acl(ingest_deps, policy.document_id, ["compliance"], "admin")
    act = await activate_in_postgres(ingest_deps.pool, job.version_id)
    await sync_activation(ingest_deps, act)

    as_of = date(2026, 10, 16)
    assert await ingest_deps.bm25.search(QUESTION, SUPPORT, as_of, k=50) == []
    vec = ingest_deps.embedder.embed_query(QUESTION)
    assert await ingest_deps.pg.search(vec, SUPPORT, as_of, k=50) == []
    async with ingest_deps.pool.connection() as conn:
        rows = await (
            await conn.execute(
                "SELECT DISTINCT acl_groups FROM chunks WHERE version_id = %s", (job.version_id,)
            )
        ).fetchall()
    assert [list(r[0]) for r in rows] == [["compliance"]]


async def test_rejected_upload_does_not_replace_the_stored_raw_file(ingest_deps: IngestDeps) -> None:
    policy = _kyc0042()
    v2 = policy.versions[1]
    blob = render_version(policy, v2)
    await register_upload(ingest_deps, _meta(policy, v2, policy.acl_groups), blob, "admin")
    key = raw_key(policy.document_id, v2.version, v2.source_format)
    before = await ingest_deps.objects.get(key)
    with pytest.raises(VersionConflict):
        await register_upload(ingest_deps, _meta(policy, v2, policy.acl_groups), blob + b"\nedited", "admin")
    assert await ingest_deps.objects.get(key) == before == blob


async def test_activation_and_upload_are_audited_once(ingest_deps: IngestDeps) -> None:
    from compliance_rag.db.audit import verify_chain
    from compliance_rag.ingest.pipeline import ingest_document

    policy = _kyc0042()
    v2 = policy.versions[1]
    job = await register_upload(
        ingest_deps,
        _meta(policy, v2, policy.acl_groups),
        render_version(policy, v2),
        "admin",
        actor_role="content_admin",
    )
    assert (await ingest_document(ingest_deps, job.job_id)).status == "done"
    await activate_in_postgres(ingest_deps.pool, job.version_id)  # a replay adds nothing
    async with ingest_deps.pool.connection() as conn:
        rows = await (
            await conn.execute(
                "SELECT action, actor_role FROM audit WHERE target = %s ORDER BY seq", ("KYC-0042@2",)
            )
        ).fetchall()
        assert [tuple(r) for r in rows] == [
            ("document_upload", "content_admin"),
            ("version_activate", "system"),
        ]
        assert (await verify_chain(conn)).ok


async def test_acl_change_before_chunks_exist_is_applied_at_activation(ingest_deps: IngestDeps) -> None:
    """change_acl runs while the job is parsing: no chunk rows exist yet, so only activation can fix them."""
    policy = _kyc0042()
    v2 = policy.versions[1]
    job = await register_upload(ingest_deps, _meta(policy, v2, ["all"]), render_version(policy, v2), "admin")
    parsed = await parse_version(ingest_deps, job.version_id)  # chunk records carry ACL "all"
    await change_acl(ingest_deps, policy.document_id, ["compliance"], "admin")
    await write_indexes(
        ingest_deps, build_records(parsed, ingest_deps.embedder)
    )  # written with the stale ACL
    act = await activate_in_postgres(ingest_deps.pool, job.version_id)
    await sync_activation(ingest_deps, act)

    as_of = date(2026, 10, 16)
    assert await ingest_deps.bm25.search(QUESTION, SUPPORT, as_of, k=50) == []
    vec = ingest_deps.embedder.embed_query(QUESTION)
    assert await ingest_deps.pg.search(vec, SUPPORT, as_of, k=50) == []
    async with ingest_deps.pool.connection() as conn:
        rows = await (
            await conn.execute(
                "SELECT DISTINCT acl_groups FROM chunks WHERE version_id = %s", (job.version_id,)
            )
        ).fetchall()
    assert [list(r[0]) for r in rows] == [["compliance"]]
