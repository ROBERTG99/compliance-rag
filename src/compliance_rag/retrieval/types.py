"""Shared retrieval types."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, TypedDict

import numpy as np
import numpy.typing as npt

Role = Literal["analyst", "legal", "support", "content_admin"]


class Principal(TypedDict):
    sub: str
    role: Role
    groups: list[str]


class Candidate(TypedDict):
    chunk_id: str
    document_id: str
    version: int
    text: str
    acl_groups: list[str]
    valid_from: str
    valid_to: str | None
    bm25: float | None
    cosine: float | None
    rrf: float
    rerank: float | None
    title: str
    section_path: str
    char_start: int
    char_end: int
    injection_score: float


def make_candidate(**kwargs: object) -> Candidate:
    base: dict[str, object] = {
        "bm25": None,
        "cosine": None,
        "rrf": 0.0,
        "rerank": None,
        "title": "",
        "section_path": "",
        "char_start": 0,
        "char_end": 0,
        "injection_score": 0.0,
        "valid_to": None,
    }
    base.update(kwargs)
    return base  # type: ignore[return-value]


@dataclass
class ChunkRecord:
    """One chunk as written to Postgres, OpenSearch and Qdrant."""

    chunk_id: str
    version_id: str
    document_id: str
    version: int
    title: str
    domain: str
    ordinal: int
    section_path: str
    text: str
    char_start: int
    char_end: int
    token_count: int
    injection_score: float
    acl_groups: list[str]
    valid_from: date
    valid_to: date | None
    visible: bool
    embedding: npt.NDArray[np.float32]
