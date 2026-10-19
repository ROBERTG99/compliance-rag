"""Context guard (FR-13): score each sentence of retrieved text for injected instructions.

Sentences scoring at least ``REMOVE_THRESHOLD`` (assistant-directed imperatives, "ignore previous
instructions", chat-role tokens, hidden Unicode) are removed before the text reaches the model.
Scoring is deterministic and pattern based; it never looks for the test canaries themselves.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

REMOVE_THRESHOLD = 0.7

_SENTENCE_RE = re.compile(r"\S(?:[^.!?]|[.!?](?=\S))*(?:[.!?]+|$)")
_HEADING_LINE = re.compile(r"^[ \t]*(?:#{1,6}[ \t]*\S.*|Article[ \t]+\d+\b.*)$", re.M)
_BLANK = re.compile(r"\n[ \t]*\n")
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
_HIDDEN = re.compile(
    "[\u200b\u200c\u200d\u2060\u2066-\u2069\u202a-\u202e\ufeff]"
)  # zero-width, bidi controls and BOM, written as escapes
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


def _regions(text: str) -> list[tuple[int, int, bool]]:
    """Paragraph regions separated by blank lines; heading lines become their own region."""
    regions: list[tuple[int, int, bool]] = []
    cursor = 0
    for h in _HEADING_LINE.finditer(text):
        if h.start() > cursor:
            regions.append((cursor, h.start(), False))
        regions.append((h.start(), h.end(), True))
        cursor = h.end()
    regions.append((cursor, len(text), False))
    out: list[tuple[int, int, bool]] = []
    for start, end, heading in regions:
        if heading:
            out.append((start, end, True))
            continue
        pos = start
        for blank in _BLANK.finditer(text, start, end):
            out.append((pos, blank.start(), False))
            pos = blank.end()
        out.append((pos, end, False))
    return [r for r in out if text[r[0] : r[1]].strip()]


def split_sentences(text: str) -> list[Sentence]:
    """Sentences end at . ! ? (not inside numbers), blank lines or heading lines; a single newline
    (PDF/DOCX line wrapping) is treated as a space."""
    out: list[Sentence] = []
    for start, end, heading in _regions(text):
        if heading:
            seg = text[start:end].strip()
            s0 = start + text[start:end].index(seg)
            out.append(Sentence(seg, s0, s0 + len(seg)))
            continue
        for m in _SENTENCE_RE.finditer(text, start, end):
            out.append(Sentence(m.group(0), m.start(), m.end()))
    return out


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
    """Blank out (same length) every sentence scoring at least ``threshold``.

    Blanking instead of cutting keeps character offsets valid, so citations into a guarded chunk still
    point at the right place in the extracted text.
    """
    chars = list(text)
    removed = 0
    max_score = 0.0
    for s in split_sentences(text):
        score = score_sentence(s.text)
        max_score = max(max_score, score)
        if score >= threshold:
            removed += 1
            for i in range(s.start, s.end):
                if chars[i] != "\n":
                    chars[i] = " "
    return GuardResult(text="".join(chars) if removed else text, removed=removed, max_score=max_score)
