"""`crag` command-line interface."""

from __future__ import annotations

import asyncio

import psycopg
import typer

from compliance_rag.settings import get_settings

app = typer.Typer(help="compliance-rag operations CLI", no_args_is_help=True, pretty_exceptions_enable=False)
audit_app = typer.Typer(help="Audit log commands", no_args_is_help=True)
app.add_typer(audit_app, name="audit")
search_app = typer.Typer(help="OpenSearch index commands", no_args_is_help=True)
app.add_typer(search_app, name="search")
corpus_app = typer.Typer(help="Synthetic corpus commands", no_args_is_help=True)
app.add_typer(corpus_app, name="corpus")
jobs_app = typer.Typer(help="Ingestion job commands", no_args_is_help=True)
app.add_typer(jobs_app, name="jobs")


@app.command()
def migrate(database_url: str = typer.Option(None, help="Override CRAG_DATABASE_URL")) -> None:
    """Run Alembic upgrade head."""
    from compliance_rag.db.migrate import upgrade

    upgrade(database_url or get_settings().psycopg_url)
    typer.echo("migrations at head")


@audit_app.command("verify")
def audit_verify(database_url: str = typer.Option(None, help="Override CRAG_DATABASE_URL")) -> None:
    """Recompute the audit hash chain; exit 1 on the first mismatch."""
    from compliance_rag.db.audit import verify_chain

    async def _run() -> None:
        url = database_url or get_settings().psycopg_url
        async with await psycopg.AsyncConnection.connect(url) as conn:
            result = await verify_chain(conn)
        if result.ok:
            typer.echo(f"audit chain ok ({result.rows} rows)")
        else:
            typer.echo(f"audit chain BROKEN at seq {result.first_bad_seq}", err=True)
            raise typer.Exit(1)

    asyncio.run(_run())


@app.command()
def seed(
    force: bool = typer.Option(False, help="Re-seed even if the corpus fingerprint is already loaded"),
    qdrant: bool = typer.Option(False, help="Also index into Qdrant (profile qdrant)"),
    migrate_first: bool = typer.Option(True, "--migrate/--no-migrate", help="Run migrations first"),
) -> None:
    """Load the synthetic corpus (seed 2026): S3 raw files, Postgres, OpenSearch (and Qdrant)."""
    from compliance_rag.db.migrate import upgrade
    from compliance_rag.ingest.seed import seed_corpus
    from compliance_rag.runtime import build_services

    settings = get_settings()
    if migrate_first:
        upgrade(settings.psycopg_url)

    async def _run() -> None:
        services = await build_services(settings, with_qdrant=qdrant or settings.vector_store == "qdrant")
        try:
            await services.objects.ensure_bucket()
            # a freshly restarted OpenSearch can pass its healthcheck before the REST port accepts connections
            for _ in range(60):
                if await services.bm25.ping():
                    break
                await asyncio.sleep(1)
            await services.bm25.init()
            if services.qdrant is not None:
                await services.qdrant.ensure_collection()
            report = await seed_corpus(services.ingest_deps(), force=force, log=typer.echo)
            typer.echo(
                f"seed {report.status}: {report.documents} documents, {report.versions} versions, "
                f"{report.chunks} chunks in {report.seconds:.1f}s (fingerprint {report.fingerprint[:12]})"
            )
        finally:
            await services.close()

    asyncio.run(_run())


@app.command()
def reindex(
    reembed: bool = typer.Option(False, help="Recompute embeddings first (refits the LSA embedder)"),
    bm25: bool = typer.Option(True, "--bm25/--no-bm25", help="Rewrite the OpenSearch index"),
    qdrant: bool | None = typer.Option(
        None, "--qdrant/--no-qdrant", help="Rewrite Qdrant (default: when configured or reachable)"
    ),
    recreate: bool = typer.Option(False, help="Drop and recreate the indexes first (removes orphans)"),
) -> None:
    """Rebuild the search indexes (and optionally the embeddings) from Postgres."""
    import httpx

    from compliance_rag.ingest.reindex import reindex as do_reindex
    from compliance_rag.runtime import build_services

    settings = get_settings()
    use_qdrant = qdrant
    if use_qdrant is None:
        try:
            reachable = httpx.get(f"{settings.qdrant_url}/readyz", timeout=2).status_code == 200
        except httpx.HTTPError:
            reachable = False
        use_qdrant = settings.vector_store == "qdrant" or reachable

    async def _run() -> None:
        services = await build_services(settings, with_qdrant=use_qdrant)
        try:
            if bm25:
                await services.bm25.init()
            if services.qdrant is not None:
                await services.qdrant.ensure_collection()
            report = await do_reindex(
                services.ingest_deps(),
                bm25=bm25,
                qdrant=use_qdrant,
                reembed=reembed,
                recreate=recreate,
                log=typer.echo,
            )
            typer.echo(f"reindexed {report.chunks} chunks in {report.seconds:.1f}s")
        finally:
            await services.close()

    asyncio.run(_run())


@jobs_app.command("replay-failed")
def jobs_replay_failed() -> None:
    """Re-queue every failed ingestion job (attempts reset; the pipeline steps are idempotent)."""
    from arq import create_pool as arq_pool
    from arq.connections import RedisSettings

    from compliance_rag.db.pool import create_pool
    from compliance_rag.ingest.pipeline import replay_failed_jobs

    settings = get_settings()

    async def _run() -> list[str]:
        redis = await arq_pool(RedisSettings.from_dsn(settings.redis_url))
        pool = await create_pool(settings.psycopg_url, max_size=2)
        try:

            async def enqueue(job_id: str) -> None:
                # a fresh Arq job id: the failed run's result is still kept under the original one
                await redis.enqueue_job("ingest_document", job_id)

            return await replay_failed_jobs(pool, enqueue)
        finally:
            await pool.close()
            await redis.aclose()

    replayed = asyncio.run(_run())
    for job_id in replayed:
        typer.echo(f"re-queued {job_id}")
    typer.echo(f"{len(replayed)} failed job(s) re-queued")


@search_app.command("init")
def search_init(opensearch_url: str = typer.Option(None, help="Override CRAG_OPENSEARCH_URL")) -> None:
    """Create the BM25 index and alias if missing (idempotent)."""
    from compliance_rag.retrieval.bm25 import BM25Index

    settings = get_settings()

    async def _run() -> bool:
        idx = BM25Index(
            opensearch_url or settings.opensearch_url, settings.opensearch_index, settings.opensearch_alias
        )
        try:
            return await idx.init()
        finally:
            await idx.close()

    created = asyncio.run(_run())
    typer.echo(f"index {settings.opensearch_index} ({'created' if created else 'already present'})")


@corpus_app.command("generate")
def corpus_generate(
    out: str = typer.Option("data/generated/corpus.v1", help="Output directory"),
    seed: int = typer.Option(2026, help="Generator seed"),
    render: bool = typer.Option(True, help="Render source files (md/html/docx/pdf)"),
) -> None:
    """Generate the seeded corpus, rendered sources and manifest."""
    from pathlib import Path

    from data.generator.build import write_corpus

    manifest = write_corpus(Path(out), seed=seed, render=render)
    typer.echo(
        f"{manifest['n_policies']} policies, {manifest['n_versions']} versions, "
        f"manifest {manifest['manifest_sha256'][:16]}"
    )


@corpus_app.command("export-datasets")
def corpus_export_datasets(
    to: str = typer.Option("evals/datasets", help="Dataset directory"),
    redteam_to: str = typer.Option("evals/redteam", help="Red-team case directory"),
    seed: int = typer.Option(2026, help="Generator seed"),
) -> None:
    """Write questions.v1.jsonl, judge_labels.v1.jsonl and the red-team cases; never changes an existing file."""
    import json
    from pathlib import Path

    from data.generator.corpus import build_corpus
    from data.generator.questions import build_judge_labels, build_questions
    from data.generator.redteam import build_redteam_cases, dump_cases

    policies = build_corpus(seed)
    outputs = {
        Path(to) / "questions.v1.jsonl": build_questions(policies, seed),
        Path(to) / "judge_labels.v1.jsonl": build_judge_labels(policies, seed),
        Path(redteam_to) / "cases.v1.yaml": build_redteam_cases(policies),
    }
    for target, rows in outputs.items():
        if target.suffix == ".yaml":
            text = dump_cases(rows)
        else:
            text = "".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in rows)
        if target.exists():
            if target.read_text() != text:
                typer.echo(
                    f"{target} exists and differs; datasets are append-only, add a new version", err=True
                )
                raise typer.Exit(1)
            typer.echo(f"{target} unchanged ({len(rows)} rows)")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        typer.echo(f"wrote {target} ({len(rows)} rows)")


if __name__ == "__main__":  # pragma: no cover
    app()
