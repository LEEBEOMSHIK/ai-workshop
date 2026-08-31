"""Terminalize inactive RAG dispatches and record exact handoff failures."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012_terminal_rag_handoffs"
down_revision: str | Sequence[str] | None = "0011_active_rag_builds"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "rag_ingestion_dispatches",
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.drop_constraint(
        "ck_rag_ing_dispatch_state",
        "rag_ingestion_dispatches",
        type_="check",
    )
    op.drop_constraint(
        "ck_rag_ing_dispatch_status",
        "rag_ingestion_dispatches",
        type_="check",
    )
    op.create_check_constraint(
        "ck_rag_ing_dispatch_status",
        "rag_ingestion_dispatches",
        "status IN ('pending', 'claimed', 'sent', 'cancelled')",
    )
    op.create_check_constraint(
        "ck_rag_ing_dispatch_state",
        "rag_ingestion_dispatches",
        "(status = 'pending' AND claim_token IS NULL AND claimed_at IS NULL "
        "AND sent_at IS NULL AND cancelled_at IS NULL) OR "
        "(status = 'claimed' AND claim_token IS NOT NULL "
        "AND claimed_at IS NOT NULL AND sent_at IS NULL AND cancelled_at IS NULL) OR "
        "(status = 'sent' AND claim_token IS NULL AND claimed_at IS NULL "
        "AND sent_at IS NOT NULL AND cancelled_at IS NULL) OR "
        "(status = 'cancelled' AND claim_token IS NULL AND claimed_at IS NULL "
        "AND sent_at IS NULL AND cancelled_at IS NOT NULL)",
    )
    op.create_table(
        "rag_asset_handoff_failures",
        sa.Column("asset_version_id", sa.Uuid(), nullable=False),
        sa.Column("indexing_profile_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_class", sa.String(length=32), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_message", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('retrying', 'resolved', 'quarantined', 'cancelled')",
            name="ck_rag_asset_handoff_status",
        ),
        sa.CheckConstraint(
            "error_class IS NULL OR error_class IN "
            "('transient', 'permanent', 'obsolete')",
            name="ck_rag_asset_handoff_error_class",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0", name="ck_rag_asset_handoff_attempt"
        ),
        sa.CheckConstraint(
            "(status = 'retrying' AND error_class = 'transient' "
            "AND error_code IS NOT NULL AND last_error_message IS NOT NULL "
            "AND next_retry_at IS NOT NULL AND terminal_at IS NULL) OR "
            "(status = 'quarantined' AND error_class IN ('transient', 'permanent') "
            "AND error_code IS NOT NULL AND last_error_message IS NOT NULL "
            "AND next_retry_at IS NULL AND terminal_at IS NOT NULL) OR "
            "(status = 'cancelled' AND error_class = 'obsolete' "
            "AND error_code IS NOT NULL AND last_error_message IS NOT NULL "
            "AND next_retry_at IS NULL AND terminal_at IS NOT NULL) OR "
            "(status = 'resolved' AND error_class IS NULL AND error_code IS NULL "
            "AND last_error_message IS NULL AND next_retry_at IS NULL "
            "AND terminal_at IS NOT NULL)",
            name="ck_rag_asset_handoff_state",
        ),
        sa.ForeignKeyConstraint(
            ["asset_version_id"], ["asset_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["indexing_profile_id"], ["rag_profiles.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("asset_version_id", "indexing_profile_id"),
    )
    op.create_index(
        "ix_rag_asset_handoff_retry",
        "rag_asset_handoff_failures",
        ["status", "next_retry_at"],
    )


def downgrade() -> None:
    # Cancelled rows are already paired with terminal failed Jobs. Removing the
    # terminal outbox row preserves non-delivery under the older three-state schema.
    op.drop_index(
        "ix_rag_asset_handoff_retry", table_name="rag_asset_handoff_failures"
    )
    op.drop_table("rag_asset_handoff_failures")
    op.execute("DELETE FROM rag_ingestion_dispatches WHERE status = 'cancelled'")
    op.drop_constraint(
        "ck_rag_ing_dispatch_state",
        "rag_ingestion_dispatches",
        type_="check",
    )
    op.drop_constraint(
        "ck_rag_ing_dispatch_status",
        "rag_ingestion_dispatches",
        type_="check",
    )
    op.create_check_constraint(
        "ck_rag_ing_dispatch_status",
        "rag_ingestion_dispatches",
        "status IN ('pending', 'claimed', 'sent')",
    )
    op.create_check_constraint(
        "ck_rag_ing_dispatch_state",
        "rag_ingestion_dispatches",
        "(status = 'pending' AND claim_token IS NULL AND claimed_at IS NULL "
        "AND sent_at IS NULL) OR "
        "(status = 'claimed' AND claim_token IS NOT NULL "
        "AND claimed_at IS NOT NULL AND sent_at IS NULL) OR "
        "(status = 'sent' AND claim_token IS NULL AND claimed_at IS NULL "
        "AND sent_at IS NOT NULL)",
    )
    op.drop_column("rag_ingestion_dispatches", "cancelled_at")
