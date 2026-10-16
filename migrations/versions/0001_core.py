"""Core schema: documents, versions, ACL, chunks (pgvector HNSW), index metadata, ingestion jobs.

Revision ID: 0001_core
Revises:
"""

from alembic import op

revision = "0001_core"
down_revision = None
branch_labels = None
depends_on = None

UPGRADE = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE documents (
  document_id text PRIMARY KEY CHECK (document_id ~ '^[A-Z]{2,4}-[0-9]{4}$'),
  title text NOT NULL, domain text NOT NULL, owner text NOT NULL);
CREATE TABLE document_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id text NOT NULL REFERENCES documents ON DELETE RESTRICT,
  version int NOT NULL CHECK (version >= 1),
  content_sha256 char(64) NOT NULL,
  source_format text NOT NULL CHECK (source_format IN ('pdf','docx','html','md')),
  s3_key text NOT NULL,
  size_bytes int NOT NULL CHECK (size_bytes BETWEEN 1 AND 20971520),
  extracted_text text,
  valid_from date NOT NULL,
  valid_to date CHECK (valid_to IS NULL OR valid_to > valid_from),
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','indexing','active','failed')),
  uploaded_at timestamptz NOT NULL DEFAULT now(), activated_at timestamptz,
  UNIQUE (document_id, version), UNIQUE (document_id, content_sha256));
CREATE UNIQUE INDEX one_open_version ON document_versions (document_id)
  WHERE status = 'active' AND valid_to IS NULL;
CREATE TABLE document_acl (
  document_id text NOT NULL REFERENCES documents ON DELETE CASCADE,
  group_name text NOT NULL CHECK (group_name IN ('all','compliance','legal','support')),
  granted_by text NOT NULL,
  PRIMARY KEY (document_id, group_name));
CREATE TABLE chunks (
  chunk_id char(32) PRIMARY KEY,
  version_id uuid NOT NULL REFERENCES document_versions ON DELETE CASCADE,
  document_id text NOT NULL, ordinal int NOT NULL, section_path text NOT NULL,
  text text NOT NULL, char_start int NOT NULL, char_end int NOT NULL CHECK (char_end > char_start),
  token_count int NOT NULL CHECK (token_count BETWEEN 1 AND 800),
  injection_score real NOT NULL DEFAULT 0,
  acl_groups text[] NOT NULL, valid_from date NOT NULL, valid_to date,
  visible boolean NOT NULL DEFAULT false,
  embedding vector(384) NOT NULL,
  UNIQUE (version_id, ordinal));
CREATE INDEX chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);
CREATE INDEX chunks_acl_gin ON chunks USING gin (acl_groups);
CREATE INDEX chunks_validity ON chunks (valid_from, valid_to) WHERE visible;
CREATE TABLE index_meta (key text PRIMARY KEY, value jsonb NOT NULL);
CREATE TABLE ingestion_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  idempotency_key char(64) NOT NULL UNIQUE,
  kind text NOT NULL CHECK (kind IN ('ingest','acl_sync','reindex')),
  document_id text NOT NULL, version_id uuid REFERENCES document_versions,
  status text NOT NULL CHECK (status IN ('queued','parsing','embedding','indexing','activating','done','failed')),
  attempts int NOT NULL DEFAULT 0, error text, requested_by text NOT NULL,
  enqueued_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz, chunk_count int);
CREATE INDEX ingestion_jobs_status ON ingestion_jobs (status, enqueued_at);
"""

DOWNGRADE = """
DROP TABLE IF EXISTS ingestion_jobs;
DROP TABLE IF EXISTS index_meta;
DROP TABLE IF EXISTS chunks;
DROP TABLE IF EXISTS document_acl;
DROP TABLE IF EXISTS document_versions;
DROP TABLE IF EXISTS documents;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
