"""OpenTelemetry tracing (BUILD.md §14): HTTP server/client, Postgres (psycopg), Redis, Arq jobs, graph nodes.

Spans are exported over OTLP/HTTP when ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set (profile ``observability``);
otherwise the provider records nothing outside the process. Attributes never carry question or document text.
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import Event, ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import SpanKind, Status, StatusCode

from compliance_rag import __version__

_PROVIDER: TracerProvider | None = None
_LIBRARIES = False
tracer = trace.get_tracer("compliance_rag", __version__)


REDACTED = "[redacted]"
_QUERY_ATTRS = ("http.url", "url.full", "http.target", "url.query")


def _strip_query(key: str, value: Any) -> Any:
    if key == "url.query":
        return REDACTED
    return value.split("?", 1)[0] if isinstance(value, str) else value


def scrub_span(span: ReadableSpan) -> ReadableSpan:
    """Exception messages and stack traces can quote question or document text, and query strings can carry
    search terms: keep the exception type and the path, drop the rest."""
    attributes = {
        k: (_strip_query(k, v) if k in _QUERY_ATTRS else v) for k, v in (span.attributes or {}).items()
    }
    events = [
        Event(
            e.name,
            {
                k: (REDACTED if k in ("exception.message", "exception.stacktrace") else v)
                for k, v in (e.attributes or {}).items()
            },
            e.timestamp,
        )
        for e in span.events
    ]
    status = span.status
    if status.description:
        status = Status(status.status_code, status.description.split(":", 1)[0])
    return ReadableSpan(
        name=span.name,
        context=span.context,
        parent=span.parent,
        resource=span.resource,
        attributes=attributes,
        events=events,
        links=span.links,
        kind=span.kind,
        status=status,
        start_time=span.start_time,
        end_time=span.end_time,
        instrumentation_scope=span.instrumentation_scope,
    )


class ScrubbingExporter(SpanExporter):
    """Wraps the real exporter: every span is scrubbed before it leaves the process."""

    def __init__(self, inner: SpanExporter) -> None:
        self.inner = inner

    def export(self, spans: Any) -> SpanExportResult:
        return self.inner.export([scrub_span(s) for s in spans])

    def shutdown(self) -> None:
        self.inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self.inner.force_flush(timeout_millis)


def setup_tracing(service: str, endpoint: str | None = None) -> TracerProvider:
    """Install the process-wide provider once; later calls return it (and add the exporter if new)."""
    global _PROVIDER
    if _PROVIDER is None:
        _PROVIDER = TracerProvider(
            resource=Resource.create(
                {"service.name": f"compliance-rag-{service}", "service.version": __version__}
            )
        )
        trace.set_tracer_provider(_PROVIDER)
    if endpoint and not getattr(_PROVIDER, "_crag_otlp", False):
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        _PROVIDER.add_span_processor(
            BatchSpanProcessor(
                ScrubbingExporter(OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces"))
            )
        )
        _PROVIDER._crag_otlp = True  # type: ignore[attr-defined]
    return _PROVIDER


def instrument_libraries() -> None:
    """Client-side instrumentation: httpx (OpenSearch, Qdrant, OIDC JWKS), psycopg and Redis. Idempotent."""
    global _LIBRARIES
    if _LIBRARIES:
        return
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
    from opentelemetry.instrumentation.redis import RedisInstrumentor

    HTTPXClientInstrumentor().instrument()
    # statement text only (parameters are never captured): no question or chunk text in spans
    PsycopgInstrumentor().instrument(enable_commenter=False)
    RedisInstrumentor().instrument()
    _LIBRARIES = True


def instrument_app(app: Any) -> None:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    # health probes and metrics scrapes would drown the traces
    FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,readyz,metrics")


def traced_job[F: Callable[..., Awaitable[Any]]](fn: F) -> F:
    """One CONSUMER span per Arq job execution, named ``arq.<function>``."""

    @functools.wraps(fn)
    async def wrapper(ctx: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
        with tracer.start_as_current_span(f"arq.{fn.__name__}", kind=SpanKind.CONSUMER) as span:
            span.set_attribute("app.job", fn.__name__)
            span.set_attribute("app.job_try", int(ctx.get("job_try", 1) or 1))
            try:
                return await fn(ctx, *args, **kwargs)
            except Exception as exc:
                span.set_status(Status(StatusCode.ERROR, type(exc).__name__))
                raise

    return wrapper  # type: ignore[return-value]
