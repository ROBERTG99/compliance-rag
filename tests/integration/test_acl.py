"""ACL before retrieval and no existence leakage (FR-11, T-27)."""

from __future__ import annotations

import pytest

from tests.fixtures_services import ApiEnv

pytestmark = pytest.mark.integration
RESTRICTED_Q = "How long are complaint files under a litigation hold preserved after the hold is lifted?"
UNKNOWN_Q = "How long are pet insurance claims for the Zephyr Crypto Wallet preserved after closure?"
VOLATILE = {"run_id", "conversation_id", "latency_ms"}


async def _ask(env: ApiEnv, persona: str, question: str) -> dict:
    async with await env.client(persona) as client:
        resp = await client.post(
            "/v1/ask", json={"question": question, "stream": False, "as_of": "2026-10-16"}
        )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_abstention_does_not_reveal_restricted_documents(api_env: ApiEnv) -> None:
    legal = await _ask(api_env, "legal", RESTRICTED_Q)
    assert not legal["abstained"] and legal["versions"][0]["document_id"] == "CMP-0215"
    restricted = await _ask(api_env, "support", RESTRICTED_Q)
    unknown = await _ask(api_env, "support", UNKNOWN_Q)
    assert restricted["abstained"] and unknown["abstained"]
    strip = lambda body: {k: v for k, v in body.items() if k not in VOLATILE}  # noqa: E731
    assert strip(restricted) == strip(unknown)
    assert "CMP-0215" not in str(restricted) and "litigation" not in restricted["message"].lower()
    assert restricted["cost_usd"] is None
    # FR-11: the restricted evidence itself is a 404 (not 403) for support
    chunk_id = legal["claims"][0]["citations"][0]["chunk_id"]
    async with await api_env.client("support") as support:
        assert (await support.get(f"/v1/chunks/{chunk_id}")).status_code == 404
    async with await api_env.client("legal") as legal_client:
        assert (await legal_client.get(f"/v1/chunks/{chunk_id}")).status_code == 200


async def test_follow_up_requires_the_same_owner(api_env: ApiEnv) -> None:
    first = await _ask(api_env, "analyst", "What is the maximum age of a proof-of-address document?")
    async with await api_env.client("support") as other:
        resp = await other.post(
            "/v1/ask",
            json={"question": "And for older versions?", "stream": False, "follow_up_of": first["run_id"]},
        )
    assert resp.status_code == 404
    async with await api_env.client("analyst") as owner:
        resp = await owner.post(
            "/v1/ask",
            json={"question": "Who owns that policy?", "stream": False, "follow_up_of": first["run_id"]},
        )
    assert resp.status_code == 200 and resp.json()["conversation_id"] == first["conversation_id"]


async def test_future_as_of_is_rejected_for_non_admins(api_env: ApiEnv) -> None:
    async with await api_env.client("analyst") as client:
        resp = await client.post("/v1/ask", json={"question": "q?", "stream": False, "as_of": "2099-01-01"})
    assert resp.status_code == 422 and resp.headers["content-type"].startswith("application/problem+json")


async def test_requests_without_a_valid_token_get_401_problem(api_env: ApiEnv) -> None:
    async with await api_env.client() as anon:
        resp = await anon.post("/v1/ask", json={"question": "q?", "stream": False})
        bad = await anon.get("/v1/me", headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 401 and bad.status_code == 401
    assert resp.json()["status"] == 401 and resp.headers["content-type"].startswith(
        "application/problem+json"
    )
