"""Document review requests and immutable replay receipts (no execution grants)."""

import sqlalchemy as sa

from alembic import op

revision = "0032_evidence_approval_requests"
down_revision = "0031_evidence_reapproval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rag_evidence_approval_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "requester_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "revision_id",
            sa.Uuid(),
            sa.ForeignKey("asset_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("state_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("decision_request_id", sa.Uuid()),
        sa.Column("decision_digest", sa.String(64)),
        sa.UniqueConstraint("resolved_by", "decision_request_id"),
        sa.CheckConstraint(
            "provider = 'development_codex_exec'", name="ck_evidence_request_provider"
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND state_revision = 0 AND resolved_at IS NULL "
            "AND resolved_by IS NULL AND decision_request_id IS NULL AND decision_digest IS NULL) "
            "OR (status IN ('approved','rejected') AND state_revision = 1 "
            "AND resolved_at IS NOT NULL AND resolved_by IS NOT NULL "
            "AND decision_request_id IS NOT NULL AND decision_digest IS NOT NULL "
            "AND decision_digest ~ '^[0-9a-f]{64}$')",
            name="ck_evidence_request_resolution",
        ),
    )
    op.create_index(
        "uq_evidence_request_pending",
        "rag_evidence_approval_requests",
        ["requester_id", "revision_id", "provider"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_evidence_request_page", "rag_evidence_approval_requests", ["created_at", "id"]
    )
    op.create_table(
        "rag_evidence_approval_request_receipts",
        sa.Column(
            "actor_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True
        ),
        sa.Column("request_id", sa.Uuid(), primary_key=True),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column(
            "approval_request_id",
            sa.Uuid(),
            sa.ForeignKey("rag_evidence_approval_requests.id", ondelete="RESTRICT"),
            nullable=False,
        ),
    )
    op.execute("""
        CREATE FUNCTION guard_evidence_request() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE' OR OLD.status <> 'pending' OR
             ROW(NEW.id,NEW.requester_id,NEW.revision_id,NEW.provider,NEW.created_at)
             IS DISTINCT FROM ROW(OLD.id,OLD.requester_id,OLD.revision_id,
                                  OLD.provider,OLD.created_at)
             OR NEW.status NOT IN ('approved','rejected') THEN
            RAISE EXCEPTION 'evidence request history is immutable';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER evidence_request_guard BEFORE UPDATE OR DELETE
          ON rag_evidence_approval_requests FOR EACH ROW EXECUTE FUNCTION guard_evidence_request();
        CREATE FUNCTION guard_evidence_request_receipt() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'evidence request receipt is immutable'; END $$;
        CREATE TRIGGER evidence_request_receipt_guard BEFORE UPDATE OR DELETE
          ON rag_evidence_approval_request_receipts FOR EACH ROW
          EXECUTE FUNCTION guard_evidence_request_receipt();
    """)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM rag_evidence_approval_requests) THEN
            RAISE EXCEPTION 'Cannot discard document approval request history';
          END IF;
        END $$;
    """)
    op.drop_table("rag_evidence_approval_request_receipts")
    op.drop_table("rag_evidence_approval_requests")
    op.execute(
        "DROP FUNCTION guard_evidence_request_receipt(); DROP FUNCTION guard_evidence_request();"
    )
