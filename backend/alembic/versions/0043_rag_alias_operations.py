"""Durable shared alias request journal without source-row foreign keys."""

from alembic import op

revision = "0043_rag_alias_operations"
down_revision = "0042_rag_index_resources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE rag_alias_operations (
    id UUID PRIMARY KEY,
    store_id VARCHAR(80) NOT NULL,
    cluster_uuid VARCHAR(128) NOT NULL,
    alias VARCHAR(255) NOT NULL,
    indexing_profile_id UUID NOT NULL,
    document_processing_profile_id UUID NOT NULL,
    targets JSONB NOT NULL,
    state VARCHAR(16) NOT NULL,
    result_code VARCHAR(32),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at TIMESTAMPTZ,
    CONSTRAINT ck_rag_alias_store CHECK (store_id ~ '^[a-z][a-z0-9_]{0,79}$'),
    CONSTRAINT ck_rag_alias_cluster CHECK (cluster_uuid ~ '^[A-Za-z0-9_-]{1,128}$'),
    CONSTRAINT ck_rag_alias_name CHECK (alias ~ '^[a-z0-9][a-z0-9._-]{0,254}$'),
    CONSTRAINT ck_rag_alias_targets CHECK (jsonb_typeof(targets) = 'array'),
    CONSTRAINT ck_rag_alias_state CHECK (
        (state = 'open' AND closed_at IS NULL AND result_code IS NULL) OR
        (state = 'closed' AND closed_at IS NOT NULL AND result_code IS NOT NULL
         AND result_code = 'confirmed')
    )
);
CREATE UNIQUE INDEX uq_rag_alias_open ON rag_alias_operations(cluster_uuid, alias)
WHERE state = 'open';
CREATE FUNCTION guard_rag_alias_operation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.id, NEW.store_id, NEW.cluster_uuid, NEW.alias, NEW.indexing_profile_id,
        NEW.document_processing_profile_id, NEW.targets, NEW.created_at)
       IS DISTINCT FROM
       (OLD.id, OLD.store_id, OLD.cluster_uuid, OLD.alias, OLD.indexing_profile_id,
        OLD.document_processing_profile_id, OLD.targets, OLD.created_at)
       OR (OLD.state = 'closed' AND NEW IS DISTINCT FROM OLD) THEN
        RAISE EXCEPTION 'immutable alias operation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER guard_rag_alias_operation BEFORE UPDATE ON rag_alias_operations
FOR EACH ROW EXECUTE FUNCTION guard_rag_alias_operation();
""")


def downgrade() -> None:
    op.execute("""
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM rag_alias_operations) THEN
        RAISE EXCEPTION 'alias operations must be resolved before downgrade';
    END IF;
END $$;
DROP TABLE rag_alias_operations;
DROP FUNCTION guard_rag_alias_operation();
""")
