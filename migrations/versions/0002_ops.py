"""Operational tables: answers, feedback and the append-only hash-chained audit log.

Revision ID: 0002_ops
Revises: 0001_core
"""

from alembic import op

revision = "0002_ops"
down_revision = "0001_core"
branch_labels = None
depends_on = None

UPGRADE = """
CREATE TABLE answers (
  run_id uuid PRIMARY KEY, conversation_id uuid NOT NULL,
  follow_up_of uuid REFERENCES answers, user_sub text NOT NULL, groups text[] NOT NULL,
  question text NOT NULL CHECK (char_length(question) <= 2000), as_of date NOT NULL,
  response jsonb NOT NULL, abstained boolean NOT NULL, abstain_reason text,
  steps jsonb NOT NULL, cost_usd numeric(10,6) NOT NULL, latency_ms int NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX answers_user ON answers (user_sub, created_at DESC);
CREATE TABLE feedback (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL REFERENCES answers ON DELETE CASCADE, user_sub text NOT NULL,
  rating text NOT NULL CHECK (rating IN ('up','down')),
  reason text NOT NULL CHECK (reason IN ('correct','wrong_fact','wrong_citation','outdated','missing_info','should_abstain','other')),
  comment text CHECK (char_length(comment) <= 1000),
  status text NOT NULL DEFAULT 'new' CHECK (status IN ('new','triaged','added_to_dev_set')),
  created_at timestamptz NOT NULL DEFAULT now(), UNIQUE (run_id, user_sub));
CREATE TABLE audit (
  seq bigserial PRIMARY KEY, ts timestamptz NOT NULL DEFAULT now(),
  actor_sub text NOT NULL, actor_role text NOT NULL,
  action text NOT NULL CHECK (action IN ('ask','evidence_view','document_upload','version_activate','acl_change','feedback','feedback_triage')),
  target text NOT NULL, details jsonb NOT NULL,
  prev_hash char(64) NOT NULL, hash char(64) NOT NULL);
CREATE FUNCTION audit_append_only() RETURNS trigger LANGUAGE plpgsql AS
  $$ BEGIN RAISE EXCEPTION 'audit is append-only'; END $$;
CREATE TRIGGER audit_no_mutation BEFORE UPDATE OR DELETE ON audit
  FOR EACH ROW EXECUTE FUNCTION audit_append_only();
"""

DOWNGRADE = """
DROP TABLE IF EXISTS audit;
DROP FUNCTION IF EXISTS audit_append_only();
DROP TABLE IF EXISTS feedback;
DROP TABLE IF EXISTS answers;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
