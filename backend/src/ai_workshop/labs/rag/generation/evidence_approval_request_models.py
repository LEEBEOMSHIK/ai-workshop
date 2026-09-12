"""Request state and immutable idempotency receipts; no document bodies."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ai_workshop.shared.models import Base


class EvidenceApprovalRequestRecord(Base):
    __tablename__ = "rag_evidence_approval_requests"
    __table_args__ = (UniqueConstraint("resolved_by", "decision_request_id"),)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    requester_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    revision_id: Mapped[UUID] = mapped_column(ForeignKey("asset_versions.id", ondelete="RESTRICT"))
    provider: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    state_revision: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    decision_request_id: Mapped[UUID | None]
    decision_digest: Mapped[str | None] = mapped_column(String(64))


class EvidenceApprovalRequestReceiptRecord(Base):
    __tablename__ = "rag_evidence_approval_request_receipts"
    actor_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True
    )
    request_id: Mapped[UUID] = mapped_column(primary_key=True)
    request_digest: Mapped[str] = mapped_column(String(64))
    approval_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_evidence_approval_requests.id", ondelete="RESTRICT")
    )
