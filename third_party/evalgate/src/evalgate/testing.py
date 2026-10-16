"""Testing helpers (evalgate FR-13 subset): FakeJudge.

FakeJudge passes a candidate that contains every key fact (numbers, dates) of the reference and no
contradicting number; injection phrases force a fail.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_INJECTION = re.compile(r"ignore (the|all|previous)|answer pass|disregard|you are now", re.I)


def normalize_number(token: str) -> str:
    return token.replace(",", "").rstrip(".")


def numbers(text: str) -> set[str]:
    return {normalize_number(m) for m in _NUMBER.findall(text)}


@dataclass(frozen=True)
class JudgeVerdict:
    passed: bool
    reason: str


class FakeJudge:
    """Deterministic rule-based judge used offline and in tests."""

    def grade(self, reference: str, candidate: str) -> JudgeVerdict:
        if _INJECTION.search(candidate):
            return JudgeVerdict(False, "injection_pattern")
        ref, cand = numbers(reference), numbers(candidate)
        missing = ref - cand
        if missing:
            return JudgeVerdict(False, f"missing:{','.join(sorted(missing))}")
        extra = cand - ref
        if extra:
            return JudgeVerdict(False, f"contradicting:{','.join(sorted(extra))}")
        if not ref and len(candidate.strip()) < 3:
            return JudgeVerdict(False, "empty")
        return JudgeVerdict(True, "ok")
