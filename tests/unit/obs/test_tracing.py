"""Spans for HTTP (server and client), Arq jobs and the database driver (BUILD.md §14, T-43)."""

from __future__ import annotations

import httpx
from fastapi import FastAPI
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind

from compliance_rag.obs.tracing import instrument_app, instrument_libraries, traced_job
from tests.unit.obs.conftest import spans_named


async def test_http_server_and_client_spans(spans: InMemorySpanExporter) -> None:
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

    app = FastAPI()

    @app.get("/v1/things/{thing_id}")
    async def thing(thing_id: str) -> dict[str, str]:
        # OpenSearch and Qdrant are reached over httpx; a mock transport needs the per-client hook
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200))) as c:
            HTTPXClientInstrumentor.instrument_client(c)
            await c.get("http://opensearch:9200/_search")
        return {"id": thing_id}

    instrument_app(app)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api") as client:
        assert (await client.get("/v1/things/42")).status_code == 200
        assert (await client.get("/healthz")).status_code == 404  # excluded from tracing either way
    finished = spans.get_finished_spans()
    server = [s for s in finished if s.kind == SpanKind.SERVER]
    assert len(server) == 1 and server[0].attributes["http.route"] == "/v1/things/{thing_id}"
    outgoing = [s for s in finished if s.kind == SpanKind.CLIENT]
    assert outgoing and outgoing[0].parent is not None  # the client call is a child of the request
    assert outgoing[0].parent.trace_id == server[0].context.trace_id


async def test_arq_jobs_run_in_a_span(spans: InMemorySpanExporter) -> None:
    @traced_job
    async def ingest_document(ctx: dict[str, object], job_id: str) -> str:
        return job_id

    assert await ingest_document({"job_try": 2}, "j-1") == "j-1"
    (span,) = spans_named(spans, "arq.ingest_document")
    assert span.kind == SpanKind.CONSUMER
    assert span.attributes["app.job"] == "ingest_document" and span.attributes["app.job_try"] == 2


def test_client_libraries_are_instrumented() -> None:
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
    from opentelemetry.instrumentation.redis import RedisInstrumentor

    instrument_libraries()
    for instrumentor in (HTTPXClientInstrumentor(), PsycopgInstrumentor(), RedisInstrumentor()):
        assert instrumentor.is_instrumented_by_opentelemetry, type(instrumentor).__name__


async def test_exported_spans_carry_no_query_strings_or_exception_messages(
    spans: InMemorySpanExporter,
) -> None:
    app = FastAPI()

    @app.get("/v1/documents")
    async def search(q: str = "") -> dict[str, str]:
        return {"q": "ok"}

    @app.get("/boom")
    async def boom() -> dict[str, str]:
        raise RuntimeError("How long are complaint files under a litigation hold preserved?")

    instrument_app(app)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://api") as client:
        await client.get("/v1/documents", params={"q": "litigation hold"})
        await client.get("/boom")
    exported = " ".join(
        f"{s.attributes} {[(e.name, e.attributes) for e in s.events]}" for s in spans.get_finished_spans()
    )
    assert "litigation" not in exported
    assert "RuntimeError" in exported  # the exception type is kept for debugging
