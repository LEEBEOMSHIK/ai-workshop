"""Create common RAG document provenance and projections."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_rag_search_documents"
down_revision: str | Sequence[str] | None = "0005_rag_profiles"
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
        "rag_document_projections",
        sa.Column("asset_version_id", sa.Uuid(), nullable=False),
        sa.Column("indexing_profile_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(["asset_version_id"], ["asset_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["indexing_profile_id"], ["rag_profiles.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('pending', 'parsing', 'chunking', 'embedding', 'indexing', "
            "'ready', 'failed', 'partial_ready')",
            name="ck_rag_document_projections_status",
        ),
        sa.UniqueConstraint("asset_version_id", "indexing_profile_id"),
    )
    op.create_table(
        "rag_structural_elements",
        sa.Column("projection_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("section_path", sa.JSON(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("bbox", sa.JSON(), nullable=True),
        sa.Column("parser_name", sa.String(180), nullable=False),
        sa.Column("parser_version", sa.String(180), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(
            ["projection_id"], ["rag_document_projections.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("projection_id", "ordinal"),
        sa.UniqueConstraint("projection_id", "id"),
    )
    op.create_table(
        "rag_retrieval_chunks",
        sa.Column("projection_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("section_path", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(
            ["projection_id"], ["rag_document_projections.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("projection_id", "ordinal"),
        sa.UniqueConstraint("projection_id", "id"),
    )
    op.create_table(
        "rag_evidence_units",
        sa.Column("projection_id", sa.Uuid(), nullable=False),
        sa.Column("retrieval_chunk_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("element_id", sa.Uuid(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("bbox", sa.JSON(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(
            ["projection_id", "retrieval_chunk_id"],
            ["rag_retrieval_chunks.projection_id", "rag_retrieval_chunks.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["projection_id", "element_id"],
            ["rag_structural_elements.projection_id", "rag_structural_elements.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("retrieval_chunk_id", "ordinal"),
    )
    op.create_table(
        "rag_index_builds",
        sa.Column("projection_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(
            ["projection_id"], ["rag_document_projections.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("rag_index_builds")
    op.drop_table("rag_evidence_units")
    op.drop_table("rag_retrieval_chunks")
    op.drop_table("rag_structural_elements")
    op.drop_table("rag_document_projections")
