"""Programmatic Alembic upgrade/downgrade (used by `crag migrate`, the migrate job and tests)."""

from __future__ import annotations

from alembic import command
from alembic.config import Config

from compliance_rag.settings import get_settings


def _config(url: str | None) -> Config:
    root = get_settings().root
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    if url:
        cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def upgrade(url: str | None = None, revision: str = "head") -> None:
    command.upgrade(_config(url), revision)


def downgrade(url: str | None = None, revision: str = "base") -> None:
    command.downgrade(_config(url), revision)
