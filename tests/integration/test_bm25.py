"""OpenSearch BM25 leg filters ACL, validity and visibility in the query."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import date

import numpy as np
import pytest

from compliance_rag.retrieval.bm25 import BM25Index
from compliance_rag.retrieval.types import ChunkRecord, Principal

pytestmark = pytest.mark.integration
SUPPORT: Principal = {"sub": "support@northwind.test", "role": "support", "groups": ["support", "all"]}
LEGAL: Principal = {"sub": "legal@northwind.test", "role": "legal", "groups": ["legal", "compliance", "all"]}
AS_OF = date(2026, 10, 16)


def _rec(i: int, text: str, groups: list[str], **kw: object) -> ChunkRecord:
    base = dict(
        chunk_id=uuid.UUID(int=i).hex,
        version_id=str(uuid.UUID(int=1000 + i)),
        document_id=f"CMP-{i:04d}",
        version=1,
        title="Litigation Hold Exceptions",
        domain="complaints",
        ordinal=0,
        section_path="Article 3 — Exceptions",
        text=text,
        char_start=0,
        char_end=len(text),
        token_count=10,
        injection_score=0.0,
        acl_groups=groups,
        valid_from=date(2025, 1, 1),
        valid_to=None,
        visible=True,
        embedding=np.zeros(384, dtype=np.float32),
    )
    base.update(kw)
    return ChunkRecord(**base)  # type: ignore[arg-type]


@pytest.fixture
async def index(opensearch_url: str, os_index: str) -> AsyncIterator[BM25Index]:
    idx = BM25Index(opensearch_url, index=os_index, alias=f"{os_index}-alias")
    await idx.init()
    try:
        yield idx
    finally:
        await idx.drop()
        await idx.close()


async def test_restricted_chunk_never_returned(index: BM25Index) -> None:
    question = "complaint files litigation hold preserved years after hold lifted"
    await index.bulk_index(
        [
            _rec(
                1,
                "Complaint files under a litigation hold are preserved for 10 years after the hold is lifted.",
                ["legal"],
            ),
            _rec(2, "Complaint records are archived according to the general schedule.", ["all"]),
        ],
        refresh=True,
    )
    support_hits = await index.search(question, SUPPORT, AS_OF, k=50)
    assert [h["document_id"] for h in support_hits] == ["CMP-0002"]
    legal_hits = await index.search(question, LEGAL, AS_OF, k=50)
    assert legal_hits[0]["document_id"] == "CMP-0001"
    assert legal_hits[0]["bm25"] and legal_hits[0]["bm25"] > 0


async def test_init_is_idempotent(index: BM25Index) -> None:
    await index.init()
    await index.init()
    assert await index.count() == 0


async def test_validity_visibility_and_acl_updates(index: BM25Index) -> None:
    text = "Vendors must notify security incidents within 24 hours."
    old = _rec(1, text, ["all"], valid_from=date(2024, 1, 1), valid_to=date(2025, 1, 1))
    hidden = _rec(2, text, ["all"], visible=False)
    current = _rec(3, text, ["all"])
    await index.bulk_index([old, hidden, current], refresh=True)
    ids = {h["chunk_id"] for h in await index.search("security incidents notify", SUPPORT, AS_OF, k=10)}
    assert ids == {current.chunk_id}
    ids = {
        h["chunk_id"]
        for h in await index.search("security incidents notify", SUPPORT, date(2024, 6, 1), k=10)
    }
    assert ids == {old.chunk_id}
    await index.set_visible(hidden.version_id, True)
    await index.close_version(current.version_id, date(2026, 3, 1))
    await index.update_acl(hidden.document_id, ["legal"])
    await index.refresh()
    assert await index.search("security incidents notify", SUPPORT, AS_OF, k=10) == []
    ids = {h["chunk_id"] for h in await index.search("security incidents notify", LEGAL, AS_OF, k=10)}
    assert ids == {hidden.chunk_id}
    await index.delete_version(hidden.version_id)
    await index.refresh()
    assert await index.search("security incidents notify", LEGAL, AS_OF, k=10) == []


async def test_updates_target_the_alias_and_report_failures(index: BM25Index) -> None:
    from compliance_rag.retrieval.bm25 import OpenSearchError

    await index.bulk_index([_rec(1, "Vendors must notify incidents within 24 hours.", ["all"])], refresh=True)
    await index.update_acl("CMP-0001", ["legal"])  # goes through the alias
    await index.refresh()
    assert await index.search("vendors notify incidents", SUPPORT, AS_OF, k=10) == []
    broken = BM25Index(index.url, index="does-not-exist", alias="does-not-exist-alias")
    try:
        with pytest.raises(OpenSearchError):
            await broken.update_acl("CMP-0001", ["all"])
    finally:
        await broken.close()


async def test_hits_carry_offsets_into_extracted_text(index: BM25Index) -> None:
    rec = _rec(5, "Vendors must notify incidents within 24 hours.", ["all"], char_start=1200, char_end=1246)
    await index.bulk_index([rec], refresh=True)
    hit = (await index.search("vendors notify incidents", SUPPORT, AS_OF, k=5))[0]
    assert (hit["char_start"], hit["char_end"]) == (1200, 1246)


async def test_init_adds_new_mapping_fields_to_an_existing_index(opensearch_url: str, os_index: str) -> None:
    import httpx

    old = {"mappings": {"dynamic": "strict", "properties": {"chunk_id": {"type": "keyword"}}}}
    async with httpx.AsyncClient(base_url=opensearch_url) as client:
        assert (await client.put(f"/{os_index}", json=old)).status_code == 200
        idx = BM25Index(opensearch_url, index=os_index, alias=f"{os_index}-alias")
        try:
            await idx.init()
            props = (await client.get(f"/{os_index}/_mapping")).json()[os_index]["mappings"]["properties"]
            assert {"char_start", "char_end", "acl_groups"} <= set(props)
        finally:
            await idx.drop()
            await idx.close()
