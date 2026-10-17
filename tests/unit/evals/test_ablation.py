"""`make eval-ablation`: five retrieval configurations on the test split (BUILD.md §11, T-40)."""

from __future__ import annotations

from typing import Any

from scripts.ablation import CONFIGS, ablation_row, run_ablation


def test_five_configurations() -> None:
    assert [c.name for c in CONFIGS] == [
        "bm25",
        "vector-pgvector",
        "vector-qdrant",
        "hybrid",
        "hybrid+rerank",
    ]
    by_name = {c.name: c.system for c in CONFIGS}
    assert by_name["bm25"] == {"bm25": True, "vector": False, "rerank": False}
    assert by_name["vector-pgvector"] == {
        "bm25": False,
        "vector": True,
        "vector_store": "pgvector",
        "rerank": False,
    }
    assert by_name["vector-qdrant"] == {
        "bm25": False,
        "vector": True,
        "vector_store": "qdrant",
        "rerank": False,
    }
    assert by_name["hybrid"] == {"bm25": True, "vector": True, "vector_store": "pgvector", "rerank": False}
    assert by_name["hybrid+rerank"] == {
        "bm25": True,
        "vector": True,
        "vector_store": "pgvector",
        "rerank": True,
    }


def _report(recall: float) -> dict[str, Any]:
    m = {"unit": "rate"}
    return {
        "suite": "retrieval",
        "split": "test",
        "generated_at": "2026-10-17T10:00:00+00:00",
        "target": {"reranker": "feature"},
        "errors": 0,
        "metrics": {
            "recall@10": {**m, "value": recall, "n": 88},
            "mrr@10": {**m, "value": recall / 2},
            "retrieval_p95": {"unit": "ms", "value": 42.0},
            "degraded_rate": {**m, "value": 0.0},
        },
    }


def test_rows_copy_the_report_values() -> None:
    assert ablation_row("bm25", _report(0.8)) == {
        "config": "bm25",
        "n": 88,
        "recall@10": 0.8,
        "mrr@10": 0.4,
        "p95_ms": 42.0,
        "degraded_rate": 0.0,
    }


async def test_run_ablation_runs_every_configuration_in_order() -> None:
    seen: list[dict[str, Any]] = []

    async def fake_run(system: dict[str, Any]) -> dict[str, Any]:
        seen.append(system)
        return _report(0.5 + 0.1 * len(seen))

    result = await run_ablation(fake_run)
    rows = result["rows"]
    assert [r["config"] for r in rows] == [c.name for c in CONFIGS]
    assert seen == [c.system for c in CONFIGS]
    assert rows[-1]["recall@10"] == 1.0
    assert result["split"] == "test" and result["target"] == {"reranker": "feature"}
