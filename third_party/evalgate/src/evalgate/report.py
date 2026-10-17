"""Markdown rendering of one or more ``evalgate.report.v1`` reports."""

from __future__ import annotations

from typing import Any


def _fmt(value: float | None, unit: str) -> str:
    if value is None:
        return "n/a"
    if unit == "ms":
        return f"{value:.0f} ms"
    if unit == "count":
        return f"{value:g}"
    return f"{value:.3f}"


def render_markdown(reports: list[dict[str, Any]], *, title: str, preface: str = "") -> str:
    lines = [f"# {title}", ""]
    if preface:
        lines += [preface.rstrip(), ""]
    for r in reports:
        status = "PASS" if r["passed"] else "FAIL"
        lines += [
            f"## Suite `{r['suite']}`: {status}",
            "",
            f"- Split: `{r['split']}` ({r['dataset']['n']} cases, dataset sha256 `{r['dataset']['sha256'][:12]}`)",
            f"- Generated: {r['generated_at']} in {r['duration_s']} s; errors: {r['errors']}",
        ]
        for key, value in sorted(r.get("target", {}).items()):
            lines.append(f"- {key}: {value}")
        lines += ["", "| Metric | Value | Threshold | Cases | Gate | Result |", "|---|---|---|---|---|---|"]
        for name, m in r["metrics"].items():
            gate = "hard" if m["hard"] else ("yes" if m["gate"] else "no")
            result = "pass" if m["passed"] else "**fail**"
            lines.append(
                f"| {name} | {_fmt(m['value'], m['unit'])} | {m['threshold_text'] or '—'} | {m['n']} | {gate} | {result} |"
            )
        lines.append("")
    return "\n".join(lines)
