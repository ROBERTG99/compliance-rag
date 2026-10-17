"""Suite definition (YAML) and dotted-path loading."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


class Threshold(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min: float | None = None
    max: float | None = None
    exclusive: bool = False  # strict comparison: "< 0.01" rather than "<= 0.01"

    def holds(self, value: float) -> bool:
        if self.min is not None and (value <= self.min if self.exclusive else value < self.min):
            return False
        return not (self.max is not None and (value >= self.max if self.exclusive else value > self.max))

    def describe(self) -> str:
        parts = []
        if self.min is not None:
            parts.append(f"{'>' if self.exclusive else '≥'} {self.min:g}")
        if self.max is not None:
            parts.append(f"{'<' if self.exclusive else '≤'} {self.max:g}" if self.max else "= 0")
        return " and ".join(parts)


class MetricSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    fn: str  # "module:function"; (row, output) -> float | None, or (num, den) for aggregate "ratio"
    aggregate: Literal["mean", "ratio", "max", "p95"] = "mean"
    unit: Literal["rate", "ms", "count"] = "rate"
    threshold: Threshold | None = None
    gate: bool = True
    hard: bool = False  # a hard gate also fails on any regression from the baseline
    description: str = ""

    @property
    def higher_is_better(self) -> bool:
        return self.threshold is not None and self.threshold.min is not None


class Suite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str = ""
    dataset: str
    target: str  # "module:factory"; the factory returns a Target
    metrics: list[MetricSpec] = Field(min_length=1)
    concurrency: int = 4


def load_suite(path: str | Path) -> Suite:
    return Suite.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


def resolve(dotted: str) -> Any:
    module, _, attr = dotted.partition(":")
    if not attr:
        raise ValueError(f"expected 'module:attribute', got {dotted!r}")
    obj: Any = importlib.import_module(module)
    for part in attr.split("."):
        obj = getattr(obj, part)
    return obj
