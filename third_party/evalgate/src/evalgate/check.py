"""Gate a report: thresholds, and no regression beyond ``max_regression_pp`` against a baseline."""

from __future__ import annotations

from typing import Any


def check(report: dict[str, Any], baseline: dict[str, Any] | None, max_regression_pp: float) -> list[str]:
    """Return the failures (empty when the report passes)."""
    failures: list[str] = []
    if report.get("errors"):
        failures.append(f"{report['errors']} case(s) raised errors")
    for name, m in report["metrics"].items():
        if not m["gate"]:
            continue
        if m["value"] is None:
            failures.append(f"{name}: no applicable cases")
            continue
        if not m["passed"]:
            failures.append(f"{name} = {m['value']:.4f} violates {m['threshold_text']}")
        base = (baseline or {}).get("metrics", {}).get(name)
        if not base or base.get("value") is None or m["unit"] != "rate":
            continue
        delta_pp = (m["value"] - base["value"]) * 100
        worse = -delta_pp if m["higher_is_better"] else delta_pp
        limit = 0.0 if m["hard"] else max_regression_pp
        if worse > limit + 1e-9:
            failures.append(
                f"{name} regressed by {worse:.2f} pp (baseline {base['value']:.4f}, now {m['value']:.4f})"
            )
    return failures
