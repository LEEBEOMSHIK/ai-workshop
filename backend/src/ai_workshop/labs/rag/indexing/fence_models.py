"""Durable document-scoped admission fence; there is deliberately no release API."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKeyConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from ai_workshop.shared.models import Base


class RagIndexWriteFenceRecord(Base):
    __tablename__ = "rag_index_write_fences"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "document_id"],
            ["documents.workspace_id", "documents.id"],
            name="fk_rag_index_write_fences_document",
            ondelete="RESTRICT",
        ),
        CheckConstraint("generation >= 1", name="ck_rag_index_write_fences_generation"),
    )
    document_id: Mapped[UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(nullable=False)
    generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
