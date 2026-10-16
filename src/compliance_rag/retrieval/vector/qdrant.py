"""Qdrant store (profile ``qdrant``): cosine collection with payload filters inside the query."""

from __future__ import annotations

import uuid
from datetime import date

import numpy as np
import numpy.typing as npt
from qdrant_client import AsyncQdrantClient, models

from compliance_rag.retrieval.filters import AccessFilter, date_to_int
from compliance_rag.retrieval.types import Candidate, ChunkRecord, Principal, make_candidate


def point_id(chunk_id: str) -> str:
    return str(uuid.UUID(hex=chunk_id))


class QdrantStore:
    name = "qdrant"

    def __init__(self, url: str, collection: str = "crag_chunks", dim: int = 384) -> None:
        self.client = AsyncQdrantClient(url=url, prefer_grpc=False, timeout=10, check_compatibility=False)
        self.collection = collection
        self.dim = dim

    async def ensure_collection(self) -> None:
        if await self.client.collection_exists(self.collection):
            return
        await self.client.create_collection(
            self.collection,
            vectors_config=models.VectorParams(size=self.dim, distance=models.Distance.COSINE),
            hnsw_config=models.HnswConfigDiff(m=16, ef_construct=64),
        )
        for field, schema in [
            ("acl_groups", models.PayloadSchemaType.KEYWORD),
            ("document_id", models.PayloadSchemaType.KEYWORD),
            ("version_id", models.PayloadSchemaType.KEYWORD),
            ("visible", models.PayloadSchemaType.BOOL),
            ("valid_from_n", models.PayloadSchemaType.INTEGER),
            ("valid_to_n", models.PayloadSchemaType.INTEGER),
        ]:
            await self.client.create_payload_index(self.collection, field, field_schema=schema)

    async def drop_collection(self) -> None:
        await self.client.delete_collection(self.collection)

    async def close(self) -> None:
        await self.client.close()

    async def upsert(self, records: list[ChunkRecord]) -> None:
        points = [
            models.PointStruct(
                id=point_id(r.chunk_id),
                vector=np.asarray(r.embedding, dtype=np.float32).tolist(),
                payload={
                    "chunk_id": r.chunk_id,
                    "version_id": r.version_id,
                    "document_id": r.document_id,
                    "version": r.version,
                    "title": r.title,
                    "section_path": r.section_path,
                    "text": r.text,
                    "char_start": r.char_start,
                    "char_end": r.char_end,
                    "injection_score": r.injection_score,
                    "acl_groups": r.acl_groups,
                    "visible": r.visible,
                    "valid_from": r.valid_from.isoformat(),
                    "valid_to": r.valid_to.isoformat() if r.valid_to else None,
                    "valid_from_n": date_to_int(r.valid_from),
                    "valid_to_n": date_to_int(r.valid_to),
                },
            )
            for r in records
        ]
        for i in range(0, len(points), 512):
            await self.client.upsert(self.collection, points=points[i : i + 512], wait=True)

    async def search(
        self, embedding: npt.NDArray[np.float32], principal: Principal, as_of: date, k: int
    ) -> list[Candidate]:
        flt = AccessFilter.for_principal(principal, as_of)
        resp = await self.client.query_points(
            self.collection,
            query=np.asarray(embedding, dtype=np.float32).tolist(),
            query_filter=flt.qdrant(),
            limit=k,
            with_payload=True,
            search_params=models.SearchParams(hnsw_ef=100),
        )
        out: list[Candidate] = []
        for p in resp.points:
            pl = p.payload or {}
            out.append(
                make_candidate(
                    chunk_id=pl["chunk_id"],
                    document_id=pl["document_id"],
                    version=int(pl["version"]),
                    text=pl["text"],
                    acl_groups=list(pl["acl_groups"]),
                    valid_from=pl["valid_from"],
                    valid_to=pl.get("valid_to"),
                    cosine=float(p.score),
                    title=pl.get("title", ""),
                    section_path=pl.get("section_path", ""),
                    char_start=int(pl.get("char_start", 0)),
                    char_end=int(pl.get("char_end", 0)),
                    injection_score=float(pl.get("injection_score", 0.0)),
                )
            )
        return out

    async def _set_payload(self, payload: dict[str, object], key: str, value: str) -> None:
        await self.client.set_payload(
            self.collection,
            payload=payload,
            points=models.Filter(must=[models.FieldCondition(key=key, match=models.MatchValue(value=value))]),
            wait=True,
        )

    async def set_visible(self, version_id: str, visible: bool) -> None:
        await self._set_payload({"visible": visible}, "version_id", version_id)

    async def close_version(self, version_id: str, valid_to: date) -> None:
        await self._set_payload(
            {"valid_to": valid_to.isoformat(), "valid_to_n": date_to_int(valid_to)}, "version_id", version_id
        )

    async def update_acl(self, document_id: str, groups: list[str]) -> None:
        await self._set_payload({"acl_groups": groups}, "document_id", document_id)

    async def delete_version(self, version_id: str) -> None:
        await self.client.delete(
            self.collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[models.FieldCondition(key="version_id", match=models.MatchValue(value=version_id))]
                )
            ),
            wait=True,
        )
