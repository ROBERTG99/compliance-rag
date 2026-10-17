"""The eval summary (`evals/reports/latest.json`) and `evals/REPORT.md` are rendered from run reports only."""

from __future__ import annotations

from typing import Any

from compliance_rag.evals.reporting import by_category, render_report, slim_baseline, summarize


def _metric(value: float, unit: str = "rate", passed: bool = True, gate: bool = True) -> dict[str, Any]:
    return {
        "value": value,
        "n": 2,
        "unit": unit,
        "threshold_text": "≥ 0.9",
        "gate": gate,
        "hard": False,
        "higher_is_better": True,
        "passed": passed,
    }


def _report(suite: str, metrics: dict[str, Any], passed: bool = True) -> dict[str, Any]:
    return {
        "schema": "evalgate.report.v1",
        "suite": suite,
        "split": "test",
        "generated_at": "2026-10-17T10:00:00+00:00",
        "duration_s": 3.0,
        "dataset": {"path": "d.jsonl", "sha256": "ab" * 32, "n": 2},
        "target": {"llm": "FakeLLM (offline)"},
        "metrics": metrics,
        "errors": 0,
        "passed": passed,
        "cases": [
            {"id": "single_hop-001", "error": None, "scores": {"key_fact_accuracy": 1.0, "p95": 10.0}},
            {"id": "single_hop-002", "error": None, "scores": {"key_fact_accuracy": 0.0, "p95": 30.0}},
            {"id": "acl_probe-001", "error": None, "scores": {"key_fact_accuracy": None, "p95": 20.0}},
        ],
    }


RAG = _report(
    "rag",
    {"key_fact_accuracy": _metric(0.5, passed=False), "retrieval_p95": _metric(120.0, "ms")},
    passed=False,
)
RETRIEVAL = _report("retrieval", {"recall@10": _metric(0.96)})
ABLATION = [{"config": "bm25", "recall@10": 0.8, "mrr@10": 0.7, "p95_ms": 40.0}]


def test_summary_flattens_metrics_with_unit_suffixes_and_suite_prefixes() -> None:
    latest = summarize([RAG, RETRIEVAL], ablation=ABLATION)
    assert latest["metrics"] == {
        "key_fact_accuracy": 0.5,
        "retrieval_p95_ms": 120.0,
        "retrieval.recall@10": 0.96,
    }
    assert latest["llm"] == "FakeLLM (offline)"
    assert latest["split"] == "test"
    assert latest["passed"] is False
    assert latest["ablation"] == ABLATION
    assert "cases" not in latest["suites"]["rag"]


def test_by_category_averages_mean_metrics_per_question_category() -> None:
    cats = by_category(RAG, metrics=["key_fact_accuracy"])
    assert cats["single_hop"] == {"n": 2, "key_fact_accuracy": 0.5}
    assert cats["acl_probe"] == {"n": 1, "key_fact_accuracy": None}


def test_report_labels_offline_numbers_and_lists_every_section() -> None:
    latest = summarize(
        [RAG, RETRIEVAL],
        ablation=ABLATION,
        redteam={"total": 4, "failures": 0, "document_answered": {"answered": 2, "of": 3}},
    )
    text = render_report(latest, failures=["[rag] key_fact_accuracy = 0.5000 violates ≥ 0.9"])
    assert "FakeLLM" in text and "make eval" in text
    assert "## Suite `rag`: FAIL" in text
    assert "| key_fact_accuracy | 0.500 |" in text
    assert "| retrieval_p95 | 120 ms |" in text
    assert "## Retrieval ablation" in text and "| bm25 | 0.800 | 0.700 | 40 ms |" in text
    assert "## Red-team" in text and "0 failures" in text and "2 of 3" in text
    assert "## By question category (`rag`)" in text
    assert "key_fact_accuracy = 0.5000 violates" in text


def test_report_without_optional_sections_says_how_to_produce_them() -> None:
    text = render_report(summarize([RETRIEVAL]), failures=[])
    assert "make eval-ablation" in text and "make redteam" in text
    assert "All gates pass" in text


def test_baseline_keeps_only_metric_values() -> None:
    base = slim_baseline([RAG, RETRIEVAL])
    assert base["rag"]["metrics"]["key_fact_accuracy"]["value"] == 0.5
    assert base["rag"]["suite"] == "rag"
    assert "cases" not in base["rag"]
