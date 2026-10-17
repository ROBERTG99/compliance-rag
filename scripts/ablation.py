"""`make eval-ablation`: recall@10, MRR@10 and p95 for five retrieval configurations (BUILD.md §11).

    uv run python scripts/ablation.py            # test split; needs the stack and the qdrant profile

Runs the retrieval suite once per configuration (BM25, vector-pgvector, vector-qdrant, hybrid,
hybrid+rerank), writes `evals/reports/ablation.json` and re-renders `evals/REPORT.md` and
`evals/reports/latest.json` from the latest `make eval` run. Qdrant is filled from Postgres first when its
collection is rebuilt from Postgres first, so it holds exactly what pgvector holds.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "evals" / "reports"
SUITE = ROOT / "evals" / "suites" / "retrieval.yaml"


@dataclass(frozen=True)
class Config:
    name: str
    system: dict[str, Any]


CONFIGS = (
    Config("bm25", {"bm25": True, "vector": False, "rerank": False}),
    Config("vector-pgvector", {"bm25": False, "vector": True, "vector_store": "pgvector", "rerank": False}),
    Config("vector-qdrant", {"bm25": False, "vector": True, "vector_store": "qdrant", "rerank": False}),
    Config("hybrid", {"bm25": True, "vector": True, "vector_store": "pgvector", "rerank": False}),
    Config("hybrid+rerank", {"bm25": True, "vector": True, "vector_store": "pgvector", "rerank": True}),
)

RunFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def ablation_row(name: str, report: dict[str, Any]) -> dict[str, Any]:
    m = report["metrics"]
    return {
        "config": name,
        "n": m["recall@10"]["n"],
        "recall@10": m["recall@10"]["value"],
        "mrr@10": m["mrr@10"]["value"],
        "p95_ms": m["retrieval_p95"]["value"],
        "degraded_rate": m["degraded_rate"]["value"],
    }


async def run_ablation(run: RunFn, log: Callable[[str], None] = lambda _m: None) -> dict[str, Any]:
    """Rows per configuration plus the provenance of the run (split, time, the full system's target)."""
    rows = []
    report: dict[str, Any] = {}
    for config in CONFIGS:
        report = await run(config.system)
        if report.get("errors"):
            raise RuntimeError(f"{config.name}: {report['errors']} case(s) raised errors")
        rows.append(ablation_row(config.name, report))
        log(f"{config.name}: recall@10 {rows[-1]['recall@10']:.3f}, p95 {rows[-1]['p95_ms']:.0f} ms")
    return {
        "generated_at": report.get("generated_at"),
        "split": report.get("split"),
        "target": report.get("target", {}),  # hybrid+rerank: the served configuration
        "rows": rows,
    }


async def fresh_qdrant(log: Callable[[str], None]) -> None:
    """Rebuild the Qdrant collection from Postgres every time: no stale vectors, payloads or orphans."""
    from compliance_rag.ingest.reindex import reindex
    from compliance_rag.runtime import build_services
    from compliance_rag.settings import get_settings

    services = await build_services(get_settings(), with_qdrant=True)
    try:
        assert services.qdrant is not None
        if await services.qdrant.client.collection_exists(services.qdrant.collection):
            await services.qdrant.drop_collection()
        await services.qdrant.ensure_collection()
        await reindex(services.ingest_deps(), bm25=False, qdrant=True, log=log)
    finally:
        await services.close()


def suite_runner(split: str, limit: int | None) -> RunFn:
    from evalgate.runner import run_suite
    from evalgate.suite import load_suite

    from compliance_rag.evals.target import RetrievalTarget

    async def run(system: dict[str, Any]) -> dict[str, Any]:
        target = RetrievalTarget(**system)
        try:  # run_suite sets up a target it is given but leaves closing it to the owner
            return await run_suite(load_suite(SUITE), split, limit=limit, target=target)
        finally:
            await target.close()

    return run


async def amain(split: str, limit: int | None) -> dict[str, Any]:
    await fresh_qdrant(print)
    return await run_ablation(suite_runner(split, limit), print)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", default="test", choices=["dev", "test"])
    parser.add_argument("--limit", type=int, default=0, help="first N cases (smoke runs; not published)")
    args = parser.parse_args(argv)
    result = asyncio.run(amain(args.split, args.limit or None))
    if args.split != "test" or args.limit:
        print(json.dumps(result["rows"], indent=2))
        return 0
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "ablation.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    from scripts.run_evals import main as run_evals

    return run_evals(["--render-only"])


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
