"""Application settings (``CRAG_`` prefix) plus the shared portfolio variables.

Defaults are offline: FakeLLM, LSA embedder, feature reranker, pgvector. Every variable is
documented in ``.env.example`` (enforced by ``tests/unit/test_settings.py``).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

_SHARED = {
    "demo_mode": "DEMO_MODE",
    "live_eval_budget_usd": "LIVE_EVAL_BUDGET_USD",
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "openai_api_key": "OPENAI_API_KEY",
    "aws_region": "AWS_REGION",
    "langfuse_public_key": "LANGFUSE_PUBLIC_KEY",
    "langfuse_secret_key": "LANGFUSE_SECRET_KEY",
    "langfuse_host": "LANGFUSE_HOST",
    "otel_exporter_otlp_endpoint": "OTEL_EXPORTER_OTLP_ENDPOINT",
    "log_level": "LOG_LEVEL",
}


def _shared(name: str) -> AliasChoices:
    return AliasChoices(_SHARED[name])


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CRAG_", env_file=".env", extra="ignore", populate_by_name=True
    )

    # infrastructure
    database_url: str = "postgresql://crag:crag@localhost:8620/crag"
    redis_url: str = "redis://localhost:8630/0"
    opensearch_url: str = "http://localhost:8640"
    opensearch_index: str = "crag-chunks-v1"
    opensearch_alias: str = "crag-chunks"
    s3_endpoint_url: str = "http://localhost:8641"
    s3_access_key: SecretStr = SecretStr("crag-dev-access")
    s3_secret_key: SecretStr = SecretStr("crag-dev-secret-key")
    s3_bucket: str = "crag-raw"
    s3_region: str = "us-east-1"
    qdrant_url: str = "http://localhost:8643"
    qdrant_collection: str = "crag_chunks"

    # retrieval and AI
    vector_store: Literal["pgvector", "qdrant"] = "pgvector"
    embedder: Literal["lsa", "titan", "openai"] = "lsa"
    embed_dim: int = 384
    reranker: Literal["feature", "cohere", "cross_encoder"] = "feature"
    llm_provider: Literal["fake", "anthropic", "bedrock"] = "fake"
    model_fast: str = "claude-haiku-5-5"
    model_generate: str = "claude-opus-5-5"
    model_judge: str = "claude-haiku-5-5"
    model_titan_embed: str = "amazon.titan-embed-text-v2:0"
    model_cohere_rerank: str = "cohere.rerank-v3-5:0"
    model_openai_embed: str = "text-embedding-3-small"
    abstain_tau: float = 0.35
    rrf_k: int = 60
    topk_context: int = 8
    leg_k: int = 50
    leg_timeout_ms: int = 250
    generate_timeout_s: float = 30.0
    cassette_dir: str = "tests/fixtures/llm"
    record_cassettes: bool = False

    # auth and limits
    oidc_issuer: str = "http://localhost:8612"
    oidc_public_issuer: str = ""
    oidc_audience: str = "compliance-rag"
    max_upload_mb: int = 20
    max_question_chars: int = 2000
    rate_limit_per_min: int = 30
    sse_ttl_s: int = 300

    # paths
    app_root: str = "."

    # shared portfolio variables (no CRAG_ prefix)
    demo_mode: Literal["offline", "live"] = Field("offline", validation_alias=_shared("demo_mode"))
    live_eval_budget_usd: float = Field(2.0, validation_alias=_shared("live_eval_budget_usd"))
    anthropic_api_key: SecretStr | None = Field(None, validation_alias=_shared("anthropic_api_key"))
    openai_api_key: SecretStr | None = Field(None, validation_alias=_shared("openai_api_key"))
    aws_region: str = Field("us-east-1", validation_alias=_shared("aws_region"))
    langfuse_public_key: str | None = Field(None, validation_alias=_shared("langfuse_public_key"))
    langfuse_secret_key: SecretStr | None = Field(None, validation_alias=_shared("langfuse_secret_key"))
    langfuse_host: str | None = Field(None, validation_alias=_shared("langfuse_host"))
    otel_exporter_otlp_endpoint: str | None = Field(
        None, validation_alias=_shared("otel_exporter_otlp_endpoint")
    )
    log_level: str = Field("INFO", validation_alias=_shared("log_level"))

    @property
    def root(self) -> Path:
        return Path(self.app_root).resolve()

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def psycopg_url(self) -> str:
        """Plain libpq URL (psycopg / langgraph checkpointer)."""
        return self.database_url.replace("postgresql+psycopg://", "postgresql://")

    @property
    def sqlalchemy_url(self) -> str:
        return self.psycopg_url.replace("postgresql://", "postgresql+psycopg://", 1)

    @classmethod
    def env_names(cls) -> list[str]:
        names = []
        for field in cls.model_fields:
            names.append(_SHARED.get(field, f"CRAG_{field.upper()}"))
        return names


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
