"""Vendored evalgate subset: thresholds, aggregation, runner, check and calibration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evalgate.calibrate import calibrate
from evalgate.check import check
from evalgate.runner import aggregate, run_suite
from evalgate.suite import MetricSpec, Suite, Threshold
from evalgate.testing import FakeJudge

ROOT = Path(__file__).resolve().parents[3]


def test_thresholds_inclusive_and_exclusive() -> None:
    assert Threshold(min=0.9).holds(0.9) and not Threshold(min=0.9).holds(0.89)
    assert Threshold(max=0.01, exclusive=True).holds(0.0099) and not Threshold(
        max=0.01, exclusive=True
    ).holds(0.01)
    assert Threshold(max=0).holds(0.0) and not Threshold(max=0).holds(0.001)
    assert Threshold(max=0).describe() == "= 0"


def test_aggregations_skip_not_applicable_cases() -> None:
    assert aggregate(MetricSpec(name="m", fn="x:y"), [1.0, None, 0.0]) == (0.5, 2)
    assert aggregate(MetricSpec(name="r", fn="x:y", aggregate="ratio"), [(1, 2), (2, 2), None]) == (0.75, 4)
    assert aggregate(
        MetricSpec(name="p", fn="x:y", aggregate="p95", unit="ms"), [float(i) for i in range(1, 101)]
    ) == (95.0, 100)
    assert aggregate(MetricSpec(name="x", fn="x:y", aggregate="max"), [0.0, 1.0]) == (1.0, 2)
    assert aggregate(MetricSpec(name="m", fn="x:y"), [None]) == (None, 0)


class EchoTarget:
    def __init__(self) -> None:
        self.closed = False

    async def setup(self) -> None: ...

    async def __call__(self, row: dict[str, Any]) -> dict[str, Any]:
        if row["id"] == "boom":
            raise RuntimeError("backend down")
        return {"answer": row["input"]["question"]}

    async def close(self) -> None:
        self.closed = True

    def describe(self) -> dict[str, Any]:
        return {"llm": "echo"}


def has_q(row: dict[str, Any], output: dict[str, Any]) -> float:
    return 1.0 if "q" in output["answer"] else 0.0


async def test_runner_scores_splits_and_fails_on_errors(tmp_path: Path) -> None:
    data = tmp_path / "d.jsonl"
    rows = [
        {"id": "a", "split": "test", "input": {"question": "q1"}},
        {"id": "b", "split": "dev", "input": {"question": "zz"}},
        {"id": "boom", "split": "test", "input": {"question": "q"}},
    ]
    data.write_text("\n".join(json.dumps(r) for r in rows))
    suite = Suite(
        name="s",
        dataset=str(data),
        target="unused:unused",
        metrics=[MetricSpec(name="has_q", fn=f"{__name__}:has_q", threshold=Threshold(min=1.0))],
    )
    target = EchoTarget()
    report = await run_suite(suite, "test", target=target)
    assert report["schema"] == "evalgate.report.v1" and report["dataset"]["n"] == 2
    assert report["metrics"]["has_q"]["value"] == 1.0 and report["errors"] == 1
    assert report["passed"] is False  # a case that raised is never silently skipped
    assert report["target"] == {"llm": "echo"}


def _report(value: float, *, hard: bool = False, higher: bool = True, unit: str = "rate") -> dict[str, Any]:
    threshold = {"min": 0.5} if higher else {"max": 0.5}
    return {
        "suite": "s",
        "errors": 0,
        "metrics": {
            "m": {
                "value": value,
                "unit": unit,
                "gate": True,
                "hard": hard,
                "higher_is_better": higher,
                "passed": (value >= 0.5) if higher else (value <= 0.5),
                "threshold_text": "",
                "threshold": threshold,
            }
        },
    }


def test_check_thresholds_and_regressions() -> None:
    assert check(_report(0.90), _report(0.905), 1.0) == []  # 0.5 pp drop is within 1 pp
    assert "regressed by 2.00 pp" in check(_report(0.88), _report(0.90), 1.0)[0]
    assert (
        check(_report(0.10, higher=False), _report(0.12, higher=False), 1.0) == []
    )  # lower is better: improved
    assert check(_report(0.90, hard=True), _report(0.901, hard=True), 1.0)  # hard gates allow no regression
    assert check(_report(0.40), None, 1.0)  # below the threshold
    # latency is gated by its threshold only (percentage points do not apply to milliseconds)
    assert not any(
        "regressed" in f
        for f in check(_report(0.3, unit="ms", higher=False), _report(0.1, unit="ms", higher=False), 1.0)
    )


def test_fake_judge_meets_the_calibration_bar_on_the_labelled_answers() -> None:
    result = calibrate(ROOT / "evals/datasets/judge_labels.v1.jsonl", FakeJudge())
    assert result["n"] == 80
    assert result["agreement"] >= 0.8, result["disagreements"][:5]


def test_fake_judge_ignores_citation_markers() -> None:
    judge = FakeJudge()
    ref = "Transaction records are retained for 7 years after the transaction."
    assert judge.grade(ref, "Under the current policy the answer is 7 years [1].").passed
    assert judge.grade(ref, "They are kept for 7 years [1][2].").passed
    assert not judge.grade(ref, "They are kept for 5 years [1].").passed
