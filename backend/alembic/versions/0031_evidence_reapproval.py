"""Preserve legacy evidence approvals; introduce current state and immutable history.

Stop all approval/execution writers before applying and deploy v3 code together.
Legacy calls are revoked, never filled with a current approval generation.
"""

import sqlalchemy as sa

from alembic import op

revision = "0031_evidence_reapproval"
down_revision = "0030_technology_permissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "LOCK TABLE rag_codex_evidence_approvals, rag_codex_call_approvals IN ACCESS EXCLUSIVE MODE"
    )
    op.create_table(
        "rag_evidence_approval_states",
        sa.Column(
            "revision_id",
            sa.Uuid(),
            sa.ForeignKey("asset_versions.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("provider", sa.String(64), primary_key=True),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("classification", sa.String(32), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("generation > 0", name="ck_evidence_state_generation"),
        sa.CheckConstraint("status IN ('approved','revoked')", name="ck_evidence_state_status"),
        sa.CheckConstraint(
            "classification IN ('public','synthetic')", name="ck_evidence_state_class"
        ),
        sa.CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="ck_evidence_state_digest"),
    )
    op.create_table(
        "rag_evidence_approval_events",
        sa.Column(
            "revision_id",
            sa.Uuid(),
            sa.ForeignKey("asset_versions.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("provider", sa.String(64), primary_key=True),
        sa.Column("generation", sa.Integer(), primary_key=True),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("classification", sa.String(32), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("request_id", sa.Uuid()),
        sa.Column("request_digest", sa.String(64)),
        sa.UniqueConstraint("actor_id", "request_id", name="uq_evidence_event_request"),
        sa.CheckConstraint("generation > 0", name="ck_evidence_event_generation"),
        sa.CheckConstraint("action IN ('approve','revoke')", name="ck_evidence_event_action"),
        sa.CheckConstraint(
            "classification IN ('public','synthetic')", name="ck_evidence_event_class"
        ),
        sa.CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="ck_evidence_event_content"),
        sa.CheckConstraint(
            "request_digest IS NULL OR request_digest ~ '^[0-9a-f]{64}$'",
            name="ck_evidence_event_digest",
        ),
        sa.CheckConstraint(
            "(request_id IS NULL) = (request_digest IS NULL)", name="ck_evidence_event_receipt"
        ),
    )
    op.execute("""
        INSERT INTO rag_evidence_approval_states
          (revision_id, provider, generation, status, content_sha256, classification,
           approved_at, revoked_at)
        SELECT revision_id, 'development_codex_exec',
          CASE WHEN revoked_at IS NULL THEN 1 ELSE 2 END,
          CASE WHEN revoked_at IS NULL THEN 'approved' ELSE 'revoked' END,
          content_sha256, classification, approved_at, revoked_at
        FROM rag_codex_evidence_approvals
    """)
    op.execute("""
        INSERT INTO rag_evidence_approval_events
          (revision_id, provider, generation, action, actor_id, occurred_at,
           classification, content_sha256)
        SELECT revision_id, 'development_codex_exec', 1, 'approve', approved_by,
          approved_at, classification, content_sha256 FROM rag_codex_evidence_approvals
        UNION ALL
        SELECT revision_id, 'development_codex_exec', 2, 'revoke', NULL,
          revoked_at, classification, content_sha256 FROM rag_codex_evidence_approvals
        WHERE revoked_at IS NOT NULL
    """)
    op.execute("""
        CREATE FUNCTION rag_evidence_history_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'evidence_approval_history_immutable'; END $$
    """)
    op.execute(
        "CREATE TRIGGER rag_evidence_events_immutable BEFORE UPDATE OR DELETE "
        "ON rag_evidence_approval_events FOR EACH ROW "
        "EXECUTE FUNCTION rag_evidence_history_immutable()"
    )
    # Keep the original immutable trigger; freeze remaining legacy write capabilities.
    op.execute(
        "CREATE TRIGGER rag_evidence_legacy_frozen BEFORE INSERT OR UPDATE OR DELETE "
        "ON rag_codex_evidence_approvals FOR EACH ROW "
        "EXECUTE FUNCTION rag_evidence_history_immutable()"
    )
    op.execute(
        "UPDATE rag_codex_call_approvals SET revoked_at = CURRENT_TIMESTAMP "
        "WHERE revoked_at IS NULL AND binding->'version' IS DISTINCT FROM '3'::jsonb"
    )
    # NOT VALID preserves old body-free rows but rejects all new old-writer calls.
    op.execute(
        "ALTER TABLE rag_codex_call_approvals ADD CONSTRAINT ck_codex_call_v3 "
        "CHECK (binding->'version' IS NOT DISTINCT FROM '3'::jsonb) NOT VALID"
    )


def downgrade() -> None:
    op.execute(
        "LOCK TABLE rag_evidence_approval_states, rag_evidence_approval_events, "
        "rag_codex_call_approvals IN ACCESS EXCLUSIVE MODE"
    )
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM rag_evidence_approval_events) OR
               EXISTS (SELECT 1 FROM rag_evidence_approval_states) OR
               EXISTS (SELECT 1 FROM rag_codex_call_approvals) THEN
                RAISE EXCEPTION 'evidence_reapproval_downgrade_requires_empty_tables';
            END IF;
        END $$
    """)
    op.execute("ALTER TABLE rag_codex_call_approvals DROP CONSTRAINT ck_codex_call_v3")
    op.execute("DROP TRIGGER rag_evidence_legacy_frozen ON rag_codex_evidence_approvals")
    op.drop_table("rag_evidence_approval_events")
    op.drop_table("rag_evidence_approval_states")
    op.execute("DROP FUNCTION rag_evidence_history_immutable()")
