"""Coverage gate for `make test` (BUILD.md §10): ≥ 85% of lines in each core package, ≥ 70% overall.

Reads a Cobertura `coverage.xml` (pytest-cov) and counts lines per file, so packages are measured from the
actual line hits rather than the report's own rates.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

CORE = ("graph", "retrieval", "rerank", "guard", "auth", "ingest")
CORE_MIN, OVERALL_MIN = 85.0, 70.0


def _package(filename: str) -> str:
    parts = Path(filename).parts
    if "compliance_rag" in parts:
        rest = parts[parts.index("compliance_rag") + 1 :]
        return rest[0] if len(rest) > 1 else "(root)"
    return parts[0] if len(parts) > 1 else "(root)"


def check(path: Path) -> list[str]:
    root = ET.parse(path).getroot()
    hits: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for cls in root.iter("class"):
        package = _package(cls.get("filename", ""))
        for line in cls.iter("line"):
            hits[package][1] += 1
            hits[package][0] += int(line.get("hits", "0")) > 0
    failures = []
    for package in CORE:
        covered, total = hits.get(package, [0, 0])
        pct = 100.0 * covered / total if total else 0.0
        if pct < CORE_MIN:
            failures.append(f"{package}: {pct:.1f}% of {total} lines < {CORE_MIN:.0f}%")
    covered = sum(h[0] for h in hits.values())
    total = sum(h[1] for h in hits.values())
    overall = 100.0 * covered / total if total else 0.0
    if overall < OVERALL_MIN:
        failures.append(f"overall: {overall:.1f}% of {total} lines < {OVERALL_MIN:.0f}%")
    for package in sorted(hits):
        c, t = hits[package]
        print(f"{package:12s} {100.0 * c / t if t else 0.0:5.1f}% ({c}/{t})")
    print(f"{'overall':12s} {overall:5.1f}% ({covered}/{total})")
    return failures


def main(argv: list[str]) -> int:
    failures = check(Path(argv[0] if argv else "coverage.xml"))
    for f in failures:
        print(f"coverage gate: {f}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
