"""Deterministic offline models per route (``DEMO_MODE=offline`` and tests).

* ``generate``: extractive composer — the context sentences with the highest overlap with the
  question become claims that quote themselves; below an overlap of 0.2 it abstains.
* ``condense_followup``: merges the previous question's content terms into the follow-up.
* ``judge``: ``evalgate.testing.FakeJudge``.
"""

from __future__ import annotations

import json
import re
from typing import Any

from compliance_rag.guard.context_guard import split_sentences
from compliance_rag.rerank.text import content_terms

MIN_OVERLAP = 0.2
MAX_CLAIMS = 3
RELATIVE_CUTOFF = 0.6


def _clean(sentence: str) -> str:
    return re.sub(r"\s+", " ", sentence).strip()


def compose_extractive(question: str, context: list[dict[str, Any]]) -> dict[str, Any]:
    q_terms = content_terms(question)
    scored: list[tuple[float, int, int, str, str]] = []
    for ci, chunk in enumerate(context):
        for si, sentence in enumerate(split_sentences(chunk["text"])):
            text = sentence.text.strip()
            if len(text) < 12 or len(text) > 400 or text.lower().startswith(("article ", "#")):
                continue
            s_terms = content_terms(text)
            if not q_terms or not s_terms:
                continue
            overlap = len(q_terms & s_terms) / len(q_terms)
            scored.append((overlap, ci, si, chunk["chunk_id"], text))
    scored.sort(key=lambda s: (-s[0], s[1], s[2]))
    if not scored or scored[0][0] < MIN_OVERLAP:
        return {"claims": [], "answer": "", "abstained": True}
    best = scored[0][0]
    claims: list[dict[str, Any]] = []
    seen: set[str] = set()
    covered: set[str] = set()
    for overlap, _ci, _si, chunk_id, text in scored:
        if len(claims) >= MAX_CLAIMS or overlap < max(MIN_OVERLAP, RELATIVE_CUTOFF * best):
            break
        key = _clean(text).lower()
        new_terms = content_terms(text) & q_terms - covered
        if key in seen or (claims and not new_terms):
            continue
        seen.add(key)
        covered |= content_terms(text) & q_terms
        claims.append({"text": _clean(text), "citations": [{"chunk_id": chunk_id, "quote": text}]})
    return {"claims": claims, "answer": " ".join(c["text"] for c in claims), "abstained": False}


def condense(question: str, previous_question: str | None, titles: list[str] | None = None) -> dict[str, str]:
    if not previous_question:
        return {"standalone_question": question}
    q_terms = content_terms(question)
    extra = [
        w
        for w in re.findall(r"[A-Za-z][A-Za-z-]+", previous_question)
        if w.lower() not in {"what", "how", "when", "is", "the", "for", "of", "a", "an"}
        and next(iter(content_terms(w)), "") not in q_terms
        and content_terms(w)
    ]
    context = " ".join(dict.fromkeys(extra))
    if titles:
        context = f"{context} ({'; '.join(titles)})"
    return {"standalone_question": f"{question.rstrip('?')} — regarding: {context}?".strip()}


class FakeLLM:
    model = "fake"

    def respond(self, route: str, data: dict[str, Any]) -> str:
        if route == "generate":
            return json.dumps(compose_extractive(data["question"], data.get("context", [])))
        if route == "condense_followup":
            return json.dumps(condense(data["question"], data.get("previous_question"), data.get("titles")))
        if route == "judge":
            from evalgate.testing import FakeJudge

            verdict = FakeJudge().grade(data["reference"], data["candidate"])
            return json.dumps({"verdict": "pass" if verdict.passed else "fail", "reason": verdict.reason})
        raise ValueError(f"no fake for route {route!r}")
