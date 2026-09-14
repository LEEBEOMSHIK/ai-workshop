from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from ai_workshop.shared.models import Base, UUIDPrimaryKeyMixin


class AssetPurgeJobRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "asset_purge_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('purge_pending','purging','retry_wait','blocked','purged')",
            name="ck_asset_purge_jobs_status",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_asset_purge_jobs_attempt_count",
        ),
        CheckConstraint(
            "(status = 'purged' AND finished_at IS NOT NULL) OR "
            "(status <> 'purged' AND finished_at IS NULL)",
            name="ck_asset_purge_jobs_finished_state",
        ),
        UniqueConstraint(
            "workspace_id",
            "request_key",
            name="uq_asset_purge_jobs_workspace_request_key",
        ),
        UniqueConstraint(
            "trash_batch_id",
            name="uq_asset_purge_jobs_trash_batch_id",
        ),
        UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_asset_purge_jobs_workspace_id",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "trash_batch_id"],
            ["asset_trash_batches.workspace_id", "asset_trash_batches.id"],
            name="fk_asset_purge_jobs_trash_batch",
            ondelete="RESTRICT",
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "workspaces.id",
            name="fk_asset_purge_jobs_workspace",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    trash_batch_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    request_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="purge_pending"
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AssetPurgeDispatchRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "asset_purge_dispatches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','claimed','sent')",
            name="ck_asset_purge_dispatches_status",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_asset_purge_dispatches_attempt_count",
        ),
        CheckConstraint(
            "(status='pending' AND claim_token IS NULL AND claimed_at IS NULL "
            "AND sent_at IS NULL) OR "
            "(status='claimed' AND claim_token IS NOT NULL AND claimed_at IS NOT NULL "
            "AND sent_at IS NULL) OR "
            "(status='sent' AND claim_token IS NULL AND claimed_at IS NULL "
            "AND sent_at IS NOT NULL)",
            name="ck_asset_purge_dispatches_claim_state",
        ),
        UniqueConstraint(
            "job_id",
            name="uq_asset_purge_dispatches_job_id",
        ),
        Index(
            "ix_asset_purge_dispatches_status_available_at",
            "status",
            "available_at",
        ),
    )

    job_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "asset_purge_jobs.id",
            name="fk_asset_purge_dispatches_job",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="pending"
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    claim_token: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
