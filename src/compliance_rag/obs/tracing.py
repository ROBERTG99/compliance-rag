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
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import SpanKind, Status, StatusCode

from compliance_rag import __version__

_PROVIDER: TracerProvider | None = None
_LIBRARIES = False
tracer = trace.get_tracer("compliance_rag", __version__)


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
            BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces"))
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
