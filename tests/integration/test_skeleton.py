"""Walking skeleton: the API answers through the FakeLLM path (T-08, FR-8)."""

import httpx

from compliance_rag.api.app import create_app


async def test_ask_returns_fake_answer() -> None:
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        health = await client.get("/healthz")
        assert health.status_code == 200
        resp = await client.post(
            "/v1/ask",
            json={"question": "What is the maximum age of a proof-of-address document?", "stream": False},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["label"] == "AI-generated"
    assert body["abstained"] is False
    assert body["claims"] and body["claims"][0]["citations"]
