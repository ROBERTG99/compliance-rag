"""Allow the `purge_expired` audit action (retention cron).

Revision ID: 0005_audit_purge
Revises: 0004_prewarm
"""

from alembic import op

revision = "0005_audit_purge"
down_revision = "0004_prewarm"
branch_labels = None
depends_on = None

OLD = "'ask','evidence_view','document_upload','version_activate','acl_change','feedback','feedback_triage'"


def upgrade() -> None:
    op.execute("ALTER TABLE audit DROP CONSTRAINT audit_action_check")
    op.execute(
        f"ALTER TABLE audit ADD CONSTRAINT audit_action_check CHECK (action IN ({OLD},'purge_expired'))"
    )


def downgrade() -> None:
    # audit rows are never deleted: existing purge rows stay, the narrower rule applies to new rows only
    op.execute("ALTER TABLE audit DROP CONSTRAINT audit_action_check")
    op.execute(f"ALTER TABLE audit ADD CONSTRAINT audit_action_check CHECK (action IN ({OLD})) NOT VALID")
