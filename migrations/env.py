"""Alembic environment: raw-SQL migrations, URL from config or CRAG_DATABASE_URL."""

from alembic import context
from sqlalchemy import create_engine, pool

from compliance_rag.settings import Settings

config = context.config


def _url() -> str:
    url = config.get_main_option("sqlalchemy.url")
    if not url:
        url = Settings().sqlalchemy_url
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


def run_migrations_offline() -> None:
    context.configure(url=_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
