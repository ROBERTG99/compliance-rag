"""BM25 query construction (no OpenSearch needed)."""

import json
from datetime import date
from pathlib import Path

from compliance_rag.retrieval.bm25 import BM25Index
from compliance_rag.retrieval.filters import AccessFilter

ROOT = Path(__file__).resolve().parents[3]


def test_packaged_mapping_matches_deploy_copy() -> None:
    a = json.loads((ROOT / "deploy/opensearch/crag-chunks-v1.json").read_text())
    b = json.loads((ROOT / "src/compliance_rag/retrieval/crag-chunks-v1.json").read_text())
    assert a == b
    assert a["mappings"]["dynamic"] == "strict"


def test_query_has_boosts_and_filters_inside_bool() -> None:
    flt = AccessFilter.for_principal(
        {"sub": "s", "role": "support", "groups": ["support", "all"]}, date(2026, 10, 16)
    )
    body = BM25Index.query_body("proof of address", flt, 50)
    assert body["size"] == 50
    mm = body["query"]["bool"]["must"][0]["multi_match"]
    assert mm["fields"] == ["text", "title^2", "section_path^1.5"]
    filters = body["query"]["bool"]["filter"]
    assert {"terms": {"acl_groups": ["all", "support"]}} in filters
    assert {"term": {"visible": True}} in filters
    assert {"range": {"valid_from": {"lte": "2026-10-16"}}} in filters


async def test_opensearch_errors_carry_the_type_not_the_reason() -> None:
    import httpx
    import pytest

    from compliance_rag.retrieval.bm25 import BM25Index, OpenSearchError

    def handler(request: httpx.Request) -> httpx.Response:
        reason = "failed to parse query [What is the litigation hold for Legal-only files?]"
        return httpx.Response(
            400, json={"error": {"type": "search_phase_execution_exception", "reason": reason}}
        )

    index = BM25Index("http://opensearch:9200", index="i", alias="a")
    index.client = httpx.AsyncClient(
        base_url="http://opensearch:9200", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(OpenSearchError) as raised:
        await index._req("POST", "/a/_search", json={})
    await index.close()
    assert "search_phase_execution_exception" in str(raised.value) and "litigation" not in str(raised.value)
