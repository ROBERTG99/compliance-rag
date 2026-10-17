"""In-memory span capture for observability tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from compliance_rag.obs.tracing import ScrubbingExporter, setup_tracing

_EXPORTER = InMemorySpanExporter()


@pytest.fixture
def spans() -> Iterator[InMemorySpanExporter]:
    provider = setup_tracing("crag-test")
    if not getattr(provider, "_crag_test_exporter", False):
        provider.add_span_processor(SimpleSpanProcessor(ScrubbingExporter(_EXPORTER)))  # as in production
        provider._crag_test_exporter = True  # type: ignore[attr-defined]
    _EXPORTER.clear()
    yield _EXPORTER
    _EXPORTER.clear()


def spans_named(exporter: InMemorySpanExporter, name: str) -> list[ReadableSpan]:
    return [s for s in exporter.get_finished_spans() if s.name == name]
