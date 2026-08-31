"""Allow a RAG profile alias to expose every active document build."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011_active_rag_builds"
down_revision: str | Sequence[str] | None = "0010_rag_evaluation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("uq_rag_index_builds_active_profile", table_name="rag_index_builds")


def downgrade() -> None:
    op.execute(
        """
        WITH ranked_active_builds AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY indexing_profile_id
                       ORDER BY updated_at DESC, created_at DESC, id DESC
                   ) AS active_position
              FROM rag_index_builds
             WHERE is_active
        )
        UPDATE rag_index_builds AS build
           SET is_active = false
          FROM ranked_active_builds AS ranked
         WHERE build.id = ranked.id
           AND ranked.active_position > 1
        """
    )
    op.create_index(
        "uq_rag_index_builds_active_profile",
        "rag_index_builds",
        ["indexing_profile_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
