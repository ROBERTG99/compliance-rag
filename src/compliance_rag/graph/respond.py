"""AnswerResponse assembly. Abstentions are uniform: no reason, no confidence, no documents."""

from __future__ import annotations

from typing import Any

ABSTAIN_MESSAGE = (
    "I can't answer that from the policy documents available to you. Try rephrasing, or ask the policy owner."
)
LABEL = "AI-generated"


def cited_versions(state: dict[str, Any]) -> list[dict[str, Any]]:
    verified = state.get("verified") or {}
    by_chunk = {c["chunk_id"]: c for c in state.get("context") or []}
    seen: dict[tuple[str, int], dict[str, Any]] = {}
    for claim in verified.get("claims", []):
        for cit in claim["citations"]:
            chunk = by_chunk.get(cit["chunk_id"], {})
            key = (cit["document_id"], int(cit["version"]))
            if key not in seen:
                valid_to = chunk.get("valid_to")
                seen[key] = {
                    "document_id": key[0],
                    "version": key[1],
                    "title": chunk.get("title", ""),
                    "valid_from": chunk.get("valid_from"),
                    "valid_to": valid_to,
                    "superseded": valid_to is not None,
                }
    return list(seen.values())


def build_response(state: dict[str, Any]) -> dict[str, Any]:
    base = {
        "run_id": state["run_id"],
        "conversation_id": state["conversation_id"],
        "as_of": state["as_of"],
        "degraded": list(state.get("degraded") or []),
        "latency_ms": int(state.get("latency_ms", 0)),
        "label": LABEL,
    }
    if state.get("abstained"):
        return {
            **base,
            "answer": "",
            "claims": [],
            "abstained": True,
            "message": ABSTAIN_MESSAGE,
            "versions": [],
            "confidence": None,
            "cost_usd": round(float(state.get("cost_usd", 0.0)), 6),
        }
    verified = state["verified"]
    return {
        **base,
        "answer": verified["answer"],
        "claims": verified["claims"],
        "abstained": False,
        "message": None,
        "versions": cited_versions(state),
        "confidence": round(float(state.get("confidence", 0.0)), 3),
        "cost_usd": round(float(state.get("cost_usd", 0.0)), 6),
    }
