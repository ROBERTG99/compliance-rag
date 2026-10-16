"""LocalLSAEmbedder: TF-IDF + TruncatedSVD (384 dims, seed 2026), fully offline and deterministic.

Serialised as an ``.npz`` (vocabulary, idf, SVD components) — never pickle.
"""

from __future__ import annotations

import hashlib
import io
import json

import numpy as np
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer

from compliance_rag.embed.base import Embedder, Matrix, l2_normalize

_TFIDF_KW = {
    "lowercase": True,
    "stop_words": "english",
    "ngram_range": (1, 2),
    "min_df": 2,
    "max_features": 60000,
    "sublinear_tf": True,
    "dtype": np.float32,
}


class LocalLSAEmbedder(Embedder):
    name = "lsa"

    def __init__(self, dim: int = 384, seed: int = 2026) -> None:
        super().__init__()
        self.dim = dim
        self.seed = seed
        self._vectorizer: TfidfVectorizer | None = None
        self._components: np.ndarray | None = None
        self._fingerprint: str | None = None

    def fit(self, texts: list[str]) -> LocalLSAEmbedder:
        kwargs = dict(_TFIDF_KW)
        if len(texts) < 50:
            kwargs["min_df"] = 1
        vectorizer = TfidfVectorizer(**kwargs)
        x = vectorizer.fit_transform(texts)
        k = max(1, min(self.dim, x.shape[0] - 1, x.shape[1] - 1))
        svd = TruncatedSVD(n_components=k, algorithm="randomized", n_iter=7, random_state=self.seed)
        svd.fit(x)
        components = np.zeros((self.dim, x.shape[1]), dtype=np.float32)
        components[:k] = svd.components_.astype(np.float32)
        self._vectorizer = vectorizer
        self._components = components
        self._fingerprint = None
        self._cache.clear()
        return self

    @property
    def fitted(self) -> bool:
        return self._vectorizer is not None and self._components is not None

    def embed_documents(self, texts: list[str]) -> Matrix:
        if self._vectorizer is None or self._components is None:
            raise RuntimeError("LocalLSAEmbedder is not fitted; run `crag seed` or `make reindex`")
        x = self._vectorizer.transform(texts)
        return l2_normalize(np.asarray(x @ self._components.T, dtype=np.float32))

    def to_bytes(self) -> bytes:
        if self._vectorizer is None or self._components is None:
            raise RuntimeError("cannot serialise an unfitted embedder")
        vocab = sorted(self._vectorizer.vocabulary_.items(), key=lambda kv: kv[1])
        buf = io.BytesIO()
        np.savez_compressed(
            buf,
            meta=np.frombuffer(json.dumps({"dim": self.dim, "seed": self.seed}).encode(), dtype=np.uint8),
            vocab=np.frombuffer(json.dumps([t for t, _ in vocab]).encode(), dtype=np.uint8),
            idf=self._vectorizer.idf_.astype(np.float32),
            components=self._components,
        )
        return buf.getvalue()

    @classmethod
    def from_bytes(cls, blob: bytes) -> LocalLSAEmbedder:
        data = np.load(io.BytesIO(blob), allow_pickle=False)
        meta = json.loads(bytes(data["meta"]).decode())
        terms = json.loads(bytes(data["vocab"]).decode())
        emb = cls(dim=int(meta["dim"]), seed=int(meta["seed"]))
        vectorizer = TfidfVectorizer(
            vocabulary={t: i for i, t in enumerate(terms)},
            **{k: v for k, v in _TFIDF_KW.items() if k not in {"min_df", "max_features"}},
        )
        vectorizer.idf_ = data["idf"].astype(np.float64)
        emb._vectorizer = vectorizer
        emb._components = data["components"].astype(np.float32)
        return emb

    def fingerprint(self) -> str:
        if self._fingerprint is None:
            if not self.fitted:
                return f"lsa-{self.dim}-unfitted"
            assert self._vectorizer is not None and self._components is not None
            h = hashlib.sha256()
            h.update(
                json.dumps(sorted((t, int(i)) for t, i in self._vectorizer.vocabulary_.items())).encode()
            )
            h.update(np.round(self._components, 5).tobytes())
            self._fingerprint = f"lsa-{self.dim}-{h.hexdigest()[:16]}"
        return self._fingerprint
