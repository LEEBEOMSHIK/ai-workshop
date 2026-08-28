"""Create folders, documents, and immutable versions."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_assets"
down_revision: str | Sequence[str] | None = "0002_workspaces"
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
        "folders",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(["parent_id"], ["folders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "parent_id", "name"),
    )
    op.create_table(
        "documents",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("folder_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("active_version_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(["folder_id"], ["folders.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "folder_id", "name"),
    )
    op.create_table(
        "asset_versions",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("object_key", sa.String(700), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("media_type", sa.String(180), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "number"),
        sa.UniqueConstraint("object_key"),
    )


def downgrade() -> None:
    op.drop_table("asset_versions")
    op.drop_table("documents")
    op.drop_table("folders")
