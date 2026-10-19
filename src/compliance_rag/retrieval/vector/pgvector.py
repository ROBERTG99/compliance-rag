"""pgvector store: HNSW cosine search with the ACL/validity predicate inside the SQL."""

from __future__ import annotations

from datetime import date

import numpy as np
import numpy.typing as npt
from psycopg_pool import AsyncConnectionPool

from compliance_rag.retrieval.filters import AccessFilter
from compliance_rag.retrieval.types import Candidate, ChunkRecord, Principal, make_candidate

# Built once from a module constant (no user input); values are bound parameters.
SEARCH_SQL = f"""
WITH hits AS (
  SELECT c.chunk_id, c.version_id, c.document_id, c.text, c.acl_groups, c.valid_from, c.valid_to,
         c.section_path, c.char_start, c.char_end, c.injection_score,
         c.embedding <=> %(embedding)s AS distance
  FROM chunks c
  WHERE {AccessFilter.SQL}
  ORDER BY c.embedding <=> %(embedding)s
  LIMIT %(k)s
)
SELECT h.*, v.version, d.title
FROM hits h
JOIN document_versions v ON v.id = h.version_id
JOIN documents d ON d.document_id = h.document_id
ORDER BY h.distance, h.chunk_id
"""  # noqa: S608

AUTHORIZED_SQL = f"SELECT c.chunk_id FROM chunks c WHERE c.chunk_id = ANY(%(ids)s) AND {AccessFilter.SQL}"  # noqa: S608

UPSERT_SQL = """
INSERT INTO chunks (chunk_id, version_id, document_id, ordinal, section_path, text, char_start, char_end,
                    token_count, injection_score, acl_groups, valid_from, valid_to, visible, embedding)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (chunk_id) DO UPDATE SET
  text = EXCLUDED.text, section_path = EXCLUDED.section_path, char_start = EXCLUDED.char_start,
  char_end = EXCLUDED.char_end, token_count = EXCLUDED.token_count, injection_score = EXCLUDED.injection_score,
  acl_groups = EXCLUDED.acl_groups, valid_from = EXCLUDED.valid_from, valid_to = EXCLUDED.valid_to,
  visible = EXCLUDED.visible, embedding = EXCLUDED.embedding
"""


class PgVectorStore:
    name = "pgvector"

    def __init__(self, pool: AsyncConnectionPool, ef_search: int = 100) -> None:
        self.pool = pool
        self.ef_search = ef_search

    async def upsert(self, records: list[ChunkRecord]) -> None:
        rows = [
            (
                r.chunk_id,
                r.version_id,
                r.document_id,
                r.ordinal,
                r.section_path,
                r.text,
                r.char_start,
                r.char_end,
                r.token_count,
                r.injection_score,
                r.acl_groups,
                r.valid_from,
                r.valid_to,
                r.visible,
                r.embedding,
            )
            for r in records
        ]
        async with self.pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
            await cur.executemany(UPSERT_SQL, rows)

    async def search(
        self, embedding: npt.NDArray[np.float32], principal: Principal, as_of: date, k: int
    ) -> list[Candidate]:
        flt = AccessFilter.for_principal(principal, as_of)
        params = {**flt.sql_params(), "embedding": np.asarray(embedding, dtype=np.float32), "k": k}
        async with self.pool.connection() as conn, conn.transaction():
            # iterative scans keep recall when the ACL predicate removes many HNSW neighbours
            await conn.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
            await conn.execute(f"SET LOCAL hnsw.ef_search = {int(self.ef_search)}")
            cur = await conn.execute(SEARCH_SQL, params)
            rows = await cur.fetchall()
            cols = [d.name for d in cur.description or []]
        out: list[Candidate] = []
        for row in rows:
            r = dict(zip(cols, row, strict=True))
            out.append(
                make_candidate(
                    chunk_id=r["chunk_id"],
                    document_id=r["document_id"],
                    version=r["version"],
                    text=r["text"],
                    acl_groups=list(r["acl_groups"]),
                    valid_from=r["valid_from"].isoformat(),
                    valid_to=r["valid_to"].isoformat() if r["valid_to"] else None,
                    cosine=float(1.0 - r["distance"]),
                    title=r["title"],
                    section_path=r["section_path"],
                    char_start=r["char_start"],
                    char_end=r["char_end"],
                    injection_score=float(r["injection_score"]),
                )
            )
        return out

    async def set_visible(self, version_id: str, visible: bool) -> None:
        async with self.pool.connection() as conn:
            await conn.execute("UPDATE chunks SET visible = %s WHERE version_id = %s", (visible, version_id))

    async def close_version(self, version_id: str, valid_to: date) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE chunks SET valid_to = %s WHERE version_id = %s", (valid_to, version_id)
            )

    async def update_acl(self, document_id: str, groups: list[str]) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE chunks SET acl_groups = %s WHERE document_id = %s", (groups, document_id)
            )

    async def delete_version(self, version_id: str) -> None:
        async with self.pool.connection() as conn:
            await conn.execute("DELETE FROM chunks WHERE version_id = %s", (version_id,))

    async def authorized(self, chunk_ids: list[str], principal: Principal, as_of: date) -> set[str]:
        """The subset of ``chunk_ids`` the principal may read at ``as_of`` according to Postgres."""
        params = {**AccessFilter.for_principal(principal, as_of).sql_params(), "ids": list(chunk_ids)}
        async with self.pool.connection() as conn:
            rows = await (await conn.execute(AUTHORIZED_SQL, params)).fetchall()
        return {str(r[0]) for r in rows}
