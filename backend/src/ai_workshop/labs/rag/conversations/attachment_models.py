"""Reserved conversation attachment identities; never a second original store."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ai_workshop.shared.models import Base, UUIDPrimaryKeyMixin


class ConversationAttachmentRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "rag_conversation_attachments"
    __table_args__ = (
        CheckConstraint(
            "state IN ('uploading','attached','failed')", name="ck_conversation_attachment_state"
        ),
        Index("ix_conversation_attachment_owner", "conversation_id", "owner_id"),
        CheckConstraint(
            "cleanup_state IN ('retained','cleanup_waiting','cleanup_candidate')",
            name="ck_conversation_attachment_cleanup",
        ),
    )
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_conversations.id", ondelete="RESTRICT"), nullable=False
    )
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    intake_id: Mapped[UUID | None] = mapped_column(ForeignKey("http_upload_intakes.id"))
    planned_document_id: Mapped[UUID | None] = mapped_column(Uuid)
    planned_version_id: Mapped[UUID | None] = mapped_column(Uuid)
    document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT")
    )
    asset_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("asset_versions.id", ondelete="RESTRICT")
    )
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80))
    cleanup_state: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default="retained"
    )
    cleanup_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cleanup_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    upload_terminated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cleanup_blockers: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
