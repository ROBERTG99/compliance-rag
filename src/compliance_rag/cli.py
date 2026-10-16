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
    seed: int = typer.Option(2026, help="Generator seed"),
) -> None:
    """Write questions.v1.jsonl and judge_labels.v1.jsonl; refuses to change an existing file."""
    import json
    from pathlib import Path

    from data.generator.corpus import build_corpus
    from data.generator.questions import build_judge_labels, build_questions

    policies = build_corpus(seed)
    outputs = {
        "questions.v1.jsonl": build_questions(policies, seed),
        "judge_labels.v1.jsonl": build_judge_labels(policies, seed),
    }
    for name, rows in outputs.items():
        target = Path(to) / name
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
