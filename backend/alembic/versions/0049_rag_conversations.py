"""Private durable conversations and idempotent, fenced request records."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0049_rag_conversations"
down_revision = "0048_job_metadata_ownership"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rag_conversations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "domain_id",
            sa.Uuid(),
            sa.ForeignKey("rag_domains.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("revision >= 1", name="ck_rag_conversation_revision"),
    )
    op.create_index(
        "ix_rag_conversations_owner_domain_updated",
        "rag_conversations",
        ["owner_id", "domain_id", "updated_at"],
    )
    op.create_table(
        "rag_conversation_turns",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("rag_conversations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("request", postgresql.JSONB(), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("scope_identity", sa.String(64), nullable=False),
        sa.Column("segment", sa.Integer(), nullable=False),
        sa.Column("response", postgresql.JSONB(none_as_null=True)),
        sa.Column("error_code", sa.String(100)),
        sa.Column("dependencies", postgresql.JSONB(), nullable=False),
        sa.Column("execution_terminated", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("conversation_id", "request_id", name="uq_rag_turn_request"),
        sa.UniqueConstraint("conversation_id", "sequence", name="uq_rag_turn_sequence"),
        sa.CheckConstraint("sequence >= 1 AND segment >= 1", name="ck_rag_turn_sequence"),
        sa.CheckConstraint(
            "status IN ('running','completed','failed','cancelled','interrupted')",
            name="ck_rag_turn_status",
        ),
    )


def downgrade() -> None:
    op.drop_table("rag_conversation_turns")
    op.drop_table("rag_conversations")
