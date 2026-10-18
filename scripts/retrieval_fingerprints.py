"""Short fingerprints of every retrieval stage per eval question, to compare two machines without printing content.

    uv run python scripts/retrieval_fingerprints.py > fingerprints.txt

One line per stage: ``<stage> <id>:<hash> ...``. Stages: the query embedding (rounded to 1e-5), the BM25 top 50,
the vector top 50, the fused list and the reranked top 10, each as (document, version, offset) keys with
rounded scores, in order. Running it on two machines (or two seeds) and diffing the output shows the first
stage whose result differs.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from compliance_rag.auth.personas import persona_principal  # noqa: E402
from compliance_rag.evals.system import build_system  # noqa: E402

STAGES = ("embedding", "bm25", "vector", "fused", "rerank")


def key(candidate: dict[str, object]) -> str:
    """Readable and independent of how chunk ids are derived."""
    return f"{candidate['document_id']}@{candidate['version']}#{candidate['char_start']}"


def short(value: object) -> str:
    return hashlib.sha256(repr(value).encode()).hexdigest()[:8]


async def main() -> list[str]:
    rows = [
        json.loads(line) for line in (ROOT / "evals/datasets/questions.v1.jsonl").read_text().splitlines()
    ]
    system = await build_system()
    out: dict[str, list[str]] = {stage: [] for stage in STAGES}
    try:
        for row in rows:
            question = row["input"]["question"]
            principal = persona_principal(row["input"]["persona"])
            as_of = date.fromisoformat(row["input"]["as_of"])
            embedding = system.retriever.embedder.embed_query(question)
            result = await system.retriever.retrieve(question, principal, as_of)
            ranked = system.reranker.rerank(question, list(result.fused)[:50], as_of)
            values = {
                "embedding": np.round(np.asarray(embedding, dtype=np.float64), 5).tolist(),
                "bm25": [(key(c), round(float(c["bm25"] or 0), 3)) for c in result.bm25_hits],
                "vector": [(key(c), round(float(c["cosine"] or 0), 4)) for c in result.vector_hits],
                "fused": [(key(c), round(float(c["rrf"]), 6)) for c in result.fused],
                "rerank": [(key(c), round(float(c["rerank"] or 0), 4)) for c in ranked[:10]],
            }
            for stage in STAGES:
                out[stage].append(f"{row['id']}:{short(values[stage])}")
    finally:
        await system.close()
    return [f"{stage} {' '.join(out[stage])}" for stage in STAGES]


if __name__ == "__main__":
    with contextlib.redirect_stdout(sys.stderr):  # log lines go to stderr, results to stdout
        lines = asyncio.run(main())
    print("\n".join(lines))
