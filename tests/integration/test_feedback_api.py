"""Feedback, triage and the audit chain."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from compliance_rag.db.audit import verify_chain
from tests.fixtures_services import ApiEnv

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


def _first_test_question() -> str:
    for line in (ROOT / "evals/datasets/questions.v1.jsonl").read_text().splitlines():
        row = json.loads(line)
        if row["split"] == "test":
            return str(row["input"]["question"])
    raise AssertionError("no test-split question")


async def _ask(env: ApiEnv, persona: str, question: str) -> str:
    async with await env.client(persona) as client:
        resp = await client.post("/v1/ask", json={"question": question, "stream": False})
    assert resp.status_code == 200, resp.text
    return str(resp.json()["run_id"])


async def _audit_rows(env: ApiEnv, action: str, target: str) -> list[dict[str, Any]]:
    async with env.app.state.crag.services.pool.connection() as conn:
        cur = await conn.execute(
            "SELECT actor_sub, details FROM audit WHERE action = %s AND target = %s ORDER BY seq",
            (action, target),
        )
        return [{"actor_sub": r[0], "details": r[1]} for r in await cur.fetchall()]


async def test_feedback_upsert_per_user(api_env: ApiEnv) -> None:
    run_id = await _ask(api_env, "analyst", "What is the maximum age of a proof-of-address document?")
    body = {"run_id": run_id, "rating": "down", "reason": "outdated", "comment": "v2 still applies?"}
    async with await api_env.client("analyst") as analyst:
        first = await analyst.post("/v1/feedback", json=body)
        second = await analyst.post("/v1/feedback", json={**body, "rating": "up", "reason": "correct"})
        bad = await analyst.post("/v1/feedback", json={**body, "reason": "rude"})
        unknown = await analyst.post("/v1/feedback", json={**body, "run_id": str(uuid.uuid4())})
    assert first.status_code == 201, first.text
    assert second.status_code == 200, second.text
    assert first.json()["id"] == second.json()["id"]
    assert second.json()["rating"] == "up" and second.json()["reason"] == "correct"
    assert bad.status_code == 422 and unknown.status_code == 404
    assert bad.headers["content-type"].startswith("application/problem+json")

    # another user's run looks like a missing run (no existence leak)
    async with await api_env.client("support") as support:
        foreign = await support.post("/v1/feedback", json=body)
    assert foreign.status_code == 404

    async with api_env.app.state.crag.services.pool.connection() as conn:
        cur = await conn.execute("SELECT count(*) FROM feedback WHERE run_id = %s", (run_id,))
        assert (await cur.fetchone())[0] == 1

    audit = await _audit_rows(api_env, "feedback", run_id)
    assert len(audit) == 2
    # comment text is user content: never in the audit log
    assert all("comment" not in row["details"] for row in audit)


async def test_triage_into_dev_split_only(api_env: ApiEnv) -> None:
    dev_run = await _ask(api_env, "legal", "What is the maximum age of a proof-of-address document?")
    test_run = await _ask(api_env, "legal", _first_test_question())
    ids: dict[str, str] = {}
    async with await api_env.client("legal") as legal:
        for name, run in (("dev", dev_run), ("test", test_run)):
            resp = await legal.post(
                "/v1/feedback", json={"run_id": run, "rating": "down", "reason": "wrong_fact"}
            )
            assert resp.status_code == 201, resp.text
            ids[name] = resp.json()["id"]
        # triage is content_admin only
        assert (
            await legal.patch(f"/v1/feedback/{ids['dev']}", json={"status": "triaged"})
        ).status_code == 403
        assert (await legal.get("/v1/feedback")).status_code == 403

    async with await api_env.client("admin") as admin:
        listed = await admin.get("/v1/feedback", params={"status": "new", "rating": "down"})
        assert listed.status_code == 200
        assert {ids["dev"], ids["test"]} <= {item["id"] for item in listed.json()["items"]}
        assert all(item["status"] == "new" for item in listed.json()["items"])

        triaged = await admin.patch(f"/v1/feedback/{ids['dev']}", json={"status": "triaged"})
        added = await admin.patch(f"/v1/feedback/{ids['dev']}", json={"status": "added_to_dev_set"})
        to_test = await admin.patch(
            f"/v1/feedback/{ids['dev']}", json={"status": "added_to_dev_set", "split": "test"}
        )
        leak = await admin.patch(f"/v1/feedback/{ids['test']}", json={"status": "added_to_dev_set"})
        missing = await admin.patch(f"/v1/feedback/{uuid.uuid4()}", json={"status": "triaged"})
        invalid = await admin.patch(f"/v1/feedback/{ids['dev']}", json={"status": "deleted"})
    assert triaged.status_code == 200 and triaged.json()["status"] == "triaged"
    assert added.status_code == 200 and added.json()["status"] == "added_to_dev_set"
    assert to_test.status_code == 422  # the contract only admits split "dev"
    # a question from the held-out test split can never be copied into the dev set
    assert leak.status_code == 422 and leak.json()["code"] == "test_split_triage"
    assert missing.status_code == 404 and invalid.status_code == 422

    assert len(await _audit_rows(api_env, "feedback_triage", ids["dev"])) == 2
    assert await _audit_rows(api_env, "feedback_triage", ids["test"]) == []
    async with api_env.app.state.crag.services.pool.connection() as conn:
        assert (await verify_chain(conn)).ok
