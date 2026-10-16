"""Shared lexical helpers for reranking and the extractive composer."""

from __future__ import annotations

import re

STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "do",
        "does",
        "for",
        "from",
        "has",
        "have",
        "how",
        "in",
        "is",
        "it",
        "its",
        "long",
        "many",
        "may",
        "much",
        "must",
        "of",
        "on",
        "or",
        "per",
        "the",
        "their",
        "there",
        "these",
        "this",
        "to",
        "under",
        "was",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "within",
        "above",
        "after",
        "any",
        "be",
        "before",
        "each",
        "every",
        "more",
        "than",
        "over",
        "our",
        "northwind",
        "policy",
    ]
)
_WORD = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)*")


def _stem(word: str) -> str:
    """Light suffix stripping so "escalated"/"escalate" and "records"/"record" match."""
    if len(word) <= 4:
        return word
    for suffix, repl in (
        ("ies", "y"),
        ("ied", "y"),
        ("ing", ""),
        ("ed", ""),
        ("es", ""),
        ("s", ""),
        ("ly", ""),
    ):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[: -len(suffix)] + repl
            break
    return word[:-1] if word.endswith("e") and len(word) > 4 else word


# Small compliance lexicon: map paraphrases onto one canonical term after stemming
# ("must not be older than" ~ "maximum age", "capped at" ~ "cap", "every N months" ~ "how often").
CANONICAL = {
    "older": "age",
    "old": "age",
    "exceed": "maximum",
    "max": "maximum",
    "most": "maximum",
    "cap": "maximum",
    "capp": "maximum",
    "least": "minimum",
    "min": "minimum",
    "often": "frequency",
    "every": "frequency",
    "frequent": "frequency",
}


def content_terms(text: str) -> set[str]:
    terms: set[str] = set()
    for word in _WORD.findall(text.lower()):
        for part in word.split("-"):
            if part and part not in STOPWORDS and not part.isdigit():
                stem = _stem(part)
                terms.add(CANONICAL.get(stem, stem))
    return terms


_PROPER = re.compile(r"(?<![.?!]\s)(?<!^)\b[A-Z][a-zA-Z]+(?:[-'][A-Za-z]+)*")


def entity_terms(question: str) -> set[str]:
    """Content terms of capitalised words that are not sentence-initial (product and entity names)."""
    words = [m.group(0) for m in _PROPER.finditer(question.strip())]
    return content_terms(" ".join(words))
