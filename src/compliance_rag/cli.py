"""`crag` command-line interface."""

from __future__ import annotations

import asyncio

import psycopg
import typer

from compliance_rag.settings import get_settings

app = typer.Typer(help="compliance-rag operations CLI", no_args_is_help=True)
audit_app = typer.Typer(help="Audit log commands", no_args_is_help=True)
app.add_typer(audit_app, name="audit")


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


if __name__ == "__main__":  # pragma: no cover
    app()
