"""Keep imported model observations separate from executing/accepted evaluation runs."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0067_stored_model_comparisons"
down_revision = "0066_generative_pending_cancel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rag_comparison_reports",
        sa.Column("id", sa.Uuid(), nullable=False, primary_key=True),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("source_key", sa.String(160), nullable=False),
        sa.Column("source_result_sha256", sa.String(64), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("owner_id", "source_key", name="uq_rag_comparison_source"),
        sa.CheckConstraint("length(source_key) BETWEEN 1 AND 160", name="ck_rag_comparison_key"),
        sa.CheckConstraint(
            "source_result_sha256 ~ '^[0-9a-f]{64}$' AND content_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_rag_comparison_hashes",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object' AND octet_length(payload::text) <= 4194304",
            name="ck_rag_comparison_payload",
        ),
    )
    op.create_index(
        "ix_rag_comparison_owner_completed",
        "rag_comparison_reports",
        ["owner_id", "completed_at", "id"],
    )
    op.execute("""
    CREATE FUNCTION rag_comparison_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      RAISE EXCEPTION 'Imported comparison records are immutable';
    END $$;
    CREATE TRIGGER rag_comparison_immutable BEFORE UPDATE OR DELETE ON rag_comparison_reports
      FOR EACH ROW EXECUTE FUNCTION rag_comparison_immutable();
    """)


def downgrade() -> None:
    op.execute("""
    DO $$ BEGIN
      IF EXISTS(SELECT 1 FROM rag_comparison_reports) THEN
        RAISE EXCEPTION 'Cannot downgrade while comparison evidence exists';
      END IF;
    END $$;
    DROP TRIGGER rag_comparison_immutable ON rag_comparison_reports;
    DROP FUNCTION rag_comparison_immutable();
    """)
    op.drop_index("ix_rag_comparison_owner_completed", table_name="rag_comparison_reports")
    op.drop_table("rag_comparison_reports")
