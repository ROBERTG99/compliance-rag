"""Version and chunk ids are derived from content, so every seed and every machine assigns the same ids."""

from __future__ import annotations

import uuid

from compliance_rag.ingest.pipeline import chunk_id_for, version_id_for

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


def test_chunk_ids_are_stable_across_registrations() -> None:
    # retrieval breaks score ties by chunk id; random version ids made tie order differ per seed
    version_id = version_id_for("VND-0343", 1, SHA)
    assert chunk_id_for(version_id, 0) == chunk_id_for(version_id_for("VND-0343", 1, SHA), 0)
