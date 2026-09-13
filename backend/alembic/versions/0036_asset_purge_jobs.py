"""Persist asset purge jobs and their dispatch outbox."""

import sqlalchemy as sa

from ai_workshop.platform.assets.trash_migration_preflight import (
    assert_trash_migration_ready,
)
from alembic import op

revision = "0036_asset_purge_jobs"
down_revision = "0035_asset_trash_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        "LOCK TABLE folders, documents IN SHARE ROW EXCLUSIVE MODE"
    )
    assert_trash_migration_ready(connection)

    op.create_table(
        "asset_purge_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("trash_batch_id", sa.Uuid(), nullable=False),
        sa.Column("request_key", sa.String(255), nullable=False),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="purge_pending",
        ),
        sa.Column(
            "attempt_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_asset_purge_jobs"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_asset_purge_jobs_workspace",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "trash_batch_id"],
            ["asset_trash_batches.workspace_id", "asset_trash_batches.id"],
            name="fk_asset_purge_jobs_trash_batch",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "request_key",
            name="uq_asset_purge_jobs_workspace_request_key",
        ),
        sa.UniqueConstraint(
            "trash_batch_id",
            name="uq_asset_purge_jobs_trash_batch_id",
        ),
        sa.CheckConstraint(
            "status IN ('purge_pending','purging','retry_wait','blocked','purged')",
            name="ck_asset_purge_jobs_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_asset_purge_jobs_attempt_count",
        ),
        sa.CheckConstraint(
            "(status = 'purged' AND finished_at IS NOT NULL) OR "
            "(status <> 'purged' AND finished_at IS NULL)",
            name="ck_asset_purge_jobs_finished_state",
        ),
    )
    op.create_table(
        "asset_purge_dispatches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column(
            "attempt_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claim_token", sa.Uuid(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_asset_purge_dispatches"),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["asset_purge_jobs.id"],
            name="fk_asset_purge_dispatches_job",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "job_id",
            name="uq_asset_purge_dispatches_job_id",
        ),
        sa.CheckConstraint(
            "status IN ('pending','claimed','sent')",
            name="ck_asset_purge_dispatches_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_asset_purge_dispatches_attempt_count",
        ),
        sa.CheckConstraint(
            "(status='pending' AND claim_token IS NULL AND claimed_at IS NULL "
            "AND sent_at IS NULL) OR "
            "(status='claimed' AND claim_token IS NOT NULL AND claimed_at IS NOT NULL "
            "AND sent_at IS NULL) OR "
            "(status='sent' AND claim_token IS NULL AND claimed_at IS NULL "
            "AND sent_at IS NOT NULL)",
            name="ck_asset_purge_dispatches_claim_state",
        ),
    )
    op.create_index(
        "ix_asset_purge_dispatches_status_available_at",
        "asset_purge_dispatches",
        ["status", "available_at"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        "LOCK TABLE folders, documents, asset_retention_policies, asset_trash_batches, "
        "asset_purge_jobs, asset_purge_dispatches IN SHARE ROW EXCLUSIVE MODE"
    )
    unsafe = connection.exec_driver_sql("""
        SELECT
          EXISTS (SELECT 1 FROM asset_retention_policies)
          OR EXISTS (SELECT 1 FROM asset_trash_batches)
          OR EXISTS (SELECT 1 FROM asset_purge_jobs)
          OR EXISTS (SELECT 1 FROM asset_purge_dispatches)
          OR EXISTS (
            SELECT 1 FROM folders
            WHERE lifecycle <> 'active' OR lifecycle_generation <> 1
               OR trash_batch_id IS NOT NULL OR trashed_at IS NOT NULL OR purge_after IS NOT NULL
          )
          OR EXISTS (
            SELECT 1 FROM documents
            WHERE lifecycle <> 'active' OR lifecycle_generation <> 1
               OR trash_batch_id IS NOT NULL OR trashed_at IS NOT NULL OR purge_after IS NOT NULL
          )
    """).scalar_one()
    if unsafe:
        raise RuntimeError("asset_purge_downgrade_unsafe")

    op.drop_index(
        "ix_asset_purge_dispatches_status_available_at",
        table_name="asset_purge_dispatches",
    )
    op.drop_table("asset_purge_dispatches")
    op.drop_table("asset_purge_jobs")
