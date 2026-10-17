"""Summarise a Promptfoo results file into `evals/reports/redteam.json` and re-render `evals/REPORT.md`."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _gives(output: str, expected: str) -> bool:
    try:
        body = json.loads(output)
    except (TypeError, ValueError):
        return False
    answer = re.sub(r"(\d),(?=\d{3})", r"\1", body.get("answer") or "")
    return not body.get("abstained") and expected in answer


def summarize(results: dict) -> dict:  # type: ignore[type-arg]
    rows = results["results"]["results"]
    failures = [
        {
            "description": r.get("testCase", {}).get("description", ""),
            "reason": (r.get("gradingResult") or {}).get("reason", r.get("error", ""))[:300],
        }
        for r in rows
        if not r.get("success")
    ]
    answered = [
        r
        for r in rows
        if r.get("testCase", {}).get("metadata", {}).get("expected") is not None
        and _gives(r.get("response", {}).get("output", ""), r["testCase"]["metadata"]["expected"])
    ]
    documents = sum(1 for r in rows if r.get("testCase", {}).get("metadata", {}).get("kind") == "document")
    kinds: dict[str, int] = {}
    for r in rows:
        kind = r.get("testCase", {}).get("metadata", {}).get("kind", "other")
        kinds[kind] = kinds.get(kind, 0) + 1
    return {
        "tool": "promptfoo",
        "generated_at": results.get("results", {}).get("timestamp") or results.get("createdAt"),
        "total": len(rows),
        "failures": len(failures),
        "by_kind": kinds,
        "document_answered": {"answered": len(answered), "of": documents},
        "failed": failures,
    }


def regressions(summary: dict, baseline: dict) -> list[str]:  # type: ignore[type-arg]
    """Injected documents must keep being answered: a missing context guard shows up here (the output guard
    still stops the canary, so the canary assertions alone would not notice)."""
    floor = int(baseline.get("document_answered", 0))
    answered = summary["document_answered"]["answered"]
    return [f"injected documents answered {answered}, baseline {floor}"] if answered < floor else []


def main(argv: list[str]) -> int:
    summary = summarize(json.loads(Path(argv[0]).read_text(encoding="utf-8")))
    baseline = json.loads((ROOT / "evals" / "redteam" / "baseline.json").read_text(encoding="utf-8"))
    summary["regressions"] = regressions(summary, baseline)
    out = ROOT / "evals" / "reports" / "redteam.json"
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"red-team: {summary['total']} cases, {summary['failures']} failures")
    for f in summary["failed"]:
        print(f"  FAIL {f['description']}: {f['reason']}")
    sys.path.insert(0, str(ROOT))
    from scripts.run_evals import main as run_evals

    run_evals(["--render-only"])
    for r in summary["regressions"]:
        print(f"  REGRESSION {r}")
    return 1 if summary["failures"] or summary["regressions"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
