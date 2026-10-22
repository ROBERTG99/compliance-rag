"""Citation verification.

A claim survives only if, for every citation: the chunk is in the context given to the model, the
quote is an exact substring of that chunk after NFKC + whitespace normalisation, and every number or
date in the claim appears in the claim's quotes. Rejected claims are reported with a reason. If the
free-text ``answer`` mentions a number absent from the verified claims it is replaced by the verified
claims joined. No verified claims → abstain (``no_verified_claims``).
"""

from __future__ import annotations

import re
import unicodedata

from compliance_rag.graph.state import Claim, GeneratedAnswer, VerifiedAnswer, VerifiedCitation, VerifiedClaim
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


def _cuts_number(text: str, start: int, end: int) -> bool:
    """True when [start, end) begins or ends inside a number such as ``1,000`` or ``2.5``."""

    def joined(i: int) -> bool:  # text[i] continues a number from text[i - 1]
        if i <= 0 or i >= len(text):
            return False
        prev, cur = text[i - 1], text[i]
        if prev.isdigit() and cur.isdigit():
            return True
        if cur in ",." and prev.isdigit() and i + 1 < len(text) and text[i + 1].isdigit():
            return True
        return prev in ",." and cur.isdigit() and i >= 2 and text[i - 2].isdigit()

    return joined(start) or joined(end)


def locate(quote: str, text: str) -> tuple[int, int] | None:
    """Return (start, end) of ``quote`` inside the original ``text`` using normalised matching.

    A match that starts or ends inside a number ("EUR 1" inside "EUR 1,000") is not a match.
    """
    norm_text, mapping = _normalized_with_map(text)
    q = normalize(quote)
    if not q:
        return None
    idx = norm_text.find(q)
    while idx >= 0:
        if not _cuts_number(norm_text, idx, idx + len(q)):
            return mapping[idx], mapping[idx + len(q) - 1] + 1
        idx = norm_text.find(q, idx + 1)
    return None


def verify_claim(
    claim: Claim, by_id: dict[str, Candidate], numbering: dict[str, int], index: int
) -> tuple[VerifiedClaim | None, str | None]:
    """Verify one claim. Citation numbers come from ``numbering`` (shared across a run) and are only
    assigned when the claim is accepted, so streamed and final numbering agree."""
    spans: list[tuple[Candidate, str, tuple[int, int]]] = []
    for cit in claim.citations:
        chunk = by_id.get(cit.chunk_id)
        if chunk is None:
            return None, "chunk_not_in_context"
        span = locate(cit.quote, chunk["text"])
        if span is None:
            return None, "quote_not_found"
        spans.append((chunk, cit.quote, span))
    quoted = set().union(*(numbers(c.quote) for c in claim.citations))
    if not numbers(claim.text) <= quoted:
        return None, "numeric_mismatch"
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
    return VerifiedClaim(index=index, text=claim.text, citations=citations), None


def final_answer(draft_answer: str, claims: list[VerifiedClaim]) -> str:
    """Keep the model's summary only if every number in it is backed by a verified claim."""
    verified_numbers = set().union(*(numbers(c.text) for c in claims)) if claims else set()
    answer = draft_answer.strip()
    if not answer or not numbers(answer) <= verified_numbers:
        return " ".join(c.text for c in claims)
    return answer


def verify_citations(draft: GeneratedAnswer, context: list[Candidate]) -> VerifiedAnswer:
    by_id = {c["chunk_id"]: c for c in context}
    claims: list[VerifiedClaim] = []
    rejected: list[dict[str, object]] = []
    numbering: dict[str, int] = {}
    for idx, claim in enumerate(draft.claims):
        verified, reason = verify_claim(claim, by_id, numbering, len(claims))
        if verified is None:
            rejected.append({"index": idx, "reason": reason})
            continue
        claims.append(verified)
    if not claims:
        return VerifiedAnswer(claims=[], answer="", rejected=rejected, abstained=True)
    return VerifiedAnswer(
        claims=claims, answer=final_answer(draft.answer, claims), rejected=rejected, abstained=False
    )
