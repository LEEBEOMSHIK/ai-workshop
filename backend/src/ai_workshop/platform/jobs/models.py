from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ai_workshop.platform.jobs.domain import JobStatus, JobType
from ai_workshop.shared.models import Base, TimestampMixin, UUIDPrimaryKeyMixin


class JobRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("user_id", "type", "idempotency_key"),
        UniqueConstraint(
            "id", "workspace_id", "asset_version_id", name="uq_jobs_id_workspace_asset_version"
        ),
        CheckConstraint("revision IS NULL OR revision >= 1", name="ck_jobs_revision"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    asset_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("asset_versions.id", ondelete="CASCADE")
    )
    type: Mapped[JobType] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[JobStatus] = mapped_column(String(32), nullable=False)
    stage: Mapped[str] = mapped_column(String(100), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(String(500))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision: Mapped[int | None] = mapped_column(BigInteger)


class JobSourceRecord(Base):
    """Immutable source pin; a job status is never evidence that writers stopped."""

    __tablename__ = "job_source_ownership"
    __table_args__ = (
        ForeignKeyConstraint(
            ["job_id", "workspace_id", "asset_version_id"],
            ["jobs.id", "jobs.workspace_id", "jobs.asset_version_id"],
            name="fk_job_source_job",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "document_id"],
            ["documents.workspace_id", "documents.id"],
            name="fk_job_source_document",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["document_id", "asset_version_id"],
            ["asset_versions.document_id", "asset_versions.id"],
            name="fk_job_source_version",
            ondelete="RESTRICT",
        ),
        Index("ix_job_source_document", "workspace_id", "document_id"),
    )
    job_id: Mapped[UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[UUID]
    document_id: Mapped[UUID]
    asset_version_id: Mapped[UUID]
