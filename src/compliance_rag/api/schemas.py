"""Response models for routes that build their bodies by hand, so the OpenAPI contract is complete."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Problem(BaseModel):
    """RFC 9457 problem details; extra members (``code``, ``errors``) are allowed."""

    model_config = ConfigDict(extra="allow")
    type: str
    title: str
    status: int
    instance: str | None = None
    detail: str | None = None
    code: str | None = None


class Health(BaseModel):
    status: Literal["ok"]


class Ready(BaseModel):
    status: Literal["ready", "unavailable"]
    checks: dict[str, str]


class Me(BaseModel):
    sub: str
    role: str
    groups: list[str]


class DocumentSummary(BaseModel):
    document_id: str
    title: str
    domain: str
    owner: str
    current_version: int | None
    versions: int
    restricted: bool
    acl_groups: list[str] | None = Field(default=None, description="content_admin only")


class DocumentPage(BaseModel):
    items: list[DocumentSummary]
    next_cursor: str | None


class VersionEntry(BaseModel):
    version: int
    status: str
    source_format: str
    valid_from: str
    valid_to: str | None
    uploaded_at: str
    activated_at: str | None
    size_bytes: int | None
    chunks: int
    in_force: bool


class DocumentDetail(BaseModel):
    document_id: str
    title: str
    domain: str
    owner: str
    restricted: bool
    versions: list[VersionEntry]
    acl_groups: list[str] | None = Field(default=None, description="content_admin only")


class ChunkOut(BaseModel):
    chunk_id: str
    document_id: str
    version: int
    section_path: str
    text: str
    char_start: int
    char_end: int
    valid_from: str
    valid_to: str | None
    title: str
    current_version: int | None
    superseded: bool


class AclAccepted(BaseModel):
    job_id: str
    document_id: str
    groups: list[str]
    indexes_synced: bool


class JobOut(BaseModel):
    job_id: str
    kind: str
    document_id: str
    version: int | None
    status: str
    attempts: int
    error: str | None
    requested_by: str
    enqueued_at: str | None
    finished_at: str | None
    chunk_count: int | None


class JobPage(BaseModel):
    items: list[JobOut]


class IndexLag(BaseModel):
    p50_s: float
    p95_s: float
    pending: int
    oldest_pending_s: float


class EvalsLatest(BaseModel):
    """Summary written by ``scripts/run_evals.py``; numbers are copied from the report, never computed here."""

    model_config = ConfigDict(extra="allow")
    generated_at: str
    split: str
    llm: str
    metrics: dict[str, Any]
    ablation: list[dict[str, Any]] = Field(default_factory=list)
