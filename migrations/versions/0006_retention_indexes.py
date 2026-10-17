"""Indexes for the retention purge: answers by age, conversation and follow-up FK; feedback by age.

Revision ID: 0006_retention_indexes
Revises: 0005_audit_purge
"""

from alembic import op

revision = "0006_retention_indexes"
down_revision = "0005_audit_purge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS answers_created ON answers (created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS answers_conversation ON answers (conversation_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS answers_follow_up ON answers (follow_up_of) WHERE follow_up_of IS NOT NULL"
    )
    op.execute("CREATE INDEX IF NOT EXISTS feedback_created ON feedback (created_at)")


def downgrade() -> None:
    for name in ("feedback_created", "answers_follow_up", "answers_conversation", "answers_created"):
        op.execute(f"DROP INDEX IF EXISTS {name}")
