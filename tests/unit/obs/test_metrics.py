"""Prometheus metrics named in BUILD.md §14 and the SLO alert rules (T-44)."""

from __future__ import annotations

from pathlib import Path

import yaml
from langgraph.checkpoint.memory import InMemorySaver
from prometheus_client import REGISTRY, generate_latest

from compliance_rag.graph.build import build_graph, run_graph
from compliance_rag.obs.metrics import ACL_POSTCHECK_VIOLATIONS
from tests.unit.graph.test_graph import ANALYST, ORION, cand, deps
from tests.unit.retrieval.test_hybrid import AS_OF, SUPPORT, FakeBM25, FakeVector, retriever
from tests.unit.retrieval.test_hybrid import cand as hcand

ROOT = Path(__file__).resolve().parents[3]
SPEC_METRICS = [
    "crag_retrieval_seconds",
    "crag_ttft_seconds",
    "crag_llm_tokens_total",
    "crag_llm_cost_usd_total",
    "crag_abstentions_total",
    "crag_claims_rejected_total",
    "crag_acl_postcheck_violations_total",
    "crag_ingestion_lag_seconds",
]


async def test_acl_violation_counter() -> None:
    before = ACL_POSTCHECK_VIOLATIONS._value.get()
    leaked = hcand("leak", bm25=10.0, groups=["legal"])  # a backend that ignored the filter
    result = await retriever(FakeBM25([leaked, hcand("ok", bm25=1.0)]), FakeVector([])).retrieve(
        "q", SUPPORT, AS_OF
    )
    assert [c["chunk_id"] for c in result.fused] == ["ok"]
    assert ACL_POSTCHECK_VIOLATIONS._value.get() == before + 1
    assert b"crag_acl_postcheck_violations_total" in generate_latest()


def test_every_spec_metric_is_exported() -> None:
    names = {m.name for m in REGISTRY.collect()}
    for name in SPEC_METRICS:
        assert name.removesuffix("_total") in names, name


async def test_a_run_observes_total_retrieval_latency() -> None:
    def total_count() -> float:
        return REGISTRY.get_sample_value("crag_retrieval_seconds_count", {"leg": "total"}) or 0.0

    before = total_count()
    graph = build_graph(deps([cand("a", ORION)], score=0.9), InMemorySaver())
    await run_graph(graph, question="What is the daily limit?", principal=ANALYST, as_of="2026-10-16")
    assert total_count() == before + 1


def test_slo_alert_rules() -> None:
    rules = yaml.safe_load((ROOT / "deploy/prometheus/alerts.yml").read_text())
    alerts = {r["alert"]: r for g in rules["groups"] for r in g["rules"]}
    assert set(alerts) == {
        "CragRetrievalSlow",
        "CragIngestionLag",
        "CragWorkerDown",
        "CragAclViolation",
        "CragCitationRejects",
    }
    assert 'stat="oldest_pending"' in alerts["CragIngestionLag"]["expr"]  # a stuck queue fires too
    assert 'absent(up{job="worker"})' in alerts["CragWorkerDown"]["expr"]
    assert (
        'leg="total"' in alerts["CragRetrievalSlow"]["expr"] and "0.3" in alerts["CragRetrievalSlow"]["expr"]
    )
    assert "[1h]" in alerts["CragRetrievalSlow"]["expr"]
    assert (
        "crag_ingestion_lag_seconds" in alerts["CragIngestionLag"]["expr"]
        and "300" in alerts["CragIngestionLag"]["expr"]
    )
    acl = alerts["CragAclViolation"]
    assert "crag_acl_postcheck_violations_total" in acl["expr"] and acl.get("for", "0m") == "0m"
    assert acl["labels"]["severity"] == "page"
    assert "0.2" in alerts["CragCitationRejects"]["expr"] and "[1h]" in alerts["CragCitationRejects"]["expr"]
