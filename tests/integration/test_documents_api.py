"""Documents API: upload, S3 import, library, versions, evidence (FR-1, T-28)."""

from __future__ import annotations

import json

import pytest

from data.generator.corpus import SEED, build_corpus
from data.generator.render import render_version
from tests.fixtures_services import ApiEnv

pytestmark = pytest.mark.integration


def _aml0107_v4() -> bytes:
    policy = next(p for p in build_corpus(SEED) if p.document_id == "AML-0107")
    v3 = policy.versions[2]
    v3.version = 4
    return render_version(policy, v3, "md").replace(b"every 18 months", b"every 12 months")


META = {
    "document_id": "AML-0107",
    "version": "4",
    "title": "Correspondent Banking Due Diligence",
    "domain": "aml",
    "owner": "MLRO",
    "valid_from": "2026-09-01",
    "acl_groups": "compliance",
}


async def test_upload_is_idempotent_by_hash(api_env: ApiEnv) -> None:
    blob = _aml0107_v4()
    async with await api_env.client("admin") as admin:
        first = await admin.post(
            "/v1/documents", data=META, files={"file": ("aml-0107-v4.md", blob, "text/markdown")}
        )
        second = await admin.post(
            "/v1/documents", data=META, files={"file": ("aml-0107-v4.md", blob, "text/markdown")}
        )
        big = await admin.post(
            "/v1/documents",
            data={**META, "version": "5"},
            files={"file": ("big.md", b"#" * (21 * 1024 * 1024), "text/markdown")},
        )
    assert first.status_code == 202, first.text
    assert first.json()["job_id"] == second.json()["job_id"]
    assert first.json()["document_id"] == "AML-0107" and first.json()["version"] == 4
    assert big.status_code == 413 and big.headers["content-type"].startswith("application/problem+json")
    state = api_env.app.state.crag
    assert await state.services.objects.exists("raw/AML-0107/v4.md")


async def test_upload_errors(api_env: ApiEnv) -> None:
    async with await api_env.client("admin") as admin:
        fake_pdf = await admin.post(
            "/v1/documents",
            data={**META, "version": "7"},
            files={"file": ("x.pdf", b"not a pdf at all", "application/pdf")},
        )
        exe = await admin.post(
            "/v1/documents",
            data={**META, "version": "7"},
            files={"file": ("x.exe", b"MZ....", "application/octet-stream")},
        )
        bad_id = await admin.post(
            "/v1/documents",
            data={**META, "document_id": "aml-107"},
            files={"file": ("x.md", b"# t", "text/markdown")},
        )
        changed = await admin.post(
            "/v1/documents",
            data={**META, "version": "1"},
            files={"file": ("x.md", b"# different bytes", "text/markdown")},
        )
        narrowed = await admin.post(
            "/v1/documents",
            data={**META, "version": "8", "acl_groups": "legal"},
            files={"file": ("x.md", b"# v8", "text/markdown")},
        )
    assert fake_pdf.status_code == 415 and exe.status_code == 415
    assert bad_id.status_code == 422
    assert changed.status_code == 409 and narrowed.status_code == 409
    async with await api_env.client("analyst") as analyst:
        denied = await analyst.post(
            "/v1/documents", data=META, files={"file": ("x.md", b"# t", "text/markdown")}
        )
    assert denied.status_code == 403


async def test_import_from_s3(api_env: ApiEnv) -> None:
    state = api_env.app.state.crag
    await state.services.objects.put("inbox/aml-0107-v9.md", _aml0107_v4() + b"\nv9")
    async with await api_env.client("admin") as admin:
        ok = await admin.post(
            "/v1/documents:from-s3", json={"key": "inbox/aml-0107-v9.md", "metadata": {**META, "version": 9}}
        )
        missing = await admin.post("/v1/documents:from-s3", json={"key": "inbox/nope.md", "metadata": META})
    assert ok.status_code == 202, ok.text
    assert missing.status_code == 404


async def test_library_and_versions_respect_acl(api_env: ApiEnv) -> None:
    async with await api_env.client("support") as support:
        page = (await support.get("/v1/documents", params={"domain": "complaints"})).json()
        hidden = await support.get("/v1/documents/CMP-0215")
    assert all(d["document_id"] != "CMP-0215" for d in page["items"])
    assert hidden.status_code == 404
    async with await api_env.client("legal") as legal:
        detail = await legal.get("/v1/documents/CMP-0215")
        page = (await legal.get("/v1/documents", params={"q": "litigation"})).json()
    assert detail.status_code == 200
    assert [v["version"] for v in detail.json()["versions"]] == [1, 2]
    assert detail.json()["versions"][0]["valid_to"] == "2025-09-01"
    assert any(d["document_id"] == "CMP-0215" and d["restricted"] for d in page["items"])
    async with await api_env.client("analyst") as analyst:
        first = (await analyst.get("/v1/documents", params={"limit": 2})).json()
        nxt = (await analyst.get("/v1/documents", params={"limit": 2, "cursor": first["next_cursor"]})).json()
        old = (await analyst.get("/v1/documents", params={"valid_at": "2023-01-01", "limit": 200})).json()
    assert len(first["items"]) == 2 and first["items"][-1]["document_id"] < nxt["items"][0]["document_id"]
    assert all(d["document_id"] != "KYC-0042" for d in old["items"])  # KYC-0042 starts in 2024


async def test_chunk_evidence_and_404_for_unauthorized(api_env: ApiEnv) -> None:
    state = api_env.app.state.crag
    async with state.services.pool.connection() as conn:
        restricted = (
            await (
                await conn.execute(
                    "SELECT chunk_id FROM chunks WHERE document_id = 'CMP-0215' AND valid_to IS NULL LIMIT 1"
                )
            ).fetchone()
        )[0]
        superseded = (
            await (
                await conn.execute(
                    "SELECT c.chunk_id FROM chunks c JOIN document_versions v ON v.id = c.version_id "
                    "WHERE c.document_id = 'KYC-0042' AND v.version = 2 LIMIT 1"
                )
            ).fetchone()
        )[0]
    async with await api_env.client("support") as support:
        assert (await support.get(f"/v1/chunks/{restricted}")).status_code == 404
        assert (await support.get("/v1/chunks/" + "0" * 32)).status_code == 404
    async with await api_env.client("analyst") as analyst:
        ev = await analyst.get(f"/v1/chunks/{superseded}")
    body = ev.json()
    assert ev.status_code == 200 and body["superseded"] is True and body["version"] == 2
    assert body["current_version"] == 3 and body["text"] and body["char_end"] > body["char_start"]
    async with state.services.pool.connection() as conn:
        n = (
            await (await conn.execute("SELECT count(*) FROM audit WHERE action = 'evidence_view'")).fetchone()
        )[0]
    assert n >= 1


async def test_inbox_poll_registers_sidecar_documents(api_env: ApiEnv) -> None:
    from compliance_rag.ingest.s3 import poll_inbox

    state = api_env.app.state.crag
    await state.services.objects.put("inbox/aml-0107-v11.md", _aml0107_v4() + b"\nv11")
    await state.services.objects.put("inbox/aml-0107-v11.json", json.dumps({**META, "version": 11}).encode())
    enqueued: list[str] = []
    result = await poll_inbox(state.services.ingest_deps(), enqueue=lambda job: enqueued.append(job.job_id))
    assert result.registered == 1 and len(enqueued) == 1
    assert not await state.services.objects.exists("inbox/aml-0107-v11.md")
    assert await state.services.objects.exists("processed/aml-0107-v11.md")


async def test_one_bad_inbox_file_does_not_block_the_others(api_env: ApiEnv) -> None:
    from compliance_rag.ingest.s3 import poll_inbox

    state = api_env.app.state.crag
    objects = state.services.objects
    # sorted first: an oversized file (would violate the size CHECK) and a malformed PDF
    await objects.put("inbox/aaa-huge.md", b"#" * (20 * 1024 * 1024 + 1))
    await objects.put("inbox/aaa-huge.json", json.dumps({**META, "version": 12}).encode())
    await objects.put("inbox/aab-bad.pdf", b"not a pdf")
    await objects.put("inbox/aab-bad.json", json.dumps({**META, "version": 13}).encode())
    await objects.put("inbox/aml-0107-v14.md", _aml0107_v4() + b"\nv14")
    await objects.put("inbox/aml-0107-v14.json", json.dumps({**META, "version": 14}).encode())
    enqueued: list[str] = []
    result = await poll_inbox(state.services.ingest_deps(), enqueue=lambda job: enqueued.append(job.job_id))
    assert (result.registered, result.failed) == (1, 2) and len(enqueued) == 1
    assert await objects.exists("failed/aaa-huge.md.error.txt")
    assert await objects.exists("failed/aab-bad.pdf.error.txt")
    assert await objects.exists("processed/aml-0107-v14.md")


async def test_inbox_keeps_files_when_the_queue_is_down(api_env: ApiEnv) -> None:
    from compliance_rag.ingest.s3 import poll_inbox

    objects = api_env.app.state.crag.services.objects
    await objects.put("inbox/aml-0107-v15.md", _aml0107_v4() + b"\nv15")
    await objects.put("inbox/aml-0107-v15.json", json.dumps({**META, "version": 15}).encode())

    def down(_job: object) -> None:
        raise ConnectionError("redis down")

    result = await poll_inbox(api_env.app.state.crag.services.ingest_deps(), enqueue=down)
    assert result.registered == 0 and result.failed == 0
    assert await objects.exists(
        "inbox/aml-0107-v15.md"
    )  # retried on the next poll (registration is idempotent)
    enqueued: list[str] = []
    again = await poll_inbox(
        api_env.app.state.crag.services.ingest_deps(), enqueue=lambda j: enqueued.append(j.job_id)
    )
    assert again.registered == 1 and len(enqueued) == 1


async def test_library_search_escapes_wildcards_and_hides_unfinished_versions(api_env: ApiEnv) -> None:
    blob = _aml0107_v4() + b"\npending-only"
    async with await api_env.client("admin") as admin:
        pending = await admin.post(
            "/v1/documents", data={**META, "version": "16"}, files={"file": ("v16.md", blob, "text/markdown")}
        )
        assert pending.status_code == 202
        admin_view = (await admin.get("/v1/documents/AML-0107")).json()
    async with await api_env.client("analyst") as analyst:
        wildcard = (await analyst.get("/v1/documents", params={"q": "%"})).json()
        underscore = (await analyst.get("/v1/documents", params={"q": "_"})).json()
        analyst_view = (await analyst.get("/v1/documents/AML-0107")).json()
    assert wildcard["items"] == [] and underscore["items"] == []  # literal characters, not wildcards
    assert 16 in {v["version"] for v in admin_view["versions"]}
    assert {v["status"] for v in analyst_view["versions"]} == {"active"}
