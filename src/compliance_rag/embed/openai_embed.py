"""OpenAI embeddings adapter. The client object is created by the LLM gateway."""

from __future__ import annotations

from typing import Any

import numpy as np

from compliance_rag.embed.base import Embedder, Matrix, l2_normalize


class OpenAIEmbedder(Embedder):
    name = "openai"

    def __init__(self, client: Any, model: str = "text-embedding-3-small", dim: int = 384) -> None:
        super().__init__()
        self.client = client
        self.model = model
        self.dim = dim

    def embed_documents(self, texts: list[str]) -> Matrix:
        resp = self.client.embeddings.create(model=self.model, input=texts, dimensions=self.dim)
        ordered = sorted(resp.data, key=lambda d: d.index)
        return l2_normalize(np.asarray([d.embedding for d in ordered], dtype=np.float32))

    def fingerprint(self) -> str:
        return f"openai-{self.dim}-{self.model}"
