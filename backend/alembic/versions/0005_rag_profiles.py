"""Create immutable RAG model and profile registry."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_rag_profiles"
down_revision: str | Sequence[str] | None = "0004_jobs"
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
        "rag_model_definitions",
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kind", "name", "version"),
    )
    op.create_table(
        "rag_profiles",
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("evaluation_state", sa.String(32), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kind", "name", "version"),
    )
    op.create_index(
        "uq_rag_profiles_default_kind",
        "rag_profiles",
        ["kind"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )
    op.create_table(
        "rag_profile_model_bindings",
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("model_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(["profile_id"], ["rag_profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["model_id"], ["rag_model_definitions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_id", "role", "model_id"),
    )


def downgrade() -> None:
    op.drop_table("rag_profile_model_bindings")
    op.drop_index("uq_rag_profiles_default_kind", table_name="rag_profiles")
    op.drop_table("rag_profiles")
    op.drop_table("rag_model_definitions")
