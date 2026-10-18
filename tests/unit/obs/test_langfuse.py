"""Langfuse (profile `langfuse`): one generation per LLM call, numbers only — never prompt or answer text."""

from __future__ import annotations

import base64
import json
from typing import Any

import httpx

from compliance_rag.llm.gateway import LLMResult
from compliance_rag.obs.langfuse import LangfuseReporter

RESULT = LLMResult(
    text='{"claims": [{"text": "Complaint files under a litigation hold are kept 7 years."}]}',
    parsed={},
    model="claude-opus-5-5",
    route="generate",
    prompt_name="generate_answer",
    prompt_version="1",
    input_tokens=1200,
    output_tokens=300,
    cost_usd=0.0108,
    latency_ms=812.5,
    stop_reason="end_turn",
    outcome="ok",
)


async def test_a_generation_is_reported_without_text() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(207, json={"successes": [], "errors": []})

    reporter = LangfuseReporter(
        "http://langfuse:3000", "pk-lf-dev", "sk-lf-dev", transport=httpx.MockTransport(handler)
    )
    await reporter.report(RESULT, run_id="run-1")
    await reporter.close()
    (request,) = seen
    assert request.url.path == "/api/public/ingestion"
    assert request.headers["authorization"] == "Basic " + base64.b64encode(b"pk-lf-dev:sk-lf-dev").decode()
    (event,) = json.loads(request.content)["batch"]
    body: dict[str, Any] = event["body"]
    assert event["type"] == "generation-create" and body["traceId"] == "run-1"
    assert body["model"] == "claude-opus-5-5" and body["name"] == "generate"
    assert body["usage"] == {"input": 1200, "output": 300, "unit": "TOKENS"}
    assert body["metadata"]["prompt_version"] == "1" and body["metadata"]["cost_usd"] == 0.0108
    assert "litigation" not in request.content.decode()


async def test_failures_never_reach_the_caller() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    reporter = LangfuseReporter("http://langfuse:3000", "pk", "sk", transport=httpx.MockTransport(handler))
    await reporter.report(RESULT, run_id=None)  # no exception
    await reporter.close()


async def test_the_gateway_reports_each_call_when_configured(monkeypatch: Any) -> None:
    import asyncio

    from compliance_rag.llm.gateway import Gateway, LLMRequest
    from compliance_rag.obs import langfuse
    from compliance_rag.settings import Settings

    reported: list[str] = []

    class Spy:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def report(self, result: LLMResult, *, run_id: str | None) -> None:
            reported.append(result.route)

    monkeypatch.setattr(langfuse, "LangfuseReporter", Spy)
    settings = Settings(
        _env_file=None,
        langfuse_host="http://langfuse:3000",
        langfuse_public_key="pk",
        langfuse_secret_key="sk",  # type: ignore[arg-type]
    )
    req = LLMRequest(
        route="condense_followup",
        system="s",
        user="u",
        schema=None,
        schema_name=None,
        prompt_name="condense_followup",
        prompt_version="1",
        data={"question": "And v2?", "previous_question": "What is the PoA age?"},
    )
    await Gateway(settings).stream(req)
    await asyncio.sleep(0)
    assert reported == ["condense_followup"]
    await Gateway(Settings(_env_file=None)).stream(req)  # not configured: nothing reported
    await asyncio.sleep(0)
    assert reported == ["condense_followup"]
