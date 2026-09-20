"""Retain tracked Jobs source identity and atomically revision metadata; legacy stays untracked."""

import sqlalchemy as sa

from alembic import op

revision = "0048_job_metadata_ownership"
down_revision = "0047_http_upload_intake"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("revision", sa.BigInteger(), nullable=True))
    op.create_check_constraint("ck_jobs_revision", "jobs", "revision IS NULL OR revision >= 1")
    op.create_table(
        "job_source_ownership",
        sa.Column("job_id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("asset_version_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id", "workspace_id", "asset_version_id"],
            ["jobs.id", "jobs.workspace_id", "jobs.asset_version_id"],
            name="fk_job_source_job",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "document_id"],
            ["documents.workspace_id", "documents.id"],
            name="fk_job_source_document",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "asset_version_id"],
            ["asset_versions.document_id", "asset_versions.id"],
            name="fk_job_source_version",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_job_source_document", "job_source_ownership", ["workspace_id", "document_id"]
    )


def downgrade() -> None:
    op.drop_table("job_source_ownership")
    op.drop_constraint("ck_jobs_revision", "jobs", type_="check")
    op.drop_column("jobs", "revision")
