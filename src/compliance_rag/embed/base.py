"""Embedder interface shared by the LSA, Titan and OpenAI implementations."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

import numpy as np
import numpy.typing as npt

Vector = npt.NDArray[np.float32]
Matrix = npt.NDArray[np.float32]


class EmbedderMismatch(RuntimeError):
    """The configured embedder differs from the one recorded in ``index_meta``."""


class Embedder:
    name: str = "base"
    dim: int = 0

    def __init__(self, query_cache_size: int = 1024) -> None:
        self._cache: OrderedDict[str, Vector] = OrderedDict()
        self._cache_size = query_cache_size

    def fingerprint(self) -> str:
        return f"{self.name}-{self.dim}"

    def meta(self) -> dict[str, Any]:
        return {"name": self.name, "dim": self.dim, "fingerprint": self.fingerprint()}

    def check_compatible(self, index_meta: dict[str, Any] | None) -> None:
        if not index_meta:
            return
        mine = self.meta()
        for key in ("name", "dim", "fingerprint"):
            if index_meta.get(key) != mine[key]:
                raise EmbedderMismatch(
                    f"index was built with {index_meta.get('name')}/{index_meta.get('dim')} "
                    f"({index_meta.get('fingerprint')}), configured {mine['name']}/{mine['dim']} "
                    f"({mine['fingerprint']}); run `make reindex`"
                )

    def embed_documents(self, texts: list[str]) -> Matrix:
        raise NotImplementedError

    def embed_query(self, text: str) -> Vector:
        """Query embeddings are cached in an LRU (answers are never cached)."""
        hit = self._cache.get(text)
        if hit is not None:
            self._cache.move_to_end(text)
            return hit
        vec: Vector = self.embed_documents([text])[0]
        self._cache[text] = vec
        if len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
        return vec


def l2_normalize(matrix: npt.NDArray[np.floating[Any]]) -> Matrix:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    out: Matrix = (matrix / norms).astype(np.float32)
    return out
