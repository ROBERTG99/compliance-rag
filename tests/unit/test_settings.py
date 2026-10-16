"""Settings defaults are offline and every variable is documented (T-09)."""

import re
from pathlib import Path

import pytest

from compliance_rag.settings import Settings

ROOT = Path(__file__).resolve().parents[2]


def test_defaults_are_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("DEMO_MODE", "CRAG_LLM_PROVIDER", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    s = Settings(_env_file=None)
    assert s.demo_mode == "offline"
    assert s.llm_provider == "fake"
    assert s.embedder == "lsa" and s.embed_dim == 384
    assert s.reranker == "feature"
    assert s.vector_store == "pgvector"
    assert s.abstain_tau == 0.35 and s.rrf_k == 60 and s.topk_context == 8 and s.leg_timeout_ms == 250
    assert s.max_upload_mb == 20 and s.rate_limit_per_min == 30
    assert s.live_eval_budget_usd == 2.0
    assert s.model_generate == "claude-opus-5-5"
    assert s.model_fast == "claude-haiku-5-5" and s.model_judge == "claude-haiku-5-5"
    assert s.s3_bucket == "crag-raw"


def test_live_mode_requires_explicit_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_MODE", "live")
    monkeypatch.setenv("CRAG_LLM_PROVIDER", "anthropic")
    s = Settings(_env_file=None)
    assert s.demo_mode == "live" and s.llm_provider == "anthropic"


def test_model_ids_have_no_date_suffix() -> None:
    s = Settings(_env_file=None)
    for model in (s.model_fast, s.model_generate, s.model_judge):
        assert not re.search(r"\d{8}$", model)


def test_every_crag_variable_documented() -> None:
    example = (ROOT / ".env.example").read_text()
    documented = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", example, flags=re.M))
    for name in Settings.env_names():
        assert name in documented, name
    for shared in (
        "DEMO_MODE",
        "LIVE_EVAL_BUDGET_USD",
        "ANTHROPIC_API_KEY",
        "LANGFUSE_PUBLIC_KEY",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "LOG_LEVEL",
    ):
        assert shared in documented, shared
