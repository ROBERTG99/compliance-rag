"""Titan and OpenAI embedding adapters against recorded responses (no network)."""

import io
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np

from compliance_rag.embed.openai_embed import OpenAIEmbedder
from compliance_rag.embed.titan import TitanEmbedder

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "embed"


class FakeBedrockRuntime:
    def __init__(self, recorded: dict[str, Any]) -> None:
        self.recorded = recorded
        self.calls: list[dict[str, Any]] = []

    def invoke_model(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"body": io.BytesIO(json.dumps(self.recorded).encode())}


class FakeOpenAI:
    def __init__(self, recorded: dict[str, Any]) -> None:
        self.calls: list[dict[str, Any]] = []
        recorded_data = recorded["data"]

        def create(**kwargs: Any) -> Any:
            self.calls.append(kwargs)
            data = [
                SimpleNamespace(embedding=d["embedding"], index=d["index"])
                for d in recorded_data[: len(kwargs["input"])]
            ]
            return SimpleNamespace(data=data, usage=SimpleNamespace(**recorded["usage"]))

        self.embeddings = SimpleNamespace(create=create)


def test_titan_request_and_response_shape() -> None:
    recorded = json.loads((FIXTURES / "titan_v2_response.json").read_text())
    client = FakeBedrockRuntime(recorded)
    emb = TitanEmbedder(client, model_id="amazon.titan-embed-text-v2:0", dim=512)
    vec = emb.embed_query("proof of address")
    assert vec.shape == (512,)
    assert abs(float(np.linalg.norm(vec)) - 1.0) < 1e-3
    body = json.loads(client.calls[0]["body"])
    assert body == {"inputText": "proof of address", "dimensions": 512, "normalize": True}
    assert client.calls[0]["modelId"] == "amazon.titan-embed-text-v2:0"
    assert emb.name == "titan" and emb.dim == 512


def test_openai_request_and_response_shape() -> None:
    recorded = json.loads((FIXTURES / "openai_embeddings_response.json").read_text())
    client = FakeOpenAI(recorded)
    emb = OpenAIEmbedder(client, model="text-embedding-3-small", dim=384)
    vecs = emb.embed_documents(["a", "b"])
    assert vecs.shape == (2, 384)
    assert client.calls[0]["dimensions"] == 384 and client.calls[0]["model"] == "text-embedding-3-small"
