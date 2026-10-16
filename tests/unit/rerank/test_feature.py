"""Feature reranker: features, fitting on dev only, fallbacks (FR-7, T-21)."""

from __future__ import annotations

import io
import json
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from compliance_rag.rerank.cohere import CohereRerankBedrock
from compliance_rag.rerank.feature import (
    FEATURES,
    FeatureReranker,
    FeatureWeights,
    extract_features,
    fit_weights,
)
from compliance_rag.retrieval.types import Candidate, make_candidate

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "rerank"
AS_OF = date(2026, 10, 16)


def cand(
    cid: str,
    text: str,
    title: str = "Policy",
    bm25: float | None = None,
    cosine: float | None = None,
    valid_from: str = "2026-01-01",
) -> Candidate:
    return make_candidate(
        chunk_id=cid,
        document_id="KYC-0001",
        version=1,
        text=text,
        acl_groups=["all"],
        valid_from=valid_from,
        valid_to=None,
        bm25=bm25,
        cosine=cosine,
        title=title,
        section_path="Article 4 — Controls",
    )


def test_features_capture_entity_and_sentence_evidence() -> None:
    q = "What is the daily spending limit on the Orion Prepaid Card?"
    good = cand(
        "a",
        "Staff log decisions. The daily spending limit on the Orion Prepaid Card is EUR 1,000.",
        "Daily Spending Limits Policy — Orion Prepaid Card",
        bm25=12.0,
        cosine=0.8,
    )
    other_product = cand(
        "b",
        "The daily spending limit on the Vega FX Transfer is EUR 500.",
        "Daily Spending Limits Policy — Vega FX Transfer",
        bm25=10.0,
        cosine=0.7,
    )
    filler = cand(
        "c",
        "Training on the daily process is mandatory. Staff supporting the spending team log limits.",
        "Training Policy — Orion Prepaid Card",
        bm25=8.0,
        cosine=0.6,
    )
    fg, fo, ff = extract_features(q, [good, other_product, filler], AS_OF)
    names = list(FEATURES)
    heading, jaccard, bm25 = names.index("heading_match"), names.index("term_jaccard"), names.index("bm25")
    assert fg[heading] == 1.0 and fo[heading] == 0.0  # product name lives in the title
    assert fg[jaccard] == 1.0 and fg[jaccard] > ff[jaccard]  # evidence is one sentence, not scattered terms
    assert 0.0 < fg[bm25] < 1.0 and fg[bm25] > fo[bm25]  # saturating absolute BM25


def test_fit_reads_dev_split_only() -> None:
    rows = [
        {"id": f"r{i}", "split": "dev" if i % 2 == 0 else "test", "input": {"question": f"q{i}"}}
        for i in range(20)
    ]
    requested: list[str] = []

    def labelled(row: dict[str, Any]) -> list[tuple[list[float], int]]:
        requested.append(row["id"])
        rng = np.random.default_rng(int(row["id"][1:]))
        pos = [float(x) for x in rng.uniform(0.6, 1.0, size=len(FEATURES))]
        neg = [float(x) for x in rng.uniform(0.0, 0.4, size=len(FEATURES))]
        return [(pos, 1), (neg, 0), (neg, 0)]

    w1 = fit_weights(rows, labelled)
    assert requested and all(int(r[1:]) % 2 == 0 for r in requested)
    requested.clear()
    w2 = fit_weights(rows, labelled)
    assert w1.coef == w2.coef and w1.intercept == w2.intercept
    assert w1.n_questions == 10 and w1.split == "dev"
    with pytest.raises(ValueError):
        fit_weights([r for r in rows if r["split"] == "test"], labelled)


def test_reranker_orders_by_probability_and_is_bounded() -> None:
    weights = FeatureWeights(features=list(FEATURES), coef=[2.0, 1.0, 4.0, 3.0, 0.2], intercept=-4.0)
    rr = FeatureReranker(weights)
    q = "What is the daily spending limit on the Orion Prepaid Card?"
    cands = [
        cand("b", "Vega FX Transfer limits are reviewed yearly.", "Vega FX Transfer", bm25=2.0),
        cand(
            "a",
            "The daily spending limit on the Orion Prepaid Card is EUR 1,000.",
            "Orion Prepaid Card",
            bm25=9.0,
        ),
    ]
    out = rr.rerank(q, cands, AS_OF)
    assert [c["chunk_id"] for c in out] == ["a", "b"]
    assert all(0.0 <= (c["rerank"] or 0) <= 1.0 for c in out)


def test_shipped_weights_load() -> None:
    w = FeatureWeights.load()
    assert w.features == list(FEATURES) and len(w.coef) == len(FEATURES)


class FakeBedrock:
    def __init__(self, payload: dict[str, Any] | None, fail: bool = False) -> None:
        self.payload, self.fail, self.calls = payload, fail, []

    def invoke_model(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self.fail:
            raise ConnectionError("bedrock unavailable")
        return {"body": io.BytesIO(json.dumps(self.payload).encode())}


def test_cohere_uses_recorded_response() -> None:
    payload = json.loads((FIXTURES / "cohere_rerank_v35_response.json").read_text())
    client = FakeBedrock(payload)
    fallback = FeatureReranker(FeatureWeights.load())
    rr = CohereRerankBedrock(client, "cohere.rerank-v3-5:0", fallback)
    cands = [cand(str(i), f"text {i}") for i in range(3)]
    out = rr.rerank("question", cands, AS_OF)
    assert [c["chunk_id"] for c in out] == ["2", "0", "1"]
    body = json.loads(client.calls[0]["body"])
    assert (
        body["query"] == "question"
        and body["documents"] == ["text 0", "text 1", "text 2"]
        and body["api_version"] == 2
    )
    assert rr.last_fallback is False


def test_cohere_errors_fall_back_to_feature_reranker() -> None:
    fallback = FeatureReranker(FeatureWeights.load())
    rr = CohereRerankBedrock(FakeBedrock(None, fail=True), "cohere.rerank-v3-5:0", fallback)
    out = rr.rerank("daily limit Orion", [cand("x", "daily limit Orion", bm25=1.0)], AS_OF)
    assert out[0]["rerank"] is not None and rr.last_fallback is True


def test_cross_encoder_unavailable_falls_back() -> None:
    from compliance_rag.rerank import create_reranker

    rr = create_reranker("cross_encoder")
    out = rr.rerank("daily limit", [cand("x", "daily limit", bm25=1.0)], AS_OF)
    assert out[0]["rerank"] is not None


def test_non_finite_scores_become_zero_features() -> None:
    nan = cand("a", "Proof of address must be recent.", bm25=float("nan"), cosine=float("nan"))
    rows = extract_features("proof of address", [nan], AS_OF)
    assert all(np.isfinite(v) for v in rows[0])
    [scored] = FeatureReranker().rerank("proof of address", [nan], AS_OF)
    assert np.isfinite(scored["rerank"])
