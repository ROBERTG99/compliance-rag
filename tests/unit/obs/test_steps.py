"""Step records and spans per graph node."""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from compliance_rag.graph.build import build_graph, run_graph
from tests.unit.graph.test_graph import ANALYST, ORION, cand, deps
from tests.unit.obs.conftest import spans_named

QUESTION = "What is the daily spending limit on the Orion Prepaid Card?"


async def _run(score: float) -> tuple[Any, dict[str, Any], list[dict[str, Any]]]:
    graph = build_graph(deps([cand("a", ORION)], score=score), InMemorySaver())
    events: list[dict[str, Any]] = []
    state = await run_graph(
        graph,
        question=QUESTION,
        principal=ANALYST,
        as_of="2026-10-16",
        emit=lambda e, d: events.append({"event": e, "data": d}),
    )
    return graph, state, events


def _graph_nodes(graph: Any) -> set[str]:
    return {n for n in graph.get_graph().nodes if not n.startswith("__")}


async def test_every_node_emits_step() -> None:
    graph, answered, answered_events = await _run(score=0.9)
    _, abstained, abstained_events = await _run(score=0.1)
    covered: set[str] = set()
    for state, events in ((answered, answered_events), (abstained, abstained_events)):
        node_steps = {s["node"] for s in state["steps"] if s["kind"] == "node"}
        reported = {
            e["data"]["node"] for e in events if e["event"] == "node" and e["data"]["status"] != "started"
        }
        assert reported <= node_steps, reported - node_steps  # every node that ran or was skipped has a step
        assert all(s["run_id"] == state["run_id"] for s in state["steps"])
        assert [s["step"] for s in state["steps"]] == list(range(len(state["steps"])))
        covered |= node_steps
    assert _graph_nodes(graph) <= covered
    llm = [s for s in answered["steps"] if s["kind"] == "llm"]
    assert llm and llm[0]["prompt_version"] and llm[0]["model"] == "fake"


async def test_every_node_emits_a_span_with_app_and_gen_ai_attributes(spans: InMemorySpanExporter) -> None:
    _graph, state, _ = await _run(score=0.9)
    ran = {s["node"] for s in state["steps"] if s["kind"] == "node" and s["status"] == "ok"}
    for node in ran:
        (span,) = spans_named(spans, f"graph.{node}")
        assert span.attributes["app.run_id"] == state["run_id"]
        assert span.attributes["app.node"] == node
    (llm,) = spans_named(spans, "gen_ai.generate")
    assert llm.attributes["gen_ai.operation.name"] == "chat"
    assert llm.attributes["gen_ai.request.model"] == "fake"
    assert llm.attributes["gen_ai.usage.input_tokens"] == 0
    assert llm.attributes["app.prompt_version"]
    # never the question or document text in span attributes
    assert all(
        QUESTION not in str(v) for s in spans.get_finished_spans() for v in (s.attributes or {}).values()
    )
