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
    for suffix in ("ies", "es", "s"):
        if len(word) > 4 and word.endswith(suffix):
            return word[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return word


def content_terms(text: str) -> set[str]:
    terms: set[str] = set()
    for word in _WORD.findall(text.lower()):
        for part in word.split("-"):
            if part and part not in STOPWORDS and not part.isdigit():
                terms.add(_stem(part))
    return terms
