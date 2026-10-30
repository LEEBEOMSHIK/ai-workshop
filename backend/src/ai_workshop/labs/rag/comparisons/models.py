from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ai_workshop.shared.models import Base, UUIDPrimaryKeyMixin


class ComparisonReportRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "rag_comparison_reports"
    __table_args__ = (
        UniqueConstraint("owner_id", "source_key", name="uq_rag_comparison_source"),
        CheckConstraint("length(source_key) BETWEEN 1 AND 160", name="ck_rag_comparison_key"),
        CheckConstraint(
            "source_result_sha256 ~ '^[0-9a-f]{64}$' AND content_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_rag_comparison_hashes",
        ),
        CheckConstraint(
            "jsonb_typeof(payload) = 'object' AND octet_length(payload::text) <= 4194304",
            name="ck_rag_comparison_payload",
        ),
        Index("ix_rag_comparison_owner_completed", "owner_id", "completed_at", "id"),
    )
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    source_key: Mapped[str] = mapped_column(String(160))
    source_result_sha256: Mapped[str] = mapped_column(String(64))
    content_sha256: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, object]] = mapped_column(JSONB)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
