"""Documentation deliverables of BUILD.md §18; every number in the README cites where it comes from (T-49)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REQUIRED = [
    "README.md",
    "docs/architecture.md",
    "docs/evaluation.md",
    "evals/REPORT.md",
    "docs/security.md",
    "docs/runbook.md",
    "docs/DEVELOPMENT.md",
    "docs/KNOWN_LIMITATIONS.md",
    "docs/verification.md",
    "docs/ai-development.md",
    "docs/design-faq.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CHANGELOG.md",
    "LICENSE",
]
ADRS = ["0001", "0002", "0003", "0004", "0005", "0006", "0007", "0008", "0009"]
README_SECTIONS = [
    "Problem",
    "Result",
    "Architecture",
    "Quick start",
    "Evaluation",
    "Guardrails",
    "Decisions",
    "Limitations",
    "How this was built",
    "License",
]
# a measured number: a 3-decimal rate, a millisecond figure or an "x of y"/"x/y" count
NUMBER = re.compile(r"\b0\.\d{3}\b|\b\d+(?:\.\d+)? ms\b|\b\d+ of \d+\b")
SOURCE = re.compile(r"\]\((?:evals/|docs/|PROGRESS\.md)[^)]*\)|`make [a-z-]+`")
REPORTS = ["evals/REPORT.md", "evals/reports/bench.json", "evals/reports/redteam.json", "PROGRESS.md"]


def test_documents_exist() -> None:
    missing = [p for p in REQUIRED if not (ROOT / p).is_file()]
    assert not missing, missing
    adrs = sorted(p.name[:4] for p in (ROOT / "docs/adr").glob("*.md"))
    assert adrs == ADRS


def test_readme_sections_in_portfolio_order() -> None:
    headings = [
        line[3:].strip() for line in (ROOT / "README.md").read_text().splitlines() if line.startswith("## ")
    ]
    positions = [next(i for i, h in enumerate(headings) if h.startswith(name)) for name in README_SECTIONS]
    assert positions == sorted(positions), headings


def test_readme_numbers_cite_sources() -> None:
    texts = {p: (ROOT / p).read_text(encoding="utf-8") for p in REPORTS}
    unsourced, unknown = [], []
    for line in (ROOT / "README.md").read_text(encoding="utf-8").splitlines():
        numbers = NUMBER.findall(line)
        if not numbers:
            continue
        if not SOURCE.search(line):
            unsourced.append(line)
        # a number must appear in the report its own line links to (any report for a make target or a doc)
        linked = [p for p in REPORTS if f"]({p}" in line]
        sources = "\n".join(texts[p] for p in linked or REPORTS)
        unknown += [(n, linked) for n in numbers if n.split(" ")[0] not in sources]
    assert not unsourced, f"numbers without a linked report or make target: {unsourced}"
    assert not unknown, f"numbers missing from the report their line links to: {unknown}"
