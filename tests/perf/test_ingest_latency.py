"""NFR-3: one offline document is ingested in under 60 s."""

from __future__ import annotations

import time
from datetime import date

import pytest

from compliance_rag.ingest.pipeline import DocumentMeta, IngestDeps, ingest_document, register_upload
from data.generator.corpus import SEED, build_corpus
from data.generator.render import render_version

pytestmark = [pytest.mark.integration, pytest.mark.perf]


@pytest.mark.parametrize("fmt", ["md", "pdf", "docx", "html"])
async def test_one_document_under_60s(ingest_deps: IngestDeps, fmt: str) -> None:
    policy = max((p for p in build_corpus(SEED) if p.product), key=lambda p: len(p.current.articles))
    v = policy.current
    meta = DocumentMeta(
        policy.document_id,
        v.version,
        policy.title,
        policy.domain,
        policy.owner,
        date.fromisoformat(v.valid_from),
        fmt,
        policy.acl_groups,
    )
    started = time.perf_counter()
    job = await register_upload(ingest_deps, meta, render_version(policy, v, fmt), "admin")
    result = await ingest_document(ingest_deps, job.job_id)
    elapsed = time.perf_counter() - started
    assert result.status == "done" and result.chunk_count >= len(v.articles)
    assert elapsed < 60, f"{fmt}: {elapsed:.1f}s"
