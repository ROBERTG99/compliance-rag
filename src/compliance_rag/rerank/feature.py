"""FeatureReranker: logistic regression over BM25, cosine, term overlap, heading match and freshness.

Weights live in ``rerank/feature_weights.json`` and are fitted on the dev split only by
``scripts/fit_reranker.py`` (``fit_weights`` refuses test rows).
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from compliance_rag.rerank.text import content_terms
from compliance_rag.retrieval.types import Candidate

FEATURES = ("bm25", "cosine", "term_jaccard", "heading_match", "freshness")
WEIGHTS_FILE = Path(__file__).with_name("feature_weights.json")


@dataclass
class FeatureWeights:
    features: list[str]
    coef: list[float]
    intercept: float
    split: str = "dev"
    n_questions: int = 0
    n_samples: int = 0
    dev_ids_sha256: str = ""
    notes: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path = WEIGHTS_FILE) -> FeatureWeights:
        data = json.loads(path.read_text())
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def save(self, path: Path = WEIGHTS_FILE) -> None:
        path.write_text(json.dumps(asdict(self), indent=2, sort_keys=True) + "\n")


def extract_features(question: str, candidates: Sequence[Candidate], as_of: date) -> list[list[float]]:
    q_terms = content_terms(question)
    max_bm25 = max((c.get("bm25") or 0.0 for c in candidates), default=0.0) or 1.0
    rows: list[list[float]] = []
    for c in candidates:
        c_terms = content_terms(c["text"])
        h_terms = content_terms(f"{c.get('title', '')} {c.get('section_path', '')}")
        overlap = len(q_terms & c_terms) / len(q_terms) if q_terms else 0.0
        heading = len(q_terms & h_terms) / len(q_terms) if q_terms else 0.0
        try:
            age_days = max(0, (as_of - date.fromisoformat(c["valid_from"])).days)
        except ValueError:
            age_days = 3650
        freshness = math.exp(-age_days / 730)
        rows.append(
            [(c.get("bm25") or 0.0) / max_bm25, float(c.get("cosine") or 0.0), overlap, heading, freshness]
        )
    return rows


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


class FeatureReranker:
    name = "feature"

    def __init__(self, weights: FeatureWeights | None = None, embedder: Any | None = None) -> None:
        self.weights = weights or FeatureWeights.load()
        self.embedder = embedder
        self._coef = np.asarray(self.weights.coef, dtype=np.float64)

    def _fill_cosine(self, question: str, candidates: list[Candidate]) -> None:
        missing = [c for c in candidates if c.get("cosine") is None]
        if not missing or self.embedder is None:
            return
        q = self.embedder.embed_query(question)
        vecs = self.embedder.embed_documents([f"{c.get('section_path', '')}\n{c['text']}" for c in missing])
        for c, v in zip(missing, vecs @ q, strict=True):
            c["cosine"] = float(v)

    def scores(self, question: str, candidates: list[Candidate], as_of: date) -> list[float]:
        if not candidates:
            return []
        self._fill_cosine(question, candidates)
        x = np.asarray(extract_features(question, candidates, as_of), dtype=np.float64)
        return [float(s) for s in _sigmoid(x @ self._coef + self.weights.intercept)]

    def rerank(self, question: str, candidates: list[Candidate], as_of: date) -> list[Candidate]:
        out: list[Candidate] = [Candidate(**c) for c in candidates]
        for c, s in zip(out, self.scores(question, out, as_of), strict=True):
            c["rerank"] = s
        return sorted(out, key=lambda c: (-(c["rerank"] or 0.0), c["chunk_id"]))


LabelledFn = Callable[[dict[str, Any]], list[tuple[list[float], int]]]


def fit_weights(
    rows: list[dict[str, Any]], labelled: LabelledFn, c: float = 1.0, notes: str = ""
) -> FeatureWeights:
    """Fit on dev rows only; ``labelled(row)`` returns (features, label) pairs for one question."""
    from sklearn.linear_model import LogisticRegression

    dev = [r for r in rows if r["split"] == "dev"]
    if not dev:
        raise ValueError("no dev rows: reranker weights are fitted on the dev split only")
    xs: list[list[float]] = []
    ys: list[int] = []
    for row in dev:
        for features, label in labelled(row):
            xs.append(features)
            ys.append(label)
    if len(set(ys)) < 2:
        raise ValueError("need positive and negative examples")
    model = LogisticRegression(C=c, solver="lbfgs", max_iter=1000, random_state=2026)
    model.fit(np.asarray(xs, dtype=np.float64), np.asarray(ys))
    ids = ",".join(sorted(r["id"] for r in dev))
    return FeatureWeights(
        features=list(FEATURES),
        coef=[round(float(v), 6) for v in model.coef_[0]],
        intercept=round(float(model.intercept_[0]), 6),
        split="dev",
        n_questions=len(dev),
        n_samples=len(ys),
        dev_ids_sha256=hashlib.sha256(ids.encode()).hexdigest(),
        notes=notes,
    )
