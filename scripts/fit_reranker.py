"""Fit FeatureReranker weights on the dev split only (``make fit-reranker``).

Candidates come from the real hybrid retrieval against the seeded stack; a candidate is positive when
it holds a gold span of the question (same document and version). Must-abstain and ACL-probe dev
questions contribute negatives only. Test rows are never read.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from compliance_rag.auth.personas import persona_principal
from compliance_rag.evals.metrics import gold_hit
from compliance_rag.evals.system import build_system
from compliance_rag.rerank.feature import FeatureReranker, FeatureWeights, extract_features, fit_weights

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evals" / "datasets" / "questions.v1.jsonl"


async def collect(
    rows: list[dict[str, Any]], hard_weight: float
) -> dict[str, list[tuple[list[float], int, float]]]:
    system = await build_system(rerank=False)
    feature = FeatureReranker(FeatureWeights.load(), embedder=system.services.embedder)
    out: dict[str, list[tuple[list[float], int, float]]] = {}
    try:
        for row in rows:
            principal = persona_principal(row["input"]["persona"])
            as_of = date.fromisoformat(row["input"]["as_of"])
            result = await system.retriever.retrieve(row["input"]["question"], principal, as_of)
            cands = [dict(c) for c in result.fused[: system.settings.leg_k]]
            feature._fill_cosine(row["input"]["question"], cands)  # type: ignore[arg-type]
            feats = extract_features(row["input"]["question"], cands, as_of)  # type: ignore[arg-type]
            golds = [] if row["expected"]["abstain"] else row["meta"]["gold"]
            # must-abstain and ACL-probe questions only yield negatives, and they are the hard ones
            weight = hard_weight if row["expected"]["abstain"] else 1.0
            out[row["id"]] = [
                (f, int(any(gold_hit(c, g) for g in golds)), weight)
                for f, c in zip(feats, cands, strict=True)
            ]
    finally:
        await system.close()
    return out


def calibrate_intercept(
    dev: list[dict[str, Any]],
    samples: dict[str, list[tuple[list[float], int, float]]],
    weights: FeatureWeights,
    tau: float,
) -> tuple[float, float]:
    """Shift the intercept so that "top score < tau" best separates must-abstain from answerable dev rows."""
    coef = np.asarray(weights.coef)
    logits = {r["id"]: max((float(np.dot(coef, f[0])) for f in samples[r["id"]]), default=-1e9) for r in dev}
    best = (0.0, -1.0)
    for shift in np.round(np.arange(-6.0, 6.01, 0.1), 2):
        correct = 0
        for r in dev:
            prob = 1.0 / (1.0 + np.exp(-(logits[r["id"]] + weights.intercept + shift)))
            correct += int((prob < tau) == bool(r["expected"]["abstain"]))
        acc = correct / len(dev)
        if acc > best[1] + 1e-9 or (abs(acc - best[1]) < 1e-9 and abs(shift) < abs(best[0])):
            best = (float(shift), acc)
    return best[0], round(best[1], 4)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--c", type=float, default=1.0, help="inverse regularisation strength")
    parser.add_argument(
        "--hard-weight", type=float, default=1.0, help="sample weight of must-abstain/ACL negatives"
    )
    parser.add_argument(
        "--tau", type=float, default=0.35, help="abstention threshold the calibration targets"
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    rows = [json.loads(line) for line in DATASET.read_text().splitlines() if line.strip()]
    dev = [r for r in rows if r["split"] == "dev"]
    samples = asyncio.run(collect(dev, args.hard_weight))
    weights = fit_weights(
        dev,
        lambda r: samples[r["id"]],
        c=args.c,
        notes="Fitted by scripts/fit_reranker.py on the dev split of questions.v1.jsonl.",
    )
    positives = sum(item[1] for s in samples.values() for item in s)
    shift, accuracy = calibrate_intercept(dev, samples, weights, tau=args.tau)
    weights.intercept = round(weights.intercept + shift, 6)
    weights.extra = {
        "intercept_shift": shift,
        "dev_abstention_accuracy_at_tau": accuracy,
        "tau": args.tau,
        "hard_weight": args.hard_weight,
        "C": args.c,
    }
    print(
        json.dumps(
            {
                "coef": dict(zip(weights.features, weights.coef, strict=True)),
                "intercept": weights.intercept,
                "dev_questions": weights.n_questions,
                "samples": weights.n_samples,
                "positives": positives,
            },
            indent=2,
        )
    )
    if not args.dry_run:
        weights.save()
        print("wrote src/compliance_rag/rerank/feature_weights.json")


if __name__ == "__main__":
    main()
