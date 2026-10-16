"""Amazon Titan Text Embeddings v2 on Bedrock. The runtime client is created by the LLM gateway."""

from __future__ import annotations

import json
from typing import Any

import numpy as np

from compliance_rag.embed.base import Embedder, Matrix, l2_normalize


class TitanEmbedder(Embedder):
    name = "titan"

    def __init__(self, client: Any, model_id: str = "amazon.titan-embed-text-v2:0", dim: int = 512) -> None:
        super().__init__()
        self.client = client
        self.model_id = model_id
        self.dim = dim

    def embed_documents(self, texts: list[str]) -> Matrix:
        rows = []
        for text in texts:
            body = json.dumps({"inputText": text, "dimensions": self.dim, "normalize": True})
            resp = self.client.invoke_model(
                modelId=self.model_id, body=body, contentType="application/json", accept="application/json"
            )
            payload = json.loads(resp["body"].read())
            rows.append(payload["embedding"])
        return l2_normalize(np.asarray(rows, dtype=np.float32))

    def fingerprint(self) -> str:
        return f"titan-{self.dim}-{self.model_id}"
