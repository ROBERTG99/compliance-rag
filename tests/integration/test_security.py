"""No question, answer or restricted document text in logs or spans (BUILD.md §14–15, T-45)."""

from __future__ import annotations

import pytest
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from compliance_rag.obs.logging import configure_logging
from compliance_rag.obs.tracing import ScrubbingExporter, setup_tracing
from tests.fixtures_services import ApiEnv

pytestmark = pytest.mark.integration
RESTRICTED_Q = "How long are complaint files under a litigation hold preserved after the hold is lifted?"


async def test_no_restricted_text_in_logs(api_env: ApiEnv, capfd: pytest.CaptureFixture[str]) -> None:
    configure_logging("DEBUG", service="api")  # the most verbose setting must still be clean
    exporter = InMemorySpanExporter()
    setup_tracing("api").add_span_processor(SimpleSpanProcessor(ScrubbingExporter(exporter)))  # as exported
    capfd.readouterr()

    async with await api_env.client("legal") as legal:
        answer = (
            await legal.post(
                "/v1/ask", json={"question": RESTRICTED_Q, "stream": False, "as_of": "2026-10-16"}
            )
        ).json()
        citation = answer["claims"][0]["citations"][0]
        evidence = (await legal.get(f"/v1/chunks/{citation['chunk_id']}")).json()
        accepted = (
            await legal.post(
                "/v1/ask", json={"question": RESTRICTED_Q, "stream": True, "as_of": "2026-10-16"}
            )
        ).json()
        streamed = (await legal.get(accepted["events_url"])).text
        await legal.post(
            "/v1/feedback",
            json={
                "run_id": answer["run_id"],
                "rating": "down",
                "reason": "other",
                "comment": "hold period unclear",
            },
        )
        await legal.get("/v1/documents", params={"q": "litigation hold"})  # search terms are text too
        too_long = await legal.post("/v1/ask", json={"question": RESTRICTED_Q * 30, "stream": False})
        assert too_long.status_code == 422  # an error path
    async with await api_env.client("support") as support:
        await support.post("/v1/ask", json={"question": RESTRICTED_Q, "stream": False, "as_of": "2026-10-16"})
        await support.get(f"/v1/chunks/{citation['chunk_id']}")  # 404

    assert "CMP-0215" in str(answer) and "claim" in streamed  # the run itself worked
    captured = capfd.readouterr()
    logs = captured.out + captured.err  # stdlib loggers (uvicorn, httpx, arq) included
    assert '"event"' in logs  # something was logged
    secrets = {
        "question": RESTRICTED_Q,
        "answer": answer["answer"][:60],
        "quote": citation["quote"][:60],
        "chunk": evidence["text"][200:260],
        "comment": "hold period unclear",
        "search": "litigation hold",
    }
    for name, text in secrets.items():
        assert text not in logs, f"{name} text in logs"
    attributes = " ".join(
        str(v) for s in exporter.get_finished_spans() for v in (s.attributes or {}).values()
    )
    assert exporter.get_finished_spans()
    for name, text in secrets.items():
        assert text not in attributes, f"{name} text in span attributes or events"
