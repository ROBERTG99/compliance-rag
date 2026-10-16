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
