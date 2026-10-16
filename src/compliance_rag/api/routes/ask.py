"""Walking-skeleton ask route: a fixed context answered by an extractive fake (replaced in T-27)."""

import uuid
from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(tags=["ask"])

_SKELETON_CHUNK = {
    "chunk_id": "0" * 32,
    "document_id": "KYC-0042",
    "version": 3,
    "text": "A proof-of-address document must not be older than 90 days at onboarding.",
}


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    stream: bool = False


@router.post("/v1/ask")
async def ask(req: AskRequest) -> dict[str, object]:
    quote = _SKELETON_CHUNK["text"]
    citation = {
        "n": 1,
        "chunk_id": _SKELETON_CHUNK["chunk_id"],
        "document_id": _SKELETON_CHUNK["document_id"],
        "version": _SKELETON_CHUNK["version"],
        "quote": quote,
        "char_start": 0,
        "char_end": len(str(quote)),
    }
    return {
        "run_id": str(uuid.uuid4()),
        "conversation_id": str(uuid.uuid4()),
        "answer": quote,
        "claims": [{"index": 0, "text": quote, "citations": [citation]}],
        "abstained": False,
        "message": None,
        "as_of": date.today().isoformat(),
        "versions": [{"document_id": "KYC-0042", "version": 3}],
        "confidence": 1.0,
        "degraded": [],
        "cost_usd": 0.0,
        "latency_ms": 0,
        "label": "AI-generated",
    }
