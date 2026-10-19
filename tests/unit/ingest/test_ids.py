"""Version and chunk ids are derived from content, so every seed and every machine assigns the same ids."""

from __future__ import annotations

import uuid
from datetime import date

from compliance_rag.ingest.chunker import Chunk
from compliance_rag.ingest.pipeline import ParsedVersion, build_records, chunk_id_for, version_id_for

SHA = "a" * 64


def test_version_id_is_a_uuid_derived_from_document_version_and_content() -> None:
    first = version_id_for("KYC-0042", 3, SHA)
    assert uuid.UUID(first).version == 5
    assert first == version_id_for("KYC-0042", 3, SHA)
    others = {
        version_id_for("KYC-0043", 3, SHA),
        version_id_for("KYC-0042", 2, SHA),
        version_id_for("KYC-0042", 3, "b" * 64),
    }
    assert first not in others and len(others) == 3


class _Embedder:
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


def test_chunk_records_hash_the_derived_version_id() -> None:
    # retrieval breaks score ties by chunk id; random version ids made tie order differ per seed
    version_id = version_id_for("VND-0343", 1, SHA)
    version = {
        "id": version_id,
        "document_id": "VND-0343",
        "version": 1,
        "title": "Vendor policy",
        "domain": "vendor",
        "acl_groups": ["all"],
        "valid_from": date(2025, 1, 1),
        "valid_to": None,
    }
    chunks = [
        Chunk(
            ordinal=n,
            section_path="1",
            text=f"text {n}",
            char_start=n * 10,
            char_end=n * 10 + 6,
            token_count=2,
        )
        for n in range(2)
    ]
    parsed = ParsedVersion(version=version, text="", chunks=chunks)
    records = build_records(parsed, _Embedder())  # type: ignore[arg-type]  # structural stand-in
    assert [r.chunk_id for r in records] == [chunk_id_for(version_id, 0), chunk_id_for(version_id, 1)]
