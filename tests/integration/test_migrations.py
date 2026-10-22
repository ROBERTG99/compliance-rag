"""Core schema."""

from __future__ import annotations

import psycopg
import pytest

from compliance_rag.db.migrate import downgrade, upgrade
from tests.fixtures_services import Database

pytestmark = pytest.mark.integration

ZERO_VEC = "[" + ",".join(["0.1"] * 384) + "]"


def _insert_doc(conn: psycopg.Connection, doc_id: str = "KYC-0042") -> None:  # type: ignore[type-arg]
    conn.execute(
        "INSERT INTO documents (document_id, title, domain, owner) VALUES (%s, 'Proof of address', 'kyc', 'compliance')",
        (doc_id,),
    )


def _insert_version(
    conn: psycopg.Connection, doc_id: str, version: int, status: str, valid_to: str | None = None
) -> str:  # type: ignore[type-arg]
    row = conn.execute(
        """INSERT INTO document_versions (document_id, version, content_sha256, source_format, s3_key,
               size_bytes, valid_from, valid_to, status)
           VALUES (%s, %s, %s, 'md', %s, 10, '2025-01-01', %s, %s) RETURNING id""",
        (doc_id, version, f"{version:064d}", f"raw/{doc_id}/{version}", valid_to, status),
    ).fetchone()
    assert row is not None
    return str(row[0])


def test_one_open_version_per_document(migrated_db: Database) -> None:
    with psycopg.connect(migrated_db.url, autocommit=True) as conn:
        _insert_doc(conn)
        _insert_version(conn, "KYC-0042", 1, "active")
        with pytest.raises(psycopg.errors.UniqueViolation):
            _insert_version(conn, "KYC-0042", 2, "active")
        # a closed previous version and a new open one is fine
        conn.execute("UPDATE document_versions SET valid_to = '2026-03-01' WHERE version = 1")
        _insert_version(conn, "KYC-0042", 2, "active")


def test_constraints_reject_bad_rows(migrated_db: Database) -> None:
    with psycopg.connect(migrated_db.url, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            _insert_doc(conn, "bad-id")
        _insert_doc(conn)
        with pytest.raises(psycopg.errors.CheckViolation):
            _insert_version(conn, "KYC-0042", 1, "active", valid_to="2024-01-01")
        vid = _insert_version(conn, "KYC-0042", 1, "pending")
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                """INSERT INTO chunks (chunk_id, version_id, document_id, ordinal, section_path, text, char_start,
                   char_end, token_count, acl_groups, valid_from, embedding)
                   VALUES (%s, %s, 'KYC-0042', 0, 'Article 1', 'x', 0, 1, 801, '{all}', '2025-01-01', %s)""",
                ("a" * 32, vid, ZERO_VEC),
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "INSERT INTO document_acl (document_id, group_name, granted_by) VALUES ('KYC-0042', 'admins', 'x')"
            )


def test_hnsw_and_gin_indexes_exist(migrated_db: Database) -> None:
    with psycopg.connect(migrated_db.url) as conn:
        names = {r[0] for r in conn.execute("SELECT indexname FROM pg_indexes WHERE tablename = 'chunks'")}
    assert {"chunks_embedding_hnsw", "chunks_acl_gin", "chunks_validity"} <= names


def test_downgrade_removes_tables(migrated_db: Database) -> None:
    downgrade(migrated_db.url, "base")
    with psycopg.connect(migrated_db.url) as conn:
        tables = {r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}
    assert not ({"documents", "chunks", "document_versions"} & tables)
    upgrade(migrated_db.url)
