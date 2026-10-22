"""Stale index copies after a failed ACL sync are never served; the reconcile cron repairs them."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from compliance_rag.ingest.pipeline import DocumentMeta, IngestDeps, ingest_document, register_upload
from compliance_rag.retrieval.hybrid import HybridRetriever
from compliance_rag.retrieval.types import Principal
from compliance_rag.worker.acl import change_acl, reconcile_acl_sync
from data.generator.corpus import SEED, build_corpus
from data.generator.render import render_version

pytestmark = pytest.mark.integration
SUPPORT: Principal = {"sub": "support@northwind.test", "role": "support", "groups": ["support", "all"]}
QUESTION = "maximum age of a proof-of-address document"
AS_OF = date(2026, 10, 16)


async def test_unsynced_revocation_is_not_served_and_is_reconciled(ingest_deps: IngestDeps) -> None:
    policy = next(p for p in build_corpus(SEED) if p.document_id == "KYC-0042")
    v2 = policy.versions[1]
    meta = DocumentMeta(
        policy.document_id,
        v2.version,
        policy.title,
        policy.domain,
        policy.owner,
        date(2025, 1, 1),
        v2.source_format,
        ["all"],
    )
    job = await register_upload(ingest_deps, meta, render_version(policy, v2), "admin")
    assert (await ingest_document(ingest_deps, job.job_id)).status == "done"
    assert await ingest_deps.bm25.search(QUESTION, SUPPORT, AS_OF, k=50)  # visible to support for now

    async def down(*_: object, **__: object) -> None:
        raise ConnectionError("opensearch down")

    with patch.object(type(ingest_deps.bm25), "update_acl", down):
        change = await change_acl(ingest_deps, policy.document_id, ["compliance"], "admin")
    assert not change.indexes_synced
    # the OpenSearch copy is stale: it still says "all"
    assert await ingest_deps.bm25.search(QUESTION, SUPPORT, AS_OF, k=50)

    retriever = HybridRetriever(
        ingest_deps.bm25, ingest_deps.pg, ingest_deps.embedder, timeout_ms=5000, authority=ingest_deps.pg
    )
    result = await retriever.retrieve(QUESTION, SUPPORT, AS_OF)
    assert result.fused == []  # Postgres says no: the stale copy is dropped

    assert await reconcile_acl_sync(ingest_deps, min_age_s=0) == 1
    assert await ingest_deps.bm25.search(QUESTION, SUPPORT, AS_OF, k=50) == []
    async with ingest_deps.pool.connection() as conn:
        status = await (
            await conn.execute("SELECT status FROM ingestion_jobs WHERE id = %s", (change.job_id,))
        ).fetchone()
        audited = await (
            await conn.execute(
                "SELECT count(*) FROM audit WHERE action = 'acl_change' AND target = 'KYC-0042'"
            )
        ).fetchone()
    assert status is not None and status[0] == "done"
    assert audited is not None and audited[0] == 1


async def test_a_change_committed_during_a_sync_wins_in_the_index(ingest_deps: IngestDeps) -> None:
    # an older, slower sync must not overwrite a newer ACL in OpenSearch: the sync re-reads Postgres after
    # writing and writes again until the ACL stops changing
    from compliance_rag.worker.acl import sync_acl

    policy = next(p for p in build_corpus(SEED) if p.document_id == "KYC-0042")
    v2 = policy.versions[1]
    meta = DocumentMeta(
        policy.document_id,
        v2.version,
        policy.title,
        policy.domain,
        policy.owner,
        date(2025, 1, 1),
        v2.source_format,
        ["all"],
    )
    job = await register_upload(ingest_deps, meta, render_version(policy, v2), "admin")
    assert (await ingest_document(ingest_deps, job.job_id)).status == "done"

    async def down(*_: object, **__: object) -> None:
        raise ConnectionError("opensearch down")

    with patch.object(type(ingest_deps.bm25), "update_acl", down):
        older = await change_acl(ingest_deps, policy.document_id, ["compliance"], "admin")
    real_update = type(ingest_deps.bm25).update_acl
    calls: list[list[str]] = []

    async def slow_update(self: object, document_id: str, groups: list[str]) -> None:
        calls.append(list(groups))
        if len(calls) == 1:  # while the older sync writes, a newer change commits in Postgres
            async with ingest_deps.pool.connection() as conn:
                await conn.execute("DELETE FROM document_acl WHERE document_id = %s", (document_id,))
                await conn.execute(
                    "INSERT INTO document_acl (document_id, group_name, granted_by) VALUES (%s, 'all', 'admin')",
                    (document_id,),
                )
        await real_update(self, document_id, groups)  # type: ignore[arg-type]

    with patch.object(type(ingest_deps.bm25), "update_acl", slow_update):
        assert await sync_acl(ingest_deps, older.job_id)
    assert calls == [["compliance"], ["all"]]
    assert await ingest_deps.bm25.search(QUESTION, SUPPORT, AS_OF, k=50)  # the newer "all" is in the index
