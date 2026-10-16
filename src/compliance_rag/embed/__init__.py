"""Embedders: offline LSA (default), Bedrock Titan and OpenAI."""

from __future__ import annotations

from compliance_rag.embed.base import Embedder, EmbedderMismatch
from compliance_rag.embed.lsa import LocalLSAEmbedder

__all__ = ["Embedder", "EmbedderMismatch", "LocalLSAEmbedder", "create_embedder"]


def create_embedder(name: str, dim: int = 384, model: str | None = None) -> Embedder:
    if name == "lsa":
        return LocalLSAEmbedder(dim=dim)
    if name == "titan":
        from compliance_rag.embed.titan import TitanEmbedder
        from compliance_rag.llm.gateway import bedrock_runtime_client

        return TitanEmbedder(
            bedrock_runtime_client(), model_id=model or "amazon.titan-embed-text-v2:0", dim=dim
        )
    if name == "openai":
        from compliance_rag.embed.openai_embed import OpenAIEmbedder
        from compliance_rag.llm.gateway import openai_client

        return OpenAIEmbedder(openai_client(), model=model or "text-embedding-3-small", dim=dim)
    raise ValueError(f"unknown embedder {name!r}")
