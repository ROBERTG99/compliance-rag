"""Held-out test split registry: feedback triage may only add cases to the dev split."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

_SPACE = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]")


class SplitRegistryUnavailable(RuntimeError):
    """No question dataset found, so test-split membership cannot be checked (fail closed)."""


def question_key(question: str) -> str:
    """Normalised hash so whitespace, case, punctuation and Unicode form do not hide a test question."""
    text = _PUNCT.sub(" ", unicodedata.normalize("NFKC", question).casefold())
    text = _SPACE.sub(" ", text).strip()
    return hashlib.sha256(text.encode()).hexdigest()


@lru_cache(maxsize=4)
def test_question_keys(datasets_dir: str) -> frozenset[str]:
    files = sorted(Path(datasets_dir).glob("questions.v*.jsonl"))
    if not files:
        raise SplitRegistryUnavailable(f"no questions.v*.jsonl under {datasets_dir}")
    keys: set[str] = set()
    for path in files:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("split") == "test":
                keys.add(question_key(str(row["input"]["question"])))
    return frozenset(keys)


def in_test_split(question: str, datasets_dir: str | Path) -> bool:
    return question_key(question) in test_question_keys(str(datasets_dir))
