"""Private locators survive source rollback; attached originals restrict source deletion."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from ai_workshop.platform.assets import models as asset_models  # noqa: F401
from ai_workshop.shared.models import Base, UUIDPrimaryKeyMixin


class UploadAttemptRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "original_upload_attempts"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "workspace_id",
            "document_id",
            "asset_version_id",
            name="uq_original_upload_source",
        ),
        UniqueConstraint(
            "store_id", "binding_id", "canonical_key", name="uq_original_upload_canonical"
        ),
        UniqueConstraint(
            "store_id", "binding_id", "temporary_key", name="uq_original_upload_temporary"
        ),
        CheckConstraint("store_id ~ '^[a-z][a-z0-9_]{0,79}$'", name="ck_original_upload_store"),
        CheckConstraint(
            "suffix IN ('.pdf','.docx','.pptx','.xlsx','.txt','.md','.html','.htm')",
            name="ck_original_upload_suffix",
        ),
        CheckConstraint(
            "(new_document AND generation IS NULL) OR "
            "(NOT new_document AND generation >= 1 AND generation IS NOT NULL)",
            name="ck_original_upload_generation",
        ),
        CheckConstraint(
            "canonical_key = workspace_id::text || '/' || document_id::text || '/' "
            "|| replace(id::text, '-', '') || suffix",
            name="ck_original_upload_canonical",
        ),
        CheckConstraint(
            "temporary_key = workspace_id::text || '/' || document_id::text || '/.' "
            "|| replace(id::text, '-', '') || '.upload.tmp'",
            name="ck_original_upload_temporary",
        ),
        CheckConstraint(
            "(state = 'open' AND revision = 1) OR "
            "(state = 'published' AND revision = 2) OR "
            "(state = 'attached' AND revision = 3) OR "
            "(state = 'discarding' AND revision = 3) OR "
            "(state = 'abandoned' AND revision IN (2,4))",
            name="ck_original_upload_state_revision",
        ),
        CheckConstraint(
            "((state = 'open' OR (state = 'abandoned' AND revision = 2)) "
            "AND size IS NULL AND sha256 IS NULL) OR "
            "((state IN ('published','attached','discarding') OR "
            "(state = 'abandoned' AND revision = 4)) "
            "AND size IS NOT NULL AND size >= 0 AND sha256 IS NOT NULL "
            "AND sha256 ~ '^[0-9a-f]{64}$')",
            name="ck_original_upload_content",
        ),
        Index("ix_original_upload_document", "workspace_id", "document_id"),
        Index("ix_original_upload_unattached", "workspace_id", "state"),
    )
    workspace_id: Mapped[UUID] = mapped_column(Uuid)
    document_id: Mapped[UUID] = mapped_column(Uuid)
    asset_version_id: Mapped[UUID] = mapped_column(Uuid)
    user_id: Mapped[UUID] = mapped_column(Uuid)
    folder_id: Mapped[UUID | None] = mapped_column(Uuid)
    new_document: Mapped[bool] = mapped_column(Boolean)
    store_id: Mapped[str] = mapped_column(String(80))
    binding_id: Mapped[UUID] = mapped_column(Uuid)
    suffix: Mapped[str] = mapped_column(String(8))
    generation: Mapped[int | None] = mapped_column(BigInteger)
    canonical_key: Mapped[str] = mapped_column(String(700))
    temporary_key: Mapped[str] = mapped_column(String(700))
    state: Mapped[str] = mapped_column(String(16))
    revision: Mapped[int] = mapped_column(BigInteger)
    size: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OriginalResourceRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "original_file_resources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "document_id"],
            ["documents.workspace_id", "documents.id"],
            name="fk_original_resource_document",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["document_id", "asset_version_id"],
            ["asset_versions.document_id", "asset_versions.id"],
            name="fk_original_resource_version",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["id", "workspace_id", "document_id", "asset_version_id"],
            [
                "original_upload_attempts.id",
                "original_upload_attempts.workspace_id",
                "original_upload_attempts.document_id",
                "original_upload_attempts.asset_version_id",
            ],
            name="fk_original_resource_attempt",
            ondelete="RESTRICT",
        ),
        CheckConstraint("revision = 1", name="ck_original_resource_revision"),
        UniqueConstraint("asset_version_id", name="uq_original_resource_version"),
        Index("ix_original_resource_document", "workspace_id", "document_id"),
    )
    workspace_id: Mapped[UUID] = mapped_column(Uuid)
    document_id: Mapped[UUID] = mapped_column(Uuid)
    asset_version_id: Mapped[UUID] = mapped_column(Uuid)
    revision: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
