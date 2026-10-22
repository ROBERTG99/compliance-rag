"""The demo scenario end to end, in-process. ``make demo`` runs the same steps over HTTP."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest

from compliance_rag.ingest.pipeline import ingest_document
from scripts.demo import run_demo
from tests.fixtures_services import S3Config, make_api_env

pytestmark = pytest.mark.integration


async def test_demo_runs_the_user_journeys(
    pg_admin_url: str, redis_url: str, opensearch_url: str, s3_config: S3Config
) -> None:
    # its own environment (same seeded subset as api_env): the demo activates AML-0107 v4, which must not
    # leak into the shared session corpus
    async with make_api_env(pg_admin_url, redis_url, opensearch_url, s3_config) as env:

        @asynccontextmanager
        async def client_for(persona: str) -> AsyncIterator[httpx.AsyncClient]:
            async with await env.client(persona) as client:
                yield client

        async def process_job(job_id: str) -> None:  # the worker's job, done inline
            await ingest_document(env.app.state.crag.services.ingest_deps(), job_id)

        lines: list[str] = []
        steps = await run_demo(client_for, log=lines.append, process_job=process_job)
    names = [s.name.split()[0] for s in steps]
    assert names == ["1", "2", "3", "4", "5", "6", "7", "a", "b", "c"]
    assert any("KYC-0042 v3" in line for line in lines)
