"""BM25 leg on OpenSearch (FR-6). Filters for ACL, validity and visibility are inside the query.

Talks to the REST API with httpx (traced by the httpx OpenTelemetry instrumentation).
"""

from __future__ import annotations

import asyncio
import json
from datetime import date
from importlib import resources
from pathlib import Path
from typing import Any

import httpx

from compliance_rag.retrieval.filters import AccessFilter
from compliance_rag.retrieval.types import Candidate, ChunkRecord, Principal, make_candidate

MAPPING_FILE = Path(__file__).resolve().parents[3] / "deploy" / "opensearch" / "crag-chunks-v1.json"


def index_body() -> dict[str, Any]:
    try:
        return dict(json.loads(MAPPING_FILE.read_text()))
    except FileNotFoundError:  # installed wheel: fall back to the packaged copy
        return dict(
            json.loads(
                resources.files("compliance_rag.retrieval").joinpath("crag-chunks-v1.json").read_text()
            )
        )


class OpenSearchError(RuntimeError):
    pass


class BM25Index:
    name = "bm25"

    def __init__(
        self, url: str, index: str = "crag-chunks-v1", alias: str = "crag-chunks", timeout_s: float = 5.0
    ) -> None:
        self.url = url.rstrip("/")
        self.index = index
        self.alias = alias
        self.client = httpx.AsyncClient(base_url=self.url, timeout=timeout_s)

    async def close(self) -> None:
        await self.client.aclose()

    async def _req(self, method: str, path: str, **kw: Any) -> httpx.Response:
        resp = await self.client.request(method, path, **kw)
        if resp.status_code >= 400:
            raise OpenSearchError(f"{method} {path} -> {resp.status_code}: {resp.text[:300]}")
        return resp

    async def ping(self) -> bool:
        try:
            return (await self.client.get("/_cluster/health")).status_code == 200
        except httpx.HTTPError:
            return False

    async def init(self) -> bool:
        """Create the index and alias when missing. Returns True when something was created."""
        created = False
        if (await self.client.head(f"/{self.index}")).status_code == 404:
            resp = await self.client.put(f"/{self.index}", json=index_body())
            if resp.status_code >= 400 and "resource_already_exists" not in resp.text:
                raise OpenSearchError(resp.text[:300])
            created = True
        else:  # add fields introduced since the index was created (allowed under "dynamic": "strict")
            await self._req(
                "PUT", f"/{self.index}/_mapping", json={"properties": index_body()["mappings"]["properties"]}
            )
        if (await self.client.head(f"/_alias/{self.alias}")).status_code == 404:
            await self._req(
                "POST", "/_aliases", json={"actions": [{"add": {"index": self.index, "alias": self.alias}}]}
            )
            created = True
        return created

    async def drop(self) -> None:
        await self.client.delete(f"/{self.index}")

    async def refresh(self) -> None:
        await self._req("POST", f"/{self.index}/_refresh")

    async def expunge_deletes(self, attempts: int = 10) -> int:
        """Merge to one segment until no deleted copies remain, so BM25 term statistics (which count
        deleted documents) are reproducible after re-indexing. Returns the remaining deleted count."""
        deleted = -1
        for attempt in range(attempts):
            await self._req(
                "POST", f"/{self.index}/_forcemerge", params={"max_num_segments": "1"}, timeout=600.0
            )
            await self.refresh()
            stats = (await self._req("GET", f"/{self.index}/_stats/docs")).json()
            deleted = int(stats["_all"]["primaries"]["docs"]["deleted"])
            if deleted == 0:
                break
            await asyncio.sleep(0.5 * (attempt + 1))
        return deleted

    async def count(self) -> int:
        resp = await self._req("GET", f"/{self.alias}/_count")
        return int(resp.json()["count"])

    async def bulk_index(self, records: list[ChunkRecord], refresh: bool = False) -> None:
        for i in range(0, len(records), 1000):
            lines: list[str] = []
            for r in records[i : i + 1000]:
                lines.append(json.dumps({"index": {"_index": self.index, "_id": r.chunk_id}}))
                lines.append(
                    json.dumps(
                        {
                            "chunk_id": r.chunk_id,
                            "document_id": r.document_id,
                            "version": r.version,
                            "version_id": r.version_id,
                            "title": r.title,
                            "section_path": r.section_path,
                            "text": r.text,
                            "domain": r.domain,
                            "acl_groups": r.acl_groups,
                            "valid_from": r.valid_from.isoformat(),
                            "valid_to": r.valid_to.isoformat() if r.valid_to else None,
                            "visible": r.visible,
                            "injection_score": r.injection_score,
                            "char_start": r.char_start,
                            "char_end": r.char_end,
                        }
                    )
                )
            resp = await self._req(
                "POST",
                "/_bulk",
                content="\n".join(lines) + "\n",
                headers={"Content-Type": "application/x-ndjson"},
                params={"refresh": "true" if refresh and i + 1000 >= len(records) else "false"},
            )
            body = resp.json()
            if body.get("errors"):
                first = next(item for item in body["items"] if "error" in item.get("index", {}))
                raise OpenSearchError(f"bulk error: {first['index']['error']}")

    @staticmethod
    def query_body(query: str, flt: AccessFilter, k: int) -> dict[str, Any]:
        return {
            "size": k,
            "_source": [
                "chunk_id",
                "document_id",
                "version",
                "title",
                "section_path",
                "text",
                "acl_groups",
                "valid_from",
                "valid_to",
                "injection_score",
                "char_start",
                "char_end",
            ],
            "query": {
                "bool": {
                    "must": [
                        {"multi_match": {"query": query, "fields": ["text", "title^2", "section_path^1.5"]}}
                    ],
                    "filter": flt.opensearch(),
                }
            },
            "sort": ["_score", {"chunk_id": "asc"}],
            "track_scores": True,
        }

    async def search(self, query: str, principal: Principal, as_of: date, k: int = 50) -> list[Candidate]:
        flt = AccessFilter.for_principal(principal, as_of)
        resp = await self._req("POST", f"/{self.alias}/_search", json=self.query_body(query, flt, k))
        out: list[Candidate] = []
        for hit in resp.json()["hits"]["hits"]:
            s = hit["_source"]
            out.append(
                make_candidate(
                    chunk_id=s["chunk_id"],
                    document_id=s["document_id"],
                    version=int(s["version"]),
                    text=s["text"],
                    acl_groups=list(s["acl_groups"]),
                    valid_from=s["valid_from"],
                    valid_to=s.get("valid_to"),
                    bm25=float(hit["_score"]),
                    title=s["title"],
                    section_path=s["section_path"],
                    injection_score=float(s.get("injection_score") or 0.0),
                    char_start=int(s.get("char_start") or 0),
                    char_end=int(s.get("char_end") or 0),
                )
            )
        return out

    async def _update_by_query(self, term: dict[str, Any], source: str, params: dict[str, Any]) -> None:
        """Idempotent update through the alias; version conflicts are retried, failures raise."""
        body = {"query": {"term": term}, "script": {"source": source, "lang": "painless", "params": params}}
        for attempt in range(3):
            resp = await self._req(
                "POST",
                f"/{self.alias}/_update_by_query",
                params={"conflicts": "proceed", "refresh": "true"},
                json=body,
            )
            result = resp.json()
            if result.get("failures"):
                raise OpenSearchError(f"update_by_query failures: {result['failures'][:1]}")
            if not result.get("version_conflicts"):
                return
            await asyncio.sleep(0.2 * (attempt + 1))
        raise OpenSearchError("update_by_query kept hitting version conflicts")

    async def set_visible_many(self, version_ids: list[str]) -> None:
        """Make many versions visible (bulk seed activation); conflicts are retried, failures raise."""
        for i in range(0, len(version_ids), 1000):
            body = {
                "query": {"terms": {"version_id": version_ids[i : i + 1000]}},
                "script": {"source": "ctx._source.visible = true", "lang": "painless"},
            }
            for attempt in range(3):
                resp = await self._req(
                    "POST",
                    f"/{self.alias}/_update_by_query",
                    params={"conflicts": "proceed", "refresh": "true"},
                    json=body,
                )
                result = resp.json()
                if result.get("failures"):
                    raise OpenSearchError("update_by_query failures while activating seed versions")
                if not result.get("version_conflicts"):
                    break
                await asyncio.sleep(0.2 * (attempt + 1))
            else:
                raise OpenSearchError("update_by_query kept hitting version conflicts")

    async def set_visible(self, version_id: str, visible: bool) -> None:
        await self._update_by_query(
            {"version_id": version_id}, "ctx._source.visible = params.v", {"v": visible}
        )

    async def close_version(self, version_id: str, valid_to: date) -> None:
        await self._update_by_query(
            {"version_id": version_id}, "ctx._source.valid_to = params.d", {"d": valid_to.isoformat()}
        )

    async def update_acl(self, document_id: str, groups: list[str]) -> None:
        await self.refresh()  # bulk-indexed documents are invisible to update-by-query until refreshed
        await self._update_by_query(
            {"document_id": document_id}, "ctx._source.acl_groups = params.g", {"g": groups}
        )

    async def delete_version(self, version_id: str) -> None:
        await self._req(
            "POST",
            f"/{self.alias}/_delete_by_query",
            params={"conflicts": "proceed", "refresh": "true"},
            json={"query": {"term": {"version_id": version_id}}},
        )
