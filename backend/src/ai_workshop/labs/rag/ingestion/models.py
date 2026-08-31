from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ai_workshop.shared.models import Base, TimestampMixin


class RagIngestionJobRecord(TimestampMixin, Base):
    __tablename__ = "rag_ingestion_jobs"
    __table_args__ = (
        UniqueConstraint("asset_version_id", "indexing_profile_id"),
        UniqueConstraint("projection_id"),
    )

    job_id: Mapped[UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True
    )
    projection_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_document_projections.id", ondelete="CASCADE"), nullable=False
    )
    asset_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("asset_versions.id", ondelete="CASCADE"), nullable=False
    )
    indexing_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    requested_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    parsed_object_key: Mapped[str | None] = mapped_column(String(700))
    parsed_sha256: Mapped[str | None] = mapped_column(String(64))
    chunk_object_key: Mapped[str | None] = mapped_column(String(700))
    chunk_sha256: Mapped[str | None] = mapped_column(String(64))
    embedding_object_key: Mapped[str | None] = mapped_column(String(700))
    embedding_sha256: Mapped[str | None] = mapped_column(String(64))
    index_build_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("rag_index_builds.id", ondelete="SET NULL")
    )
    parsed_element_count: Mapped[int | None] = mapped_column(Integer)
    chunk_count: Mapped[int | None] = mapped_column(Integer)
    embedding_count: Mapped[int | None] = mapped_column(Integer)
    indexed_document_count: Mapped[int | None] = mapped_column(Integer)
    index_alias_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class RagIngestionDispatchRecord(TimestampMixin, Base):
    __tablename__ = "rag_ingestion_dispatches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'claimed', 'sent', 'cancelled')",
            name="ck_rag_ing_dispatch_status",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_rag_ing_dispatch_attempt"),
        CheckConstraint(
            "(status = 'pending' AND claim_token IS NULL AND claimed_at IS NULL "
            "AND sent_at IS NULL AND cancelled_at IS NULL) OR "
            "(status = 'claimed' AND claim_token IS NOT NULL "
            "AND claimed_at IS NOT NULL AND sent_at IS NULL "
            "AND cancelled_at IS NULL) OR "
            "(status = 'sent' AND claim_token IS NULL AND claimed_at IS NULL "
            "AND sent_at IS NOT NULL AND cancelled_at IS NULL) OR "
            "(status = 'cancelled' AND claim_token IS NULL "
            "AND claimed_at IS NULL AND sent_at IS NULL "
            "AND cancelled_at IS NOT NULL)",
            name="ck_rag_ing_dispatch_state",
        ),
        Index("ix_rag_ing_dispatch_ready", "status", "available_at"),
    )

    job_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_ingestion_jobs.job_id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'pending'")
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claim_token: Mapped[UUID | None] = mapped_column(nullable=True)
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    last_error: Mapped[str | None] = mapped_column(String(700))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RagAssetHandoffFailureRecord(TimestampMixin, Base):
    __tablename__ = "rag_asset_handoff_failures"
    __table_args__ = (
        CheckConstraint(
            "status IN ('retrying', 'resolved', 'quarantined', 'cancelled')",
            name="ck_rag_asset_handoff_status",
        ),
        CheckConstraint(
            "error_class IS NULL OR error_class IN "
            "('transient', 'permanent', 'obsolete')",
            name="ck_rag_asset_handoff_error_class",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_rag_asset_handoff_attempt"),
        CheckConstraint(
            "(status = 'retrying' AND error_class = 'transient' "
            "AND error_code IS NOT NULL AND last_error_message IS NOT NULL "
            "AND next_retry_at IS NOT NULL AND terminal_at IS NULL) OR "
            "(status = 'quarantined' AND error_class IN ('transient', 'permanent') "
            "AND error_code IS NOT NULL AND last_error_message IS NOT NULL "
            "AND next_retry_at IS NULL AND terminal_at IS NOT NULL) OR "
            "(status = 'cancelled' AND error_class = 'obsolete' "
            "AND error_code IS NOT NULL AND last_error_message IS NOT NULL "
            "AND next_retry_at IS NULL AND terminal_at IS NOT NULL) OR "
            "(status = 'resolved' AND error_class IS NULL AND error_code IS NULL "
            "AND last_error_message IS NULL AND next_retry_at IS NULL "
            "AND terminal_at IS NOT NULL)",
            name="ck_rag_asset_handoff_state",
        ),
        Index("ix_rag_asset_handoff_retry", "status", "next_retry_at"),
    )

    asset_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("asset_versions.id", ondelete="CASCADE"), primary_key=True
    )
    indexing_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_profiles.id", ondelete="RESTRICT"), primary_key=True
    )
    requested_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_class: Mapped[str | None] = mapped_column(String(32))
    error_code: Mapped[str | None] = mapped_column(String(100))
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_message: Mapped[str | None] = mapped_column(String(500))
