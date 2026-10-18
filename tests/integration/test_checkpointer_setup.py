"""API workers start together on a fresh database: LangGraph's checkpointer migrations must not race."""

from __future__ import annotations

import asyncio

import pytest
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from compliance_rag.api.state import setup_checkpointer

pytestmark = pytest.mark.integration


async def test_concurrent_worker_start_ups_set_the_checkpointer_up_once(migrated_db) -> None:  # type: ignore[no-untyped-def]
    # one pool per simulated worker process, as with uvicorn --workers
    pools = [
        AsyncConnectionPool(
            migrated_db.url,
            min_size=1,
            max_size=3,
            open=False,
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        )
        for _ in range(6)
    ]
    for pool in pools:
        await pool.open(wait=True, timeout=30)
    try:
        await asyncio.gather(*(setup_checkpointer(pool) for pool in pools))  # no UniqueViolation
        async with pools[0].connection() as conn:
            row = await (await conn.execute("SELECT count(*) AS n FROM checkpoint_migrations")).fetchone()
        assert row is not None and row["n"] > 0
    finally:
        for pool in pools:
            await pool.close()
