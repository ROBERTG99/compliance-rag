"""After the start-up warm-up the API freezes its long-lived objects out of the cyclic GC (tail latency)."""

from __future__ import annotations

import gc
from typing import Any

import pytest

from compliance_rag.api import app as app_module
from compliance_rag.settings import Settings


class FakeState:
    async def warm_up(self) -> dict[str, Any]:
        return {}

    async def close(self) -> None:
        pass


async def test_start_up_objects_are_frozen_after_the_warm_up(monkeypatch: pytest.MonkeyPatch) -> None:
    async def build_state(_settings: Settings) -> FakeState:
        return FakeState()

    monkeypatch.setattr(app_module, "build_state", build_state)
    gc.unfreeze()
    app = app_module.create_app(Settings(_env_file=None))
    try:
        async with app.router.lifespan_context(app):
            # the reranker's per-chunk caches are millions of objects: a full collection walking them stalls
            # requests for hundreds of milliseconds
            assert gc.get_freeze_count() > 0
    finally:
        gc.unfreeze()
