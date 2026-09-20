"""Persistent temporary claims pin actual sources and optional jobs."""

from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from ai_workshop.shared.models import Base, TimestampMixin, UUIDPrimaryKeyMixin


class TemporaryWorkspaceRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_temporary_workspaces"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "document_id"],
            ["documents.workspace_id", "documents.id"],
            name="fk_temporary_document",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["document_id", "asset_version_id"],
            ["asset_versions.document_id", "asset_versions.id"],
            name="fk_temporary_version",
            ondelete="RESTRICT",
        ),
        CheckConstraint("purpose IN ('parsing','pdf_preview')", name="ck_temporary_purpose"),
        CheckConstraint(
            "coverage IN ('bounded','runtime_unverified')", name="ck_temporary_coverage"
        ),
        CheckConstraint("generation >= 1", name="ck_temporary_generation"),
        CheckConstraint("store_id ~ '^[a-z][a-z0-9_]{0,79}$'", name="ck_temporary_store"),
        CheckConstraint(
            "(state = 'open' AND revision = 1) OR "
            "(state = 'closed' AND revision = 2) OR "
            "(state = 'cleaning' AND revision = 3) OR "
            "(state = 'cleaned' AND revision = 4)",
            name="ck_temporary_state_revision",
        ),
        CheckConstraint(
            "error_code IS NULL OR error_code IN "
            "('writer_unconfirmed','cleanup_unconfirmed','ownership_failed')",
            name="ck_temporary_error_code",
        ),
        Index("ix_temporary_document", "workspace_id", "document_id"),
        Index("ix_temporary_job", "job_id"),
    )
    workspace_id: Mapped[UUID]
    document_id: Mapped[UUID]
    asset_version_id: Mapped[UUID]
    job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("jobs.id", name="fk_temporary_job", ondelete="RESTRICT")
    )
    purpose: Mapped[str] = mapped_column(String(32))
    store_id: Mapped[str] = mapped_column(String(80))
    binding_id: Mapped[UUID]
    generation: Mapped[int] = mapped_column(BigInteger)
    coverage: Mapped[str] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(16))
    revision: Mapped[int] = mapped_column(BigInteger)
    error_code: Mapped[str | None] = mapped_column(String(32))
