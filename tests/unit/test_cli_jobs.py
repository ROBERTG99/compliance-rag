"""`crag jobs replay-failed` prints what it re-queued, also when the queue fails part-way."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from typer.testing import CliRunner

from compliance_rag import cli


class _Closable:
    async def close(self) -> None:
        pass

    async def aclose(self) -> None:
        pass

    async def enqueue_job(self, *_args: Any, **_kwargs: Any) -> None:
        pass


def _patch(monkeypatch: pytest.MonkeyPatch, replay: Callable[..., Awaitable[list[str]]]) -> None:
    import arq

    from compliance_rag.db import pool
    from compliance_rag.ingest import pipeline

    async def create(*_args: Any, **_kwargs: Any) -> _Closable:
        return _Closable()

    monkeypatch.setattr(pool, "create_pool", create)
    monkeypatch.setattr(arq, "create_pool", create)
    monkeypatch.setattr(pipeline, "replay_failed_jobs", replay)


def test_replay_reports_the_jobs_it_requeued(monkeypatch: pytest.MonkeyPatch) -> None:
    async def replay(_pool: Any, enqueue: Callable[[str], Awaitable[None]]) -> list[str]:
        await enqueue("job-1")
        return ["job-1"]

    _patch(monkeypatch, replay)
    result = CliRunner().invoke(cli.app, ["jobs", "replay-failed"])
    assert result.exit_code == 0
    assert "re-queued job-1" in result.output and "1 failed job(s) re-queued" in result.output


def test_a_queue_failure_part_way_lists_what_was_requeued_and_exits_1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def replay(_pool: Any, enqueue: Callable[[str], Awaitable[None]]) -> list[str]:
        await enqueue("job-1")
        raise ConnectionError("redis down")

    _patch(monkeypatch, replay)
    result = CliRunner().invoke(cli.app, ["jobs", "replay-failed"])
    assert result.exit_code == 1
    assert "re-queued job-1" in result.output
    assert "ConnectionError" in result.output and "run it again" in result.output
