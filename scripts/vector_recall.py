"""Vector leg recall against exact search: the configured HNSW query and the same SQL with index scans off.

    uv run python scripts/vector_recall.py      # every eval question; dev ids listed, test split counted only

HNSW is approximate and its graph depends on the machine that built it (ADR 0001). The eval numbers are only
reproducible across machines while the configured search returns what exact search returns.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from compliance_rag.auth.personas import persona_principal  # noqa: E402
from compliance_rag.evals.system import build_system  # noqa: E402
from compliance_rag.retrieval.filters import AccessFilter  # noqa: E402
from compliance_rag.retrieval.vector.pgvector import SEARCH_SQL  # noqa: E402

K = 50


async def exact_ids(pool: Any, embedding: Any, principal: Any, as_of: date) -> list[str]:
    flt = AccessFilter.for_principal(principal, as_of)
    params = {**flt.sql_params(), "embedding": np.asarray(embedding, dtype=np.float32), "k": K}
    async with pool.connection() as conn, conn.transaction():
        await conn.execute("SET LOCAL enable_indexscan = off")
        await conn.execute("SET LOCAL enable_bitmapscan = off")
        cur = await conn.execute(SEARCH_SQL, params)
        return [str(r[0]) for r in await cur.fetchall()]


async def main() -> int:
    rows = [
        json.loads(line) for line in (ROOT / "evals/datasets/questions.v1.jsonl").read_text().splitlines()
    ]
    system = await build_system()
    store, embedder = system.retriever.vector, system.retriever.embedder
    differ: dict[str, list[str]] = {"dev": [], "test": []}
    try:
        for row in rows:
            principal = persona_principal(row["input"]["persona"])
            as_of = date.fromisoformat(row["input"]["as_of"])
            embedding = embedder.embed_query(row["input"]["question"])
            if not np.any(embedding):
                continue
            configured = [c["chunk_id"] for c in await store.search(embedding, principal, as_of, K)]
            if configured != await exact_ids(store.pool, embedding, principal, as_of):
                differ[row["split"]].append(row["id"])
    finally:
        await system.close()
    print(
        f"vector top-{K} differs from exact search: dev {len(differ['dev'])} {differ['dev']}, test {len(differ['test'])}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
