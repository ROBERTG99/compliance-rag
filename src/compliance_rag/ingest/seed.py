"""Bulk seed of the synthetic corpus (``crag seed``), idempotent by corpus fingerprint.

Same building blocks as the incremental pipeline (register_upload → parse_version → build_records →
write_indexes), but versions are written with their final validity windows and activated in one
Postgres transaction instead of one update-by-query per version. The incremental path is
covered by ``tests/integration/test_ingest_pipeline.py``.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import date
from typing import Any

from compliance_rag.db.audit import append_audit
from compliance_rag.embed.lsa import LocalLSAEmbedder
from compliance_rag.embed.registry import read_index_meta, save_embedder, write_index_meta
from compliance_rag.ingest.pipeline import (
    DocumentMeta,
    IngestDeps,
    ParsedVersion,
    build_records,
    parse_version,
    register_upload,
    write_indexes,
)
from compliance_rag.retrieval.types import ChunkRecord


@dataclass
class SeedReport:
    status: str
    documents: int
    versions: int
    chunks: int
    seconds: float
    fingerprint: str


async def seed_corpus(
    deps: IngestDeps,
    *,
    seed: int = 2026,
    force: bool = False,
    log: Any = print,
    exclude: set[tuple[str, int]] | None = None,
    only: set[str] | None = None,
) -> SeedReport:
    from data.generator.corpus import build_corpus, corpus_fingerprint
    from data.generator.render import render_version

    started = time.perf_counter()
    policies = build_corpus(seed)
    if only is not None:
        policies = [p for p in policies if p.document_id in only]
    fingerprint = corpus_fingerprint(policies)
    done = await read_index_meta(deps.pool, "seed")
    if done and done.get("fingerprint") == fingerprint and not force:
        return SeedReport(
            "already_seeded",
            int(done["documents"]),
            int(done["versions"]),
            int(done["chunks"]),
            0.0,
            fingerprint,
        )
    exclude = exclude or set()
    # a crash from here on must not leave a stale "seeded" marker behind
    async with deps.pool.connection() as conn:
        await conn.execute("DELETE FROM index_meta WHERE key = 'seed'")

    # 1. register every version (raw file to S3, pending version, queued job) — idempotent
    sem = asyncio.Semaphore(8)
    jobs: list[tuple[str, str, int]] = []  # (version_id, document_id, version)

    async def register(policy: Any, version: Any) -> None:
        meta = DocumentMeta(
            policy.document_id,
            version.version,
            policy.title,
            policy.domain,
            policy.owner,
            date.fromisoformat(version.valid_from),
            version.source_format,
            policy.acl_groups,
            date.fromisoformat(version.valid_to) if version.valid_to else None,
        )
        async with sem:
            job = await register_upload(deps, meta, render_version(policy, version), "seed@northwind.test")
        jobs.append((job.version_id, policy.document_id, version.version))

    await asyncio.gather(
        *(register(p, v) for p in policies for v in p.versions if (p.document_id, v.version) not in exclude)
    )
    log(f"registered {len(jobs)} versions")

    # 2. parse + chunk every version
    parsed: list[ParsedVersion] = []

    async def parse(version_id: str) -> None:
        async with sem:
            parsed.append(await parse_version(deps, version_id))

    await asyncio.gather(*(parse(vid) for vid, _, _ in jobs))
    parsed.sort(key=lambda p: (p.version["document_id"], p.version["version"]))
    n_chunks = sum(len(p.chunks) for p in parsed)
    log(f"parsed {len(parsed)} versions into {n_chunks} chunks")

    # 3. fit the offline embedder on the whole corpus unless one is already registered
    meta = await read_index_meta(deps.pool, "embedder")
    needs_fit = meta is None or force or not getattr(deps.embedder, "fitted", True)
    if needs_fit and isinstance(deps.embedder, LocalLSAEmbedder):
        texts = [f"{c.section_path}\n{c.text}" for p in parsed for c in p.chunks]
        await asyncio.to_thread(deps.embedder.fit, texts)
        await save_embedder(deps.pool, deps.objects, deps.embedder)
        log(f"fitted LSA embedder {deps.embedder.fingerprint()}")

    # 4. embed and index with the final validity window, visible
    batch: list[ChunkRecord] = []
    written = 0
    for p in parsed:
        records = await asyncio.to_thread(build_records, p, deps.embedder)
        batch += records  # invisible until the activation step below
        if len(batch) >= 2000:
            await write_indexes(deps, batch)
            written += len(batch)
            batch = []
    if batch:
        await write_indexes(deps, batch)
        written += len(batch)
    await deps.bm25.refresh()
    log(f"indexed {written} chunks")

    # 5. activate every version: Postgres in one transaction, then the search indexes
    version_ids = [vid for vid, _, _ in jobs]
    async with deps.pool.connection() as conn, conn.transaction():
        await conn.execute(
            "UPDATE document_versions SET status = 'active', activated_at = COALESCE(activated_at, now()) "
            "WHERE id = ANY(%s::uuid[])",
            (version_ids,),
        )
        await conn.execute(
            "UPDATE chunks SET visible = true WHERE version_id = ANY(%s::uuid[])", (version_ids,)
        )
        await conn.execute(
            """UPDATE ingestion_jobs j SET status = 'done', finished_at = now(), attempts = GREATEST(attempts, 1),
                      chunk_count = (SELECT count(*) FROM chunks c WHERE c.version_id = j.version_id)
               WHERE j.version_id = ANY(%s::uuid[]) AND j.status <> 'done'""",
            (version_ids,),
        )
        await append_audit(  # one row for the bulk activation (per-version rows come from the pipeline)
            conn,
            actor_sub="seed",
            actor_role="system",
            action="version_activate",
            target="seed",
            details={"versions": len(version_ids), "fingerprint": fingerprint},
        )
    await deps.bm25.set_visible_many(version_ids)
    await deps.bm25.expunge_deletes()  # re-seeding rewrites documents; keep BM25 statistics reproducible
    if deps.qdrant is not None:
        await deps.qdrant.set_visible_many(version_ids)
    report = SeedReport(
        "seeded", len(policies), len(jobs), written, time.perf_counter() - started, fingerprint
    )
    await write_index_meta(
        deps.pool,
        "seed",
        {
            "fingerprint": fingerprint,
            "documents": report.documents,
            "versions": report.versions,
            "chunks": report.chunks,
        },
    )
    return report
