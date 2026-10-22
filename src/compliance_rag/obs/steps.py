"""Step records — the evalgate StepRecord contract."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, TypedDict

StepKind = Literal["node", "llm", "retrieval"]
StepStatus = Literal["ok", "skipped", "error"]


class StepRecord(TypedDict):
    run_id: str
    task_id: str
    step: int
    node: str
    kind: StepKind
    model: str | None
    prompt_version: str | None
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float
    status: StepStatus
    error: str | None
    started_at: str


def make_step(
    run_id: str,
    node: str,
    *,
    kind: StepKind = "node",
    latency_ms: float = 0.0,
    status: StepStatus = "ok",
    model: str | None = None,
    prompt_version: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: float = 0.0,
    error: str | None = None,
    started_at: datetime | None = None,
    task_id: str | None = None,
) -> StepRecord:
    return StepRecord(
        run_id=run_id,
        task_id=task_id or run_id,
        step=0,
        node=node,
        kind=kind,
        model=model,
        prompt_version=prompt_version,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=round(cost_usd, 6),
        latency_ms=round(latency_ms, 3),
        status=status,
        error=error,
        started_at=(started_at or datetime.now(UTC)).isoformat(timespec="milliseconds"),
    )


def number_steps(steps: list[StepRecord]) -> list[StepRecord]:
    return [StepRecord(**{**s, "step": i}) for i, s in enumerate(steps)]
