"""The evaluated system is the served system: same retriever wiring as the API."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from compliance_rag.evals import system as eval_system
from compliance_rag.settings import Settings


async def test_eval_retriever_rechecks_index_hits_against_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    pg, qdrant = object(), object()

    async def fake_services(settings: Settings, **_: Any) -> SimpleNamespace:
        return SimpleNamespace(bm25=object(), pg=pg, qdrant=qdrant, embedder=object())

    monkeypatch.setattr(eval_system, "build_services", fake_services)
    monkeypatch.setattr(eval_system, "create_reranker", lambda *a, **k: object())
    monkeypatch.setattr(eval_system, "build_graph", lambda *a, **k: object())
    for store in ("pgvector", "qdrant"):
        built = await eval_system.build_system(Settings(_env_file=None), vector_store=store)
        assert built.retriever.authority is pg, store
