"""Add durable embedding artifacts and fenced index build activation."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008_rag_embedding_artifacts"
down_revision: str | Sequence[str] | None = "0007_rag_ingestion_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "rag_ingestion_jobs", sa.Column("embedding_object_key", sa.String(700), nullable=True)
    )
    op.add_column(
        "rag_ingestion_jobs", sa.Column("embedding_sha256", sa.String(64), nullable=True)
    )
    op.add_column(
        "rag_ingestion_jobs", sa.Column("index_build_id", sa.Uuid(), nullable=True)
    )

    op.add_column(
        "rag_index_builds", sa.Column("indexing_profile_id", sa.Uuid(), nullable=True)
    )
    op.add_column("rag_index_builds", sa.Column("index_name", sa.String(700), nullable=True))
    op.add_column(
        "rag_index_builds", sa.Column("expected_document_count", sa.Integer(), nullable=True)
    )
    op.add_column(
        "rag_index_builds", sa.Column("indexed_document_count", sa.Integer(), nullable=True)
    )
    op.add_column(
        "rag_index_builds", sa.Column("vector_dimension", sa.Integer(), nullable=True)
    )
    op.add_column(
        "rag_index_builds", sa.Column("status", sa.String(32), nullable=True)
    )
    op.add_column(
        "rag_index_builds",
        sa.Column("is_active", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.execute(
        """
        UPDATE rag_index_builds AS build
        SET indexing_profile_id = projection.indexing_profile_id,
            status = 'legacy'
        FROM rag_document_projections AS projection
        WHERE projection.id = build.projection_id
        """
    )
    op.execute(
        """
        WITH ranked_builds AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY projection_id
                       ORDER BY created_at ASC, id ASC
                   ) AS position
            FROM rag_index_builds
        )
        DELETE FROM rag_index_builds AS build
        USING ranked_builds AS ranked
        WHERE build.id = ranked.id
          AND ranked.position > 1
        """
    )
    op.execute(
        """
        UPDATE rag_ingestion_jobs AS ingestion
        SET index_build_id = build.id
        FROM rag_index_builds AS build
        WHERE build.projection_id = ingestion.projection_id
        """
    )
    op.alter_column("rag_index_builds", "indexing_profile_id", nullable=False)
    op.create_foreign_key(
        "fk_rag_index_builds_indexing_profile_id",
        "rag_index_builds",
        "rag_profiles",
        ["indexing_profile_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_rag_index_builds_projection_id", "rag_index_builds", ["projection_id"]
    )
    op.create_unique_constraint(
        "uq_rag_index_builds_index_name", "rag_index_builds", ["index_name"]
    )
    op.create_index(
        "uq_rag_index_builds_active_profile",
        "rag_index_builds",
        ["indexing_profile_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_foreign_key(
        "fk_rag_ingestion_jobs_index_build_id",
        "rag_ingestion_jobs",
        "rag_index_builds",
        ["index_build_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_rag_ingestion_jobs_index_build_id", "rag_ingestion_jobs", type_="foreignkey"
    )
    op.drop_index("uq_rag_index_builds_active_profile", table_name="rag_index_builds")
    op.drop_constraint(
        "uq_rag_index_builds_index_name", "rag_index_builds", type_="unique"
    )
    op.drop_constraint(
        "uq_rag_index_builds_projection_id", "rag_index_builds", type_="unique"
    )
    op.drop_constraint(
        "fk_rag_index_builds_indexing_profile_id", "rag_index_builds", type_="foreignkey"
    )
    for name in (
        "is_active",
        "status",
        "vector_dimension",
        "indexed_document_count",
        "expected_document_count",
        "index_name",
        "indexing_profile_id",
    ):
        op.drop_column("rag_index_builds", name)
    for name in ("index_build_id", "embedding_sha256", "embedding_object_key"):
        op.drop_column("rag_ingestion_jobs", name)
