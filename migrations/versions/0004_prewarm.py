"""pg_prewarm, used by the API start-up warm-up to load the chunk heap and HNSW index into shared buffers.

Revision ID: 0004_prewarm
Revises: 0003_audit_truncate
"""

from alembic import op

revision = "0004_prewarm"
down_revision = "0003_audit_truncate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_prewarm")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS pg_prewarm")
