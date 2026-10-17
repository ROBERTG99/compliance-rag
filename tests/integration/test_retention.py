"""Retention (`purge_expired`, daily): answers 90 days, feedback 365, finished jobs 30; audit kept (§5)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.types.json import Jsonb

from compliance_rag.db.pool import create_pool
from compliance_rag.worker.retention import purge_expired

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)


async def _answer(conn, days: int, follow_up_of: str | None = None, conversation: str | None = None) -> str:  # type: ignore[no-untyped-def]
    run_id = str(uuid.uuid4())
    await conn.execute(
        """INSERT INTO answers (run_id, conversation_id, follow_up_of, user_sub, groups, question, as_of,
               response, abstained, steps, cost_usd, latency_ms, created_at)
           VALUES (%s, %s, %s, 'analyst@northwind.test', '{compliance}', 'q', '2026-10-16', %s, false, %s, 0, 1, %s)""",
        (run_id, conversation or run_id, follow_up_of, Jsonb({}), Jsonb([]), NOW - timedelta(days=days)),
    )
    return run_id


async def test_purge_keeps_what_is_still_in_its_retention_window(migrated_db) -> None:  # type: ignore[no-untyped-def]
    pool = await create_pool(migrated_db.url, min_size=1, max_size=2)
    try:
        async with pool.connection() as conn:
            old = await _answer(conn, 91)
            old_with_feedback = await _answer(conn, 200)
            ancient_feedback = await _answer(conn, 400)
            recent = await _answer(conn, 10)
            follow_up = await _answer(conn, 5, follow_up_of=old)
            for run_id, days in ((old_with_feedback, 200), (ancient_feedback, 400)):
                await conn.execute(
                    "INSERT INTO feedback (run_id, user_sub, rating, reason, created_at) "
                    "VALUES (%s, 'analyst@northwind.test', 'up', 'correct', %s)",
                    (run_id, NOW - timedelta(days=days)),
                )
            for key, status, days in (
                ("a" * 64, "done", 31),
                ("b" * 64, "failed", 40),
                ("c" * 64, "done", 3),
                ("d" * 64, "queued", 60),
            ):
                await conn.execute(
                    "INSERT INTO ingestion_jobs (idempotency_key, kind, document_id, status, requested_by, "
                    "enqueued_at, finished_at) VALUES (%s, 'acl_sync', 'KYC-0042', %s, 'admin', %s, %s)",
                    (
                        key,
                        status,
                        NOW - timedelta(days=days),
                        None if status == "queued" else NOW - timedelta(days=days),
                    ),
                )
            # LangGraph keeps the graph state (question, context chunk text) per conversation (thread)
            await AsyncPostgresSaver(pool).setup()  # type: ignore[arg-type]
            for thread in (old, recent):
                await conn.execute(
                    "INSERT INTO checkpoints (thread_id, checkpoint_id, checkpoint) VALUES (%s, '1', '{}')",
                    (thread,),
                )
                await conn.execute(
                    "INSERT INTO checkpoint_blobs (thread_id, channel, version, type) VALUES (%s, 'context', '1', 'json')",
                    (thread,),
                )
                await conn.execute(
                    "INSERT INTO checkpoint_writes (thread_id, checkpoint_id, task_id, idx, channel, blob) "
                    "VALUES (%s, '1', 't', 0, 'context', '\\x00')",
                    (thread,),
                )
            audit_before = (await (await conn.execute("SELECT count(*) FROM audit")).fetchone() or [0])[0]

        report = await purge_expired(pool, now=NOW)

        async with pool.connection() as conn:
            left = {str(r[0]) for r in await (await conn.execute("SELECT run_id FROM answers")).fetchall()}
            follow = await (
                await conn.execute("SELECT follow_up_of FROM answers WHERE run_id = %s", (follow_up,))
            ).fetchone()
            audit_after = (await (await conn.execute("SELECT count(*) FROM audit")).fetchone() or [0])[0]
        # the answer behind live feedback stays until that feedback expires
        assert left == {old_with_feedback, recent, follow_up}
        assert follow is not None and follow[0] is None  # the follow-up survives, unlinked
        assert report.answers == 2 and report.feedback == 1
        assert report.jobs == 2  # finished more than 30 days ago; queued work is never purged
        async with pool.connection() as conn:
            for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
                threads = {
                    r[0] for r in await (await conn.execute(f"SELECT thread_id FROM {table}")).fetchall()
                }
                assert threads == {recent}, table  # the purged conversation's graph state is gone too
        assert report.conversations == 2  # `old` and `ancient_feedback` have no answer left
        assert (
            audit_after == audit_before + 1
        )  # one audit row records the purge; nothing is removed from audit
    finally:
        await pool.close()
