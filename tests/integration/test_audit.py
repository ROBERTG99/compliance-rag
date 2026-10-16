"""Append-only, hash-chained audit table (T-11)."""

from __future__ import annotations

import psycopg
import pytest
from typer.testing import CliRunner

from compliance_rag.cli import app
from compliance_rag.db.audit import append_audit, verify_chain

from .conftest import Database

pytestmark = pytest.mark.integration


async def test_update_rejected_and_chain_verifies(migrated_db: Database) -> None:
    async with await psycopg.AsyncConnection.connect(migrated_db.url, autocommit=True) as conn:
        for i in range(5):
            await append_audit(
                conn,
                actor_sub=f"user-{i}",
                actor_role="analyst",
                action="ask",
                target=f"run-{i}",
                details={"n": i, "q_len": 10 + i},
            )
        result = await verify_chain(conn)
        assert result.ok and result.rows == 5

        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            await conn.execute("UPDATE audit SET target = 'x' WHERE seq = 2")
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            await conn.execute("DELETE FROM audit WHERE seq = 3")

        # tamper as superuser with the trigger disabled: verification must fail at that row
        await conn.execute("ALTER TABLE audit DISABLE TRIGGER audit_no_mutation")
        await conn.execute("UPDATE audit SET details = '{\"n\": 99}'::jsonb WHERE seq = 3")
        await conn.execute("ALTER TABLE audit ENABLE TRIGGER audit_no_mutation")
        tampered = await verify_chain(conn)
        assert not tampered.ok and tampered.first_bad_seq == 3


def test_cli_audit_verify(migrated_db: Database) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["audit", "verify", "--database-url", migrated_db.url])
    assert result.exit_code == 0, result.output
    assert "chain ok" in result.output


async def test_concurrent_appends_keep_chain(migrated_db: Database) -> None:
    import asyncio

    async def one(i: int) -> None:
        async with await psycopg.AsyncConnection.connect(migrated_db.url) as c:
            await append_audit(
                c, actor_sub="u", actor_role="analyst", action="ask", target=str(i), details={}
            )
            await c.commit()

    await asyncio.gather(*(one(i) for i in range(10)))
    async with await psycopg.AsyncConnection.connect(migrated_db.url) as conn:
        result = await verify_chain(conn)
    assert result.ok and result.rows == 10
