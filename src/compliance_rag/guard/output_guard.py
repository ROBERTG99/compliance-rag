"""Output guard: block canary tokens and URLs that do not occur in the retrieved context."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

CANARY_RE = re.compile(r"\bCANARY-[0-9A-F]{6,}\b")
URL_RE = re.compile(r"https?://[^\s)\]>\"']+", re.I)


@dataclass(frozen=True)
class OutputCheck:
    ok: bool
    reasons: list[str] = field(default_factory=list)


def check_output(text: str, context_texts: list[str]) -> OutputCheck:
    reasons: list[str] = []
    if CANARY_RE.search(text):
        reasons.append("canary")
    context = "\n".join(context_texts)
    for url in URL_RE.findall(text):
        if url.rstrip(".,;:") not in context:
            reasons.append("url_not_in_context")
            break
    return OutputCheck(ok=not reasons, reasons=reasons)
