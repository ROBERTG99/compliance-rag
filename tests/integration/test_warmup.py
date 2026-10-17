"""Start-up warm-up: cold caches must not turn the first asks into 503s (both legs over 250 ms)."""

from __future__ import annotations

import pytest

from tests.fixtures_services import ApiEnv

pytestmark = pytest.mark.integration


async def test_warm_up_prewarms_postgres_and_runs_each_role(api_env: ApiEnv) -> None:
    report = await api_env.app.state.crag.warm_up()
    assert report["prewarmed_blocks"] > 0
    assert report["roles"] == 4 and report["errors"] == []
    assert report["seconds"] >= 0
