"""Citation verification (FR-9).

A claim survives only if, for every citation: the chunk is in the context given to the model, the
quote is an exact substring of that chunk after NFKC + whitespace normalisation, and every number or
date in the claim appears in the claim's quotes. Rejected claims are reported with a reason. If the
free-text ``answer`` mentions a number absent from the verified claims it is replaced by the verified
claims joined. No verified claims → abstain (``no_verified_claims``).
"""

from __future__ import annotations

import re
import unicodedata

from compliance_rag.graph.state import GeneratedAnswer, VerifiedAnswer, VerifiedCitation, VerifiedClaim
from compliance_rag.retrieval.types import Candidate

_WS = re.compile(r"\s+")
_NUM = re.compile(r"\d{4}-\d{2}-\d{2}|\d[\d,]*(?:\.\d+)?")


def normalize(text: str) -> str:
    return _WS.sub(" ", unicodedata.normalize("NFKC", text)).strip()


def numbers(text: str) -> set[str]:
    out = set()
    for token in _NUM.findall(unicodedata.normalize("NFKC", text)):
        token = token.rstrip(".,")
        out.add(token if "-" in token else token.replace(",", ""))
    return out


def _normalized_with_map(text: str) -> tuple[str, list[int]]:
    """NFKC + whitespace-collapse ``text`` and map each output char back to its source index."""
    out: list[str] = []
    mapping: list[int] = []
    pending_space = False
    for i, ch in enumerate(text):
        norm = unicodedata.normalize("NFKC", ch)
        for c in norm:
            if c.isspace():
                pending_space = bool(out)
                continue
            if pending_space:
                out.append(" ")
                mapping.append(i)
                pending_space = False
            out.append(c)
            mapping.append(i)
    return "".join(out), mapping


def locate(quote: str, text: str) -> tuple[int, int] | None:
    """Return (start, end) of ``quote`` inside the original ``text`` using normalised matching."""
    norm_text, mapping = _normalized_with_map(text)
    q = normalize(quote)
    idx = norm_text.find(q)
    if idx < 0 or not q:
        return None
    start = mapping[idx]
    end = mapping[idx + len(q) - 1] + 1
    return start, end


def verify_citations(draft: GeneratedAnswer, context: list[Candidate]) -> VerifiedAnswer:
    by_id = {c["chunk_id"]: c for c in context}
    claims: list[VerifiedClaim] = []
    rejected: list[dict[str, object]] = []
    numbering: dict[str, int] = {}  # citation [n] per chunk, assigned in order of accepted claims
    for idx, claim in enumerate(draft.claims):
        reason: str | None = None
        spans: list[tuple[Candidate, str, tuple[int, int]]] = []
        for cit in claim.citations:
            chunk = by_id.get(cit.chunk_id)
            if chunk is None:
                reason = "chunk_not_in_context"
                break
            span = locate(cit.quote, chunk["text"])
            if span is None:
                reason = "quote_not_found"
                break
            spans.append((chunk, cit.quote, span))
        if reason is None:
            quoted = set().union(*(numbers(c.quote) for c in claim.citations))
            if not numbers(claim.text) <= quoted:
                reason = "numeric_mismatch"
        if reason is not None:
            rejected.append({"index": idx, "reason": reason})
            continue
        citations = []
        for chunk, quote, (start, end) in spans:
            offset = chunk.get("char_start", 0)
            citations.append(
                VerifiedCitation(
                    n=numbering.setdefault(chunk["chunk_id"], len(numbering) + 1),
                    chunk_id=chunk["chunk_id"],
                    document_id=chunk["document_id"],
                    version=int(chunk["version"]),
                    quote=quote,
                    char_start=offset + start,
                    char_end=offset + end,
                )
            )
        claims.append(VerifiedClaim(index=len(claims), text=claim.text, citations=citations))
    if not claims:
        return VerifiedAnswer(claims=[], answer="", rejected=rejected, abstained=True)
    verified_numbers = set().union(*(numbers(c.text) for c in claims))
    answer = draft.answer.strip()
    if not answer or not numbers(answer) <= verified_numbers:
        answer = " ".join(c.text for c in claims)
    return VerifiedAnswer(claims=claims, answer=answer, rejected=rejected, abstained=False)
