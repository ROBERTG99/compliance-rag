"""Append-only audit log with a SHA-256 hash chain.

``hash = sha256(prev_hash || canonical_json(row))`` where ``row`` holds ts, actor, action, target
and details. Appends take a transaction-scoped advisory lock so concurrent writers keep one chain.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import psycopg

GENESIS = "0" * 64
_LOCK_KEY = 0x0A0D17  # advisory lock id for audit appends

AuditAction = Literal[
    "ask", "evidence_view", "document_upload", "version_activate", "acl_change", "feedback", "feedback_triage"
]


def _stringify_floats(value: Any) -> Any:
    """jsonb does not round-trip every float exactly, so floats are hashed and stored as strings."""
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, dict):
        return {str(k): _stringify_floats(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_stringify_floats(v) for v in value]
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def row_hash(prev_hash: str, row: dict[str, Any]) -> str:
    return hashlib.sha256((prev_hash + canonical_json(row)).encode()).hexdigest()


def _row(
    ts: datetime, actor_sub: str, actor_role: str, action: str, target: str, details: Any
) -> dict[str, Any]:
    return {
        "ts": ts.astimezone(UTC).isoformat(timespec="microseconds"),
        "actor_sub": actor_sub,
        "actor_role": actor_role,
        "action": action,
        "target": target,
        "details": details,
    }


async def append_audit(
    conn: psycopg.AsyncConnection[Any],
    *,
    actor_sub: str,
    actor_role: str,
    action: AuditAction,
    target: str,
    details: dict[str, Any],
) -> str:
    """Append one row inside the caller's transaction (or its own when autocommit).

    Callers must use READ COMMITTED (the default): the last hash is read after the advisory lock.
    """
    async with conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK_KEY,))
        cur = await conn.execute("SELECT hash FROM audit ORDER BY seq DESC LIMIT 1")
        last = await cur.fetchone()
        prev = str(last[0]) if last else GENESIS
        ts = datetime.now(UTC)
        # round-trip details through JSON so the stored jsonb and the hashed value agree
        normalized = json.loads(canonical_json(_stringify_floats(details)))
        digest = row_hash(prev, _row(ts, actor_sub, actor_role, action, target, normalized))
        await conn.execute(
            """INSERT INTO audit (ts, actor_sub, actor_role, action, target, details, prev_hash, hash)
               VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)""",
            (ts, actor_sub, actor_role, action, target, canonical_json(normalized), prev, digest),
        )
    return digest


@dataclass(frozen=True)
class ChainResult:
    ok: bool
    rows: int
    first_bad_seq: int | None = None


async def verify_chain(conn: psycopg.AsyncConnection[Any]) -> ChainResult:
    prev = GENESIS
    rows = 0
    cur = await conn.execute(
        "SELECT seq, ts, actor_sub, actor_role, action, target, details, prev_hash, hash FROM audit ORDER BY seq"
    )
    async for seq, ts, actor_sub, actor_role, action, target, details, prev_hash, stored in cur:
        rows += 1
        expected = row_hash(prev, _row(ts, actor_sub, actor_role, action, target, details))
        if prev_hash != prev or stored != expected:
            return ChainResult(ok=False, rows=rows, first_bad_seq=int(seq))
        prev = stored
    return ChainResult(ok=True, rows=rows)
