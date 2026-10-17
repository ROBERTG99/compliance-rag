"""`make eval`: run the offline suites, gate them and write the report (BUILD.md §11).

    uv run python scripts/run_evals.py                   # test split, check against the baseline
    uv run python scripts/run_evals.py --write-baseline  # also (re)write evals/reports/baseline.json
    uv run python scripts/run_evals.py --render-only     # re-render after `make eval-ablation` / `make redteam`

Writes the full run reports to `evals/reports/runs/` (gitignored), the summary served by
`GET /v1/evals/latest` to `evals/reports/latest.json` and `evals/REPORT.md`. Exits 1 if a gate fails.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from evalgate.check import check
from evalgate.runner import run_suite
from evalgate.suite import load_suite

from compliance_rag.evals.reporting import render_report, slim_baseline, summarize

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "evals" / "reports"
SUITES = ("rag", "retrieval")
MAX_REGRESSION_PP = 1.0


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def gate(reports: list[dict[str, Any]], baseline: dict[str, Any] | None) -> list[str]:
    failures: list[str] = []
    for report in reports:
        base = (baseline or {}).get(report["suite"])
        failures += [f"[{report['suite']}] {f}" for f in check(report, base, MAX_REGRESSION_PP)]
    return failures


def publish(
    reports: list[dict[str, Any]], failures: list[str], previous: dict[str, Any] | None = None
) -> dict[str, Any]:
    latest = summarize(
        reports, ablation=_load(REPORTS / "ablation.json"), redteam=_load(REPORTS / "redteam.json")
    )
    if previous is not None:  # re-rendering slim reports: the per-category table needs the full run's cases
        latest["by_category"] = previous.get("by_category", latest["by_category"])
    latest["passed"] = latest["passed"] and not failures
    _write(REPORTS / "latest.json", latest)
    (ROOT / "evals" / "REPORT.md").write_text(render_report(latest, failures=failures), encoding="utf-8")
    return latest


async def run_all(split: str, limit: int | None) -> list[dict[str, Any]]:
    reports = []
    for name in SUITES:
        report = await run_suite(load_suite(ROOT / "evals" / "suites" / f"{name}.yaml"), split, limit=limit)
        _write(REPORTS / "runs" / f"{name}.json", report)
        print(f"{name}: {'PASS' if report['passed'] else 'FAIL'} ({report['dataset']['n']} cases)")
        reports.append(report)
    return reports


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", default="test", choices=["dev", "test", "all"])
    parser.add_argument("--limit", type=int, default=0, help="first N cases per suite (smoke runs)")
    parser.add_argument("--write-baseline", action="store_true")
    parser.add_argument("--render-only", action="store_true", help="re-render from latest.json")
    args = parser.parse_args(argv)
    baseline = _load(REPORTS / "baseline.json")

    previous = None
    if args.render_only:
        latest = previous = _load(REPORTS / "latest.json")
        if latest is None:
            print("no evals/reports/latest.json yet: run `make eval` first", file=sys.stderr)
            return 1
        reports = list(latest["suites"].values())
    else:
        if args.split != "test" and not args.limit:
            print(f"note: reporting on the {args.split} split", file=sys.stderr)
        reports = asyncio.run(run_all(args.split, args.limit or None))
        if args.write_baseline:
            if args.split != "test" or args.limit:
                print("the baseline is the full test split only", file=sys.stderr)
                return 2
            baseline = slim_baseline(reports)
            _write(REPORTS / "baseline.json", baseline)

    failures = gate(reports, baseline)
    if args.render_only or (args.split == "test" and not args.limit):
        publish(reports, failures, previous)
        print("wrote evals/REPORT.md and evals/reports/latest.json")
    for failure in failures:
        print(f"FAIL {failure}", file=sys.stderr)
    print("all gates pass" if not failures else f"{len(failures)} gate failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
