"""Reserve conversation attachment provenance before receiving upload bytes."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0050_conversation_attachments"
down_revision = "0049_rag_conversations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rag_conversation_attachments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("rag_conversations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("intake_id", sa.Uuid(), sa.ForeignKey("http_upload_intakes.id")),
        sa.Column("planned_document_id", sa.Uuid()),
        sa.Column("planned_version_id", sa.Uuid()),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("documents.id", ondelete="RESTRICT")),
        sa.Column(
            "asset_version_id", sa.Uuid(), sa.ForeignKey("asset_versions.id", ondelete="RESTRICT")
        ),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error_code", sa.String(80)),
        sa.Column("cleanup_state", sa.String(24), nullable=False, server_default="retained"),
        sa.Column("cleanup_requested_at", sa.DateTime(timezone=True)),
        sa.Column("cleanup_checked_at", sa.DateTime(timezone=True)),
        sa.Column("upload_terminated_at", sa.DateTime(timezone=True)),
        sa.Column("cleanup_blockers", JSONB(), nullable=False, server_default="[]"),
        sa.CheckConstraint(
            "cleanup_state IN ('retained','cleanup_waiting','cleanup_candidate')",
            name="ck_conversation_attachment_cleanup",
        ),
        sa.CheckConstraint(
            "state IN ('uploading','attached','failed')", name="ck_conversation_attachment_state"
        ),
    )
    op.create_index(
        "ix_conversation_attachment_owner",
        "rag_conversation_attachments",
        ["conversation_id", "owner_id"],
    )


def downgrade() -> None:
    op.drop_table("rag_conversation_attachments")
