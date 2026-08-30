"""Create durable RAG ingestion command and artifact state."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007_rag_ingestion_jobs"
down_revision: str | Sequence[str] | None = "0006_rag_search_documents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "rag_ingestion_jobs",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("projection_id", sa.Uuid(), nullable=False),
        sa.Column("asset_version_id", sa.Uuid(), nullable=False),
        sa.Column("indexing_profile_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("parsed_object_key", sa.String(700), nullable=True),
        sa.Column("parsed_sha256", sa.String(64), nullable=True),
        sa.Column("chunk_object_key", sa.String(700), nullable=True),
        sa.Column("chunk_sha256", sa.String(64), nullable=True),
        sa.Column("parsed_element_count", sa.Integer(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=True),
        sa.Column("embedding_count", sa.Integer(), nullable=True),
        sa.Column("indexed_document_count", sa.Integer(), nullable=True),
        sa.Column(
            "index_alias_verified",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        *timestamps(),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["projection_id"], ["rag_document_projections.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["asset_version_id"], ["asset_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["indexing_profile_id"], ["rag_profiles.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("job_id"),
        sa.UniqueConstraint("asset_version_id", "indexing_profile_id"),
        sa.UniqueConstraint("projection_id"),
    )


def downgrade() -> None:
    op.drop_table("rag_ingestion_jobs")
