"""Walking skeleton → real API: an authenticated ask answers through the FakeLLM path."""

import pytest

from tests.fixtures_services import ApiEnv

pytestmark = pytest.mark.integration


async def test_ask_returns_fake_answer(api_env: ApiEnv) -> None:
    async with await api_env.client("analyst") as client:
        health = await client.get("/healthz")
        ready = await client.get("/readyz")
        me = await client.get("/v1/me")
        resp = await client.post(
            "/v1/ask",
            json={"question": "What is the maximum age of a proof-of-address document?", "stream": False},
        )
    assert health.status_code == 200 and ready.status_code == 200
    assert me.json()["role"] == "analyst"
    assert resp.status_code == 200
    body = resp.json()
    assert body["label"] == "AI-generated" and body["abstained"] is False
    assert body["claims"] and body["claims"][0]["citations"]
