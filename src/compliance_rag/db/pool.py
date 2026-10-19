"""psycopg 3 async connection pool with pgvector types registered."""

from __future__ import annotations

import contextlib
from typing import Any

from pgvector.psycopg import register_vector_async
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool


async def _configure(conn: AsyncConnection[Any]) -> None:
    # the vector extension may not exist yet (before migrations); plain SQL still works then
    with contextlib.suppress(Exception):
        await register_vector_async(conn)
    await conn.set_autocommit(True)


async def create_pool(url: str, min_size: int = 1, max_size: int = 10) -> AsyncConnectionPool:
    pool = AsyncConnectionPool(url, min_size=min_size, max_size=max_size, configure=_configure, open=False)
    await pool.open(wait=True, timeout=30)
    return pool
