"""Reject TRUNCATE on the audit table (statement-level trigger), complementing the row trigger.

Revision ID: 0003_audit_truncate
Revises: 0002_ops
"""

from alembic import op

revision = "0003_audit_truncate"
down_revision = "0002_ops"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TRIGGER audit_no_truncate BEFORE TRUNCATE ON audit
          FOR EACH STATEMENT EXECUTE FUNCTION audit_append_only();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_no_truncate ON audit")
