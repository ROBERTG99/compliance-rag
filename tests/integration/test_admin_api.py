"""ACL changes, ingestion jobs and index lag (FR-14, FR-11, T-29)."""

from __future__ import annotations

import uuid

import pytest

from tests.fixtures_services import ApiEnv

pytestmark = pytest.mark.integration


async def _pending(env: ApiEnv) -> int:
    async with await env.client("admin") as admin:
        resp = await admin.get("/v1/index/lag")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) >= {"p50_s", "p95_s", "pending"}
    return int(body["pending"])


async def test_index_lag_reports_pending(api_env: ApiEnv) -> None:
    before = await _pending(api_env)
    state = api_env.app.state.crag
    async with state.services.pool.connection() as conn:
        for _ in range(3):
            await conn.execute(
                "INSERT INTO ingestion_jobs (idempotency_key, kind, document_id, status, requested_by) "
                "VALUES (%s, 'reindex', 'KYC-0042', 'queued', 'test')",
                (uuid.uuid4().hex * 2,),
            )
    try:
        assert await _pending(api_env) == before + 3
        async with await api_env.client("admin") as admin:
            jobs = (
                await admin.get("/v1/ingestion-jobs", params={"status": "queued", "kind": "reindex"})
            ).json()
        assert len(jobs["items"]) >= 3 and all(j["status"] == "queued" for j in jobs["items"])
    finally:  # later tests count pending jobs too
        async with state.services.pool.connection() as conn:
            await conn.execute(
                "UPDATE ingestion_jobs SET status = 'done', finished_at = now() WHERE requested_by = 'test'"
            )
    async with await api_env.client("analyst") as analyst:
        assert (await analyst.get("/v1/index/lag")).status_code == 403


async def test_acl_change_reaches_both_indexes(api_env: ApiEnv) -> None:
    question = {"question": "What is the maximum age of a proof-of-address document?", "stream": False}
    async with await api_env.client("support") as support:
        assert not (await support.post("/v1/ask", json=question)).json()["abstained"]
    async with await api_env.client("admin") as admin:
        changed = await admin.put("/v1/documents/KYC-0042/acl", json={"groups": ["compliance"]})
        missing = await admin.put("/v1/documents/ZZZ-0001/acl", json={"groups": ["all"]})
        invalid = await admin.put("/v1/documents/KYC-0042/acl", json={"groups": ["admins"]})
    assert changed.status_code == 202 and changed.json()["job_id"]
    assert missing.status_code == 404 and invalid.status_code == 422
    try:
        state = api_env.app.state.crag
        from datetime import date

        from compliance_rag.auth.personas import persona_principal

        support_principal = persona_principal("support")
        bm25 = await state.services.bm25.search(
            "proof of address document", support_principal, date.today(), k=50
        )
        assert all(h["document_id"] != "KYC-0042" for h in bm25)
        vec = await state.services.pg.search(
            state.services.embedder.embed_query("proof of address"), support_principal, date.today(), k=50
        )
        assert all(h["document_id"] != "KYC-0042" for h in vec)
        async with await api_env.client("support") as support:
            assert (await support.post("/v1/ask", json=question)).json()["abstained"]
            assert (await support.get("/v1/documents/KYC-0042")).status_code == 404
        async with state.services.pool.connection() as conn:
            audit = (
                await (
                    await conn.execute("SELECT count(*) FROM audit WHERE action = 'acl_change'")
                ).fetchone()
            )[0]
        assert audit >= 1
    finally:
        async with await api_env.client("admin") as admin:
            assert (
                await admin.put("/v1/documents/KYC-0042/acl", json={"groups": ["all"]})
            ).status_code == 202
