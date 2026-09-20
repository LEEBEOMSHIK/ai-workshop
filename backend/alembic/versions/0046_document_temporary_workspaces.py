"""Reserve document temporary workspaces and retain source/job pins."""

import sqlalchemy as sa

from alembic import op

revision = "0046_document_temporary"
down_revision = "0045_original_upload_ownership"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_temporary_workspaces",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("asset_version_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("binding_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("store_id", sa.String(80), nullable=False),
        sa.Column("coverage", sa.String(32), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("error_code", sa.String(32), nullable=True),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "document_id"],
            ["documents.workspace_id", "documents.id"],
            name="fk_temporary_document",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "asset_version_id"],
            ["asset_versions.document_id", "asset_versions.id"],
            name="fk_temporary_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name="fk_temporary_job", ondelete="RESTRICT"
        ),
        sa.CheckConstraint("purpose IN ('parsing','pdf_preview')", name="ck_temporary_purpose"),
        sa.CheckConstraint(
            "coverage IN ('bounded','runtime_unverified')", name="ck_temporary_coverage"
        ),
        sa.CheckConstraint("generation >= 1", name="ck_temporary_generation"),
        sa.CheckConstraint("store_id ~ '^[a-z][a-z0-9_]{0,79}$'", name="ck_temporary_store"),
        sa.CheckConstraint(
            "(state = 'open' AND revision = 1) OR "
            "(state = 'closed' AND revision = 2) OR (state = 'cleaning' AND revision = 3) OR "
            "(state = 'cleaned' AND revision = 4)",
            name="ck_temporary_state_revision",
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code IN "
            "('writer_unconfirmed','cleanup_unconfirmed','ownership_failed')",
            name="ck_temporary_error_code",
        ),
    )
    op.create_index(
        "ix_temporary_document", "document_temporary_workspaces", ["workspace_id", "document_id"]
    )
    op.create_index("ix_temporary_job", "document_temporary_workspaces", ["job_id"])


def downgrade() -> None:
    op.drop_table("document_temporary_workspaces")
