"""Streaming answers over SSE with Last-Event-ID resume (FR-10, T-27)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.fixtures_services import ApiEnv

pytestmark = pytest.mark.integration
QUESTION = "What is the maximum age of a proof-of-address document?"


def parse_sse(text: str) -> list[dict[str, Any]]:
    events = []
    for block in text.strip().split("\n\n"):
        fields: dict[str, Any] = {}
        for line in block.splitlines():
            if line.startswith(":"):
                continue
            key, _, value = line.partition(": ")
            fields[key] = value
        if "event" in fields:
            events.append(
                {"id": int(fields["id"]), "event": fields["event"], "data": json.loads(fields["data"])}
            )
    return events


async def _stream(env: ApiEnv, persona: str = "analyst", **body: Any) -> tuple[str, list[dict[str, Any]]]:
    async with await env.client(persona) as client:
        resp = await client.post("/v1/ask", json={"question": QUESTION, "stream": True, **body})
        assert resp.status_code == 202, resp.text
        run_id = resp.json()["run_id"]
        assert resp.json()["events_url"] == f"/v1/runs/{run_id}/events"
        events = await client.get(f"/v1/runs/{run_id}/events")
        assert events.headers["content-type"].startswith("text/event-stream")
        return run_id, parse_sse(events.text)


async def test_resume_with_last_event_id(api_env: ApiEnv) -> None:
    run_id, events = await _stream(api_env)
    assert events[0]["event"] == "run_started" and events[-1]["event"] == "final"
    assert [e["id"] for e in events] == list(range(1, len(events) + 1))
    assert len(events) > 5
    async with await api_env.client("analyst") as client:
        resumed = await client.get(f"/v1/runs/{run_id}/events", headers={"Last-Event-ID": "4"})
    replay = parse_sse(resumed.text)
    assert [e["id"] for e in replay] == [e["id"] for e in events[4:]]
    assert replay == events[4:]


async def test_stream_event_contract(api_env: ApiEnv) -> None:
    _, events = await _stream(api_env, as_of="2026-10-16")
    kinds = [e["event"] for e in events]
    assert "retrieval" in kinds and "claim" in kinds and "token" in kinds
    assert kinds.index("claim") < kinds.index("final")
    final = events[-1]["data"]
    assert final["as_of"] == "2026-10-16" and final["label"] == "AI-generated" and not final["abstained"]
    assert final["versions"][0]["document_id"] == "KYC-0042" and final["versions"][0]["version"] == 3
    assert "90" in final["answer"]
    started = events[0]["data"]
    assert started["role"] == "analyst" and started["run_id"] == final["run_id"]
    # tokens only ever carry text of verified claims
    claim_texts = {e["data"]["index"]: e["data"]["text"] for e in events if e["event"] == "claim"}
    for e in events:
        if e["event"] == "token":
            assert e["data"]["text"].strip() in claim_texts[e["data"]["claim_index"]]


async def test_as_of_selects_superseded_version(api_env: ApiEnv) -> None:
    _, events = await _stream(api_env, as_of="2025-12-31")
    final = events[-1]["data"]
    assert final["versions"][0]["version"] == 2 and final["versions"][0]["superseded"] is True
    assert "120" in final["answer"]


async def test_events_are_private_to_the_run_owner(api_env: ApiEnv) -> None:
    run_id, _ = await _stream(api_env)
    async with await api_env.client("legal") as other:
        assert (await other.get(f"/v1/runs/{run_id}/events")).status_code == 404
        assert (await other.get(f"/v1/runs/{run_id}")).status_code == 404
    async with await api_env.client("analyst") as owner:
        stored = await owner.get(f"/v1/runs/{run_id}")
    assert stored.status_code == 200 and stored.json()["run_id"] == run_id and stored.json()["steps"]
