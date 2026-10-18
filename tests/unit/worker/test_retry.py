"""The worker retries an ingest job only while the pipeline has not marked it failed."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from arq.worker import Retry

from compliance_rag.ingest import pipeline
from compliance_rag.worker import main as worker_main


def _ctx(job_try: int) -> dict[str, Any]:
    services = SimpleNamespace(embedder=SimpleNamespace(fitted=True), ingest_deps=lambda: None)
    return {"services": services, "job_try": job_try}


async def test_a_final_failure_is_not_retried_whatever_arq_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    async def final(_deps: Any, job_id: str) -> Any:
        # the job's attempts in Postgres reached the limit (for example after a re-upload) on Arq's first try
        raise pipeline.FinalIngestFailure(job_id) from RuntimeError("parse error")

    monkeypatch.setattr(pipeline, "ingest_document", final)
    with pytest.raises(pipeline.FinalIngestFailure):
        await worker_main.ingest_document(_ctx(job_try=1), "job-1")


async def test_a_non_final_failure_is_retried_with_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    async def transient(_deps: Any, job_id: str) -> Any:
        raise ConnectionError("opensearch")

    monkeypatch.setattr(pipeline, "ingest_document", transient)
    with pytest.raises(Retry):
        await worker_main.ingest_document(_ctx(job_try=1), "job-1")
