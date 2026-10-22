"""`purge_expired` (daily cron): retention: answers 90 days, feedback 365, finished
ingestion jobs 30; the audit log is kept (one row records each purge).

An answer that still has feedback inside its own window is kept until that feedback expires, and newer
follow-ups of a purged answer are unlinked rather than deleted. When a conversation has no answer left, its
LangGraph checkpoints (question, context chunk text, drafts) are deleted too, as are the checkpoints of runs
that never wrote an answer once their newest checkpoint is older than the answer window.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from psycopg_pool import AsyncConnectionPool

from compliance_rag.db.audit import append_audit

ANSWERS_DAYS, FEEDBACK_DAYS, JOBS_DAYS = 90, 365, 30


@dataclass(frozen=True)
class PurgeReport:
    answers: int
    feedback: int
    jobs: int
    conversations: int = 0


CHECKPOINT_TABLES = ("checkpoint_writes", "checkpoint_blobs", "checkpoints")


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


async def purge_expired(pool: AsyncConnectionPool, *, now: datetime | None = None) -> PurgeReport:
    now = now or datetime.now(UTC)
    answers_cutoff = now - timedelta(days=ANSWERS_DAYS)
    async with pool.connection() as conn, conn.transaction():
        feedback = await conn.execute(
            "DELETE FROM feedback WHERE created_at < %s", (now - timedelta(days=FEEDBACK_DAYS),)
        )
        # lock the expired rows first: a follow-up inserted meanwhile waits on the lock (its FK check) and the
        # two statements below see exactly the same set
        expired = await (
            await conn.execute(
                """SELECT run_id, conversation_id FROM answers a WHERE a.created_at < %s
                   AND NOT EXISTS (SELECT 1 FROM feedback f WHERE f.run_id = a.run_id) FOR UPDATE""",
                (answers_cutoff,),
            )
        ).fetchall()
        run_ids = [r[0] for r in expired]
        await conn.execute("UPDATE answers SET follow_up_of = NULL WHERE follow_up_of = ANY(%s)", (run_ids,))
        answers = await conn.execute("DELETE FROM answers WHERE run_id = ANY(%s)", (run_ids,))
        candidates = {str(r[1]) for r in expired}
        has_checkpoints = (
            await (await conn.execute("SELECT to_regclass('public.checkpoints')")).fetchone() or [None]
        )[0]
        if has_checkpoints:
            # threads whose newest checkpoint is past the answer window: a run that ended before writing an
            # answer (generation or retrieval unavailable) left graph state with no answers row
            candidates |= {
                str(r[0])
                for r in await (
                    await conn.execute(
                        "SELECT thread_id FROM checkpoints GROUP BY thread_id "
                        "HAVING max((checkpoint->>'ts')::timestamptz) < %s",
                        (answers_cutoff,),
                    )
                ).fetchall()
            }
        touched = sorted(
            c for c in candidates if _is_uuid(c)
        )  # one foreign thread id must not abort the purge
        alive = {
            str(r[0])
            for r in await (
                await conn.execute(
                    "SELECT DISTINCT conversation_id FROM answers WHERE conversation_id = ANY(%s::uuid[])",
                    (touched,),
                )
            ).fetchall()
        }
        gone = [c for c in touched if c not in alive]
        if gone and has_checkpoints:
            for table in CHECKPOINT_TABLES:  # constant names
                await conn.execute(f"DELETE FROM {table} WHERE thread_id = ANY(%s)", (gone,))  # noqa: S608
        jobs = await conn.execute(
            "DELETE FROM ingestion_jobs WHERE status IN ('done', 'failed') AND finished_at < %s",
            (now - timedelta(days=JOBS_DAYS),),
        )
        report = PurgeReport(answers.rowcount, feedback.rowcount, jobs.rowcount, len(gone))
        await append_audit(
            conn,
            actor_sub="worker",
            actor_role="system",
            action="purge_expired",
            target="retention",
            details={
                "answers": report.answers,
                "feedback": report.feedback,
                "jobs": report.jobs,
                "conversations": report.conversations,
            },
        )
    return report
