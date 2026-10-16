"""Graph state and model output schemas (BUILD.md §4.6)."""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from compliance_rag.obs.steps import StepRecord
from compliance_rag.retrieval.types import Candidate, Principal


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chunk_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    quote: str = Field(min_length=12, max_length=400)


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(max_length=600)
    citations: list[Citation] = Field(min_length=1, max_length=3)


class GeneratedAnswer(BaseModel):  # claims first so they can stream
    model_config = ConfigDict(extra="forbid")
    claims: list[Claim] = Field(max_length=8)
    answer: str = Field(max_length=1200)
    abstained: bool


class VerifiedCitation(BaseModel):
    n: int
    chunk_id: str
    document_id: str
    version: int
    quote: str
    char_start: int
    char_end: int


class VerifiedClaim(BaseModel):
    index: int
    text: str
    citations: list[VerifiedCitation]


class VerifiedAnswer(BaseModel):
    claims: list[VerifiedClaim]
    answer: str
    rejected: list[dict[str, Any]]
    abstained: bool


AbstainReason = Literal["low_score", "no_valid_document", "no_verified_claims", "refusal"]


class RagState(TypedDict, total=False):
    run_id: str
    conversation_id: str
    question: str
    standalone_question: str
    follow_up_of: str | None
    previous: dict[str, Any] | None
    as_of: str
    principal: Principal
    bm25_hits: list[Candidate]
    vector_hits: list[Candidate]
    fused: list[Candidate]
    reranked: list[Candidate]
    context: list[Candidate]  # top CRAG_TOPK_CONTEXT=8
    removed_sentences: int
    draft: dict[str, Any] | None  # verified claims, model summary, rejections (JSON-serialisable)
    verified: dict[str, Any] | None  # VerifiedAnswer.model_dump()
    abstained: bool
    abstain_reason: AbstainReason | None
    degraded: list[str]
    confidence: float
    cost_usd: float
    steps: Annotated[list[StepRecord], operator.add]
