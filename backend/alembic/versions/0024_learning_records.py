"""Add private owner-scoped learning records and immutable revision snapshots."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0024_learning_records"
down_revision: str | Sequence[str] | None = "0023_rag_domains"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "learning_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("topic_keys", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("current_revision", sa.Integer(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "current_revision > 0",
            name="ck_learning_records_current_revision_positive",
        ),
        sa.CheckConstraint(
            "kind IN ('note', 'experiment')",
            name="ck_learning_records_kind",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_learning_records_owner_updated_id",
        "learning_records",
        ["owner_id", "updated_at", "id"],
        unique=False,
    )
    op.create_table(
        "learning_record_revisions",
        sa.Column("record_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("draft", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "revision > 0",
            name="ck_learning_record_revisions_revision_positive",
        ),
        sa.ForeignKeyConstraint(
            ["record_id"],
            ["learning_records.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("record_id", "revision"),
    )
    op.create_foreign_key(
        "fk_learning_records_current_revision",
        "learning_records",
        "learning_record_revisions",
        ["id", "current_revision"],
        ["record_id", "revision"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_learning_records_current_revision",
        "learning_records",
        type_="foreignkey",
    )
    op.drop_table("learning_record_revisions")
    op.drop_index("ix_learning_records_owner_updated_id", table_name="learning_records")
    op.drop_table("learning_records")

