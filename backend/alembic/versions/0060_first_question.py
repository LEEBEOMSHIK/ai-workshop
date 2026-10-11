"""Atomic first-question ledger, private attachment drafts and title provenance."""

from alembic import op

revision = "0060_first_question"
down_revision = "0059_generative_raw_proof"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE rag_conversations
      ADD COLUMN title_origin varchar(12) NOT NULL DEFAULT 'legacy',
      ADD COLUMN title_source_turn_id uuid REFERENCES rag_conversation_turns(id) ON DELETE RESTRICT,
      ADD COLUMN title_derivation varchar(12),
      ADD COLUMN title_policy_version varchar(64),
      ADD COLUMN title_error_code varchar(80),
      ADD COLUMN legacy_state varchar(24) NOT NULL DEFAULT 'active',
      ADD CONSTRAINT ck_rag_title_origin CHECK(title_origin IN ('auto','manual','legacy')),
      ADD CONSTRAINT ck_rag_title_derivation
        CHECK(title_derivation IN ('extracted','preserved','fallback')),
      ADD CONSTRAINT ck_rag_legacy_state CHECK(legacy_state IN ('active','draft_pending'));
    UPDATE rag_conversations c SET legacy_state='draft_pending'
      WHERE NOT EXISTS(SELECT 1 FROM rag_conversation_turns t WHERE t.conversation_id=c.id);
    CREATE TABLE rag_conversation_starts (
      owner_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
      domain_id uuid NOT NULL REFERENCES rag_domains(id) ON DELETE RESTRICT,
      request_id uuid NOT NULL,
      request_digest varchar(64) NOT NULL,
      conversation_id uuid NOT NULL UNIQUE REFERENCES rag_conversations(id) ON DELETE RESTRICT,
      first_turn_id uuid NOT NULL UNIQUE REFERENCES rag_conversation_turns(id) ON DELETE RESTRICT,
      created_at timestamptz NOT NULL,
      CONSTRAINT pk_rag_conversation_starts PRIMARY KEY(owner_id,domain_id,request_id)
    );
    CREATE TABLE rag_attachment_drafts (
      id uuid PRIMARY KEY,
      owner_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
      domain_id uuid NOT NULL REFERENCES rag_domains(id) ON DELETE RESTRICT,
      state varchar(12) NOT NULL,
      revision integer NOT NULL,
      create_request_id uuid NOT NULL,
      created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL,
      expires_at timestamptz NOT NULL,
      bound_conversation_id uuid UNIQUE REFERENCES rag_conversations(id) ON DELETE RESTRICT,
      legacy_conversation_id uuid REFERENCES rag_conversations(id) ON DELETE RESTRICT,
      start_request_id uuid, start_request_digest varchar(64),
      CONSTRAINT uq_rag_draft_create UNIQUE(owner_id,domain_id,create_request_id),
      CONSTRAINT uq_rag_draft_legacy UNIQUE(legacy_conversation_id),
      CONSTRAINT ck_rag_draft_state CHECK(state IN ('open','bound','abandoned','expired')),
      CONSTRAINT ck_rag_draft_revision CHECK(revision>=1),
      CONSTRAINT ck_rag_draft_bound CHECK((state='bound')=(bound_conversation_id IS NOT NULL))
    );
    CREATE INDEX ix_rag_draft_open_expiry ON rag_attachment_drafts(state,expires_at);
    ALTER TABLE rag_conversation_attachments
      ALTER COLUMN conversation_id DROP NOT NULL,
      ADD COLUMN draft_id uuid REFERENCES rag_attachment_drafts(id) ON DELETE RESTRICT,
      ADD COLUMN excluded_at timestamptz,
      ADD CONSTRAINT ck_rag_attachment_parent CHECK((conversation_id IS NULL)<>(draft_id IS NULL));
    CREATE INDEX ix_rag_attachment_draft ON rag_conversation_attachments(draft_id,owner_id);
    """)


def downgrade() -> None:
    # The complete safety fence is first, before any destructive DDL. A failed
    # downgrade must leave both originals and durable replay metadata untouched.
    op.execute("""
    DO $$ BEGIN
      IF EXISTS(SELECT 1 FROM rag_conversation_starts)
         OR EXISTS(SELECT 1 FROM rag_attachment_drafts)
         OR EXISTS(SELECT 1 FROM rag_conversation_attachments WHERE draft_id IS NOT NULL)
      THEN RAISE EXCEPTION 'first-question data exists; reviewed migration required'; END IF;
    END $$;
    """)
    op.execute("""
    DROP INDEX ix_rag_attachment_draft;
    ALTER TABLE rag_conversation_attachments DROP CONSTRAINT ck_rag_attachment_parent,
      DROP COLUMN excluded_at, DROP COLUMN draft_id, ALTER COLUMN conversation_id SET NOT NULL;
    DROP TABLE rag_attachment_drafts;
    DROP TABLE rag_conversation_starts;
    ALTER TABLE rag_conversations DROP CONSTRAINT ck_rag_title_origin,
      DROP CONSTRAINT ck_rag_title_derivation, DROP CONSTRAINT ck_rag_legacy_state,
      DROP COLUMN title_origin, DROP COLUMN title_source_turn_id, DROP COLUMN title_derivation,
      DROP COLUMN title_policy_version, DROP COLUMN title_error_code, DROP COLUMN legacy_state;
    """)
