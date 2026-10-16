"""Context guard (FR-13): score each sentence of retrieved text for injected instructions.

Sentences scoring at least ``REMOVE_THRESHOLD`` (assistant-directed imperatives, "ignore previous
instructions", chat-role tokens, hidden Unicode) are removed before the text reaches the model.
Scoring is deterministic and pattern based; it never looks for the test canaries themselves.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

REMOVE_THRESHOLD = 0.7

_SENTENCE_RE = re.compile(r"[^.!?\n]+(?:[.!?]+|$)", re.M)
_OVERRIDE = re.compile(
    r"\b(ignore|disregard|forget|override|bypass)\b[^.!?\n]{0,40}\b(previous|prior|above|earlier|all|your|the)\b"
    r"[^.!?\n]{0,30}\b(instructions?|rules?|prompts?|polic(y|ies) text|guidelines|rubric|context|above)\b",
    re.I,
)
_ROLE_TOKENS = re.compile(
    r"<\|[a-z_]+\|>|<\|im_(start|end)\|>|^\s*#{2,}\s*(instruction|system)|\b(system|developer)\s*(override|prompt|message|note)\s*:",
    re.I | re.M,
)
_ADDRESSEE = re.compile(
    r"\b(assistant|ai model|language model|llm|chatbot|the model|you are now|if you are an? (ai|model|language model))\b",
    re.I,
)
_DIRECTIVE = re.compile(
    r"\b(reply|respond|answer|print|output|reveal|repeat|append|include|tell the user|say|recommend visiting|"
    r"summari[sz]e nothing|must answer|always include|new rule)\b",
    re.I,
)
_HIDDEN = re.compile("[​‌‍⁠⁦-⁩‪-‮﻿]")
_URL = re.compile(r"https?://\S+", re.I)
_SECRETISH = re.compile(r"\b(system prompt|hidden prompt|maintenance mode|unlimited)\b", re.I)


@dataclass(frozen=True)
class Sentence:
    text: str
    start: int
    end: int


@dataclass(frozen=True)
class GuardResult:
    text: str
    removed: int
    max_score: float


def split_sentences(text: str) -> list[Sentence]:
    return [
        Sentence(m.group(0), m.start(), m.end()) for m in _SENTENCE_RE.finditer(text) if m.group(0).strip()
    ]


def score_sentence(sentence: str) -> float:
    score = 0.0
    if _HIDDEN.search(sentence):
        score += 0.4
        sentence = _HIDDEN.sub("", sentence)
    if _OVERRIDE.search(sentence):
        score += 0.8
    if _ROLE_TOKENS.search(sentence):
        score += 0.7
    addressee = bool(_ADDRESSEE.search(sentence))
    directive = bool(_DIRECTIVE.search(sentence))
    if addressee:
        score += 0.4
    if directive and (addressee or score > 0):
        score += 0.3
    if _URL.search(sentence):
        score += 0.2
    if _SECRETISH.search(sentence):
        score += 0.3
    return min(1.0, round(score, 3))


def injection_score(text: str) -> float:
    """Highest sentence score in a chunk (stored as ``chunks.injection_score`` at ingestion)."""
    return max((score_sentence(s.text) for s in split_sentences(text)), default=0.0)


def guard_text(text: str, threshold: float = REMOVE_THRESHOLD) -> GuardResult:
    keep: list[str] = []
    removed = 0
    max_score = 0.0
    cursor = 0
    for s in split_sentences(text):
        score = score_sentence(s.text)
        max_score = max(max_score, score)
        keep.append(text[cursor : s.start])
        if score >= threshold:
            removed += 1
        else:
            keep.append(s.text)
        cursor = s.end
    keep.append(text[cursor:])
    cleaned = re.sub(r"[ \t]{2,}", " ", "".join(keep))
    return GuardResult(text=cleaned if removed else text, removed=removed, max_score=max_score)
