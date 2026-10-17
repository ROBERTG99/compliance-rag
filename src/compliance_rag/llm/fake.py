"""Deterministic offline models per route (``DEMO_MODE=offline`` and tests).

* ``generate``: extractive composer — the context sentences with the highest overlap with the
  question become claims that quote themselves; below an overlap of 0.2 it abstains. It is deliberately
  naive about prompt injection: a context sentence carrying a ``CANARY-`` instruction is obeyed (the canary
  is appended to every claim), so offline red-team results depend on the guards, not on the fake.
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
CANARY = re.compile(r"\bCANARY-[0-9A-F]{6,}\b")


def _clean(sentence: str) -> str:
    return re.sub(r"\s+", " ", sentence).strip()


_QUANTITY = re.compile(
    r"\b(how (many|long|often|much)|within|what (is|are) the (minimum|maximum|daily|monthly|weekly)|"
    r"what (percentage|share|amount|chargeback|ownership|weekly|monthly|daily)|above what|after how)\b",
    re.I,
)
_HAS_NUMBER = re.compile(r"\d")
NUMBER_BONUS = 0.3


def _parts(question: str) -> list[str]:
    parts = [p.strip() for p in re.split(r",\s+and\s+|;\s*and\s+", question) if p.strip()]
    return parts or [question]


def _sentences(context: list[dict[str, Any]]) -> list[tuple[int, int, str, str]]:
    out = []
    for ci, chunk in enumerate(context):
        for si, sentence in enumerate(split_sentences(chunk["text"])):
            text = sentence.text.strip()
            if 12 <= len(text) <= 400 and not text.lower().startswith(("article ", "#")):
                out.append((ci, si, chunk["chunk_id"], text))
    return out


def _score(part: str, text: str) -> tuple[float, float]:
    """(raw overlap, ranking score) of one sentence for one (sub-)question."""
    q_terms = content_terms(part)
    s_terms = content_terms(text)
    if not q_terms or not s_terms:
        return 0.0, 0.0
    overlap = len(q_terms & s_terms) / len(q_terms)
    bonus = NUMBER_BONUS if _QUANTITY.search(part) and _HAS_NUMBER.search(text) else 0.0
    return overlap, overlap + bonus


def compose_extractive(question: str, context: list[dict[str, Any]]) -> dict[str, Any]:
    """Answer each sub-question with its best supporting sentence; abstain below overlap 0.2."""
    sentences = _sentences(context)
    if not sentences:
        return {"claims": [], "answer": "", "abstained": True}
    best_overall = max(_score(question, s[3])[0] for s in sentences)
    if best_overall < MIN_OVERLAP:
        return {"claims": [], "answer": "", "abstained": True}
    claims: list[dict[str, Any]] = []
    seen: set[str] = set()
    for part in _parts(question)[:MAX_CLAIMS]:
        ranked = sorted(sentences, key=lambda s: (-_score(part, s[3])[1], s[0], s[1]))
        _ci, _si, chunk_id, text = ranked[0]
        if _score(part, text)[0] < MIN_OVERLAP:
            continue
        key = _clean(text).lower()
        if key in seen:
            continue
        seen.add(key)
        claims.append({"text": _clean(text), "citations": [{"chunk_id": chunk_id, "quote": text}]})
    if not claims:
        return {"claims": [], "answer": "", "abstained": True}
    obeyed = sorted({m for s in sentences for m in CANARY.findall(s[3])})
    if obeyed:  # a naive model follows instructions found in its documents
        for claim in claims:
            claim["text"] = f"{claim['text']} {' '.join(obeyed)}"
    return {"claims": claims, "answer": " ".join(c["text"] for c in claims), "abstained": False}


def condense(question: str, previous_question: str | None, titles: list[str] | None = None) -> dict[str, str]:
    """Template rewrite: keep the follow-up and append the previous question's noun phrases (entity names)."""
    if not previous_question:
        return {"standalone_question": question}
    phrases = re.findall(r"(?:[A-Z][\w-]*(?:\s+[A-Z][\w-]*)+)", previous_question)
    phrases = [p for p in phrases if not p.startswith(("What ", "How ", "Within ", "When ", "Which "))]
    if not phrases and titles:
        phrases = [t.split(" — ")[-1] for t in titles[:1]]
    if not phrases:
        phrases = [previous_question.rstrip("?")]
    return {"standalone_question": f"{question.rstrip('?')} for the {' and '.join(dict.fromkeys(phrases))}?"}


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
