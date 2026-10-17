"""Judge calibration: agreement between a judge and human/construction labels."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol


class Judge(Protocol):
    def grade(self, reference: str, candidate: str) -> Any: ...


def calibrate(labels_path: str | Path, judge: Judge, split: str | None = None) -> dict[str, Any]:
    rows = [
        json.loads(line)
        for line in Path(labels_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if split:
        rows = [r for r in rows if r.get("split") == split]
    agree = 0
    disagreements: list[dict[str, Any]] = []
    for row in rows:
        verdict = judge.grade(row["reference"], row["candidate"])
        if int(bool(verdict.passed)) == int(row["label"]):
            agree += 1
        else:
            disagreements.append(
                {"id": row["id"], "label": row["label"], "reason": getattr(verdict, "reason", "")}
            )
    return {"n": len(rows), "agreement": agree / len(rows) if rows else 0.0, "disagreements": disagreements}
