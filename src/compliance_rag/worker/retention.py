"""`purge_expired` (daily cron): retention per BUILD.md §5 — answers 90 days, feedback 365, finished
ingestion jobs 30; the audit log is kept (one row records each purge).

An answer that still has feedback inside its own window is kept until that feedback expires, and newer
follow-ups of a purged answer are unlinked rather than deleted.
"""

from __future__ import annotations

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


async def purge_expired(pool: AsyncConnectionPool, *, now: datetime | None = None) -> PurgeReport:
    now = now or datetime.now(UTC)
    answers_cutoff = now - timedelta(days=ANSWERS_DAYS)
    async with pool.connection() as conn, conn.transaction():
        feedback = await conn.execute(
            "DELETE FROM feedback WHERE created_at < %s", (now - timedelta(days=FEEDBACK_DAYS),)
        )
        expired = """SELECT run_id FROM answers a WHERE a.created_at < %(cutoff)s
                     AND NOT EXISTS (SELECT 1 FROM feedback f WHERE f.run_id = a.run_id)"""
        await conn.execute(
            f"UPDATE answers SET follow_up_of = NULL WHERE follow_up_of IN ({expired})",  # noqa: S608 - constant SQL
            {"cutoff": answers_cutoff},
        )
        answers = await conn.execute(
            f"DELETE FROM answers WHERE run_id IN ({expired})",  # noqa: S608 - constant SQL
            {"cutoff": answers_cutoff},
        )
        jobs = await conn.execute(
            "DELETE FROM ingestion_jobs WHERE status IN ('done', 'failed') AND finished_at < %s",
            (now - timedelta(days=JOBS_DAYS),),
        )
        report = PurgeReport(answers.rowcount, feedback.rowcount, jobs.rowcount)
        await append_audit(
            conn,
            actor_sub="worker",
            actor_role="system",
            action="purge_expired",
            target="retention",
            details={"answers": report.answers, "feedback": report.feedback, "jobs": report.jobs},
        )
    return report
