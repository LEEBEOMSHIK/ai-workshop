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
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from ai_workshop.platform.assets import trash_models as trash_models  # noqa: F401
from ai_workshop.platform.assets.domain import VersionStatus
from ai_workshop.shared.models import Base, TimestampMixin, UUIDPrimaryKeyMixin

_LIFECYCLE_CHECK = (
    "lifecycle IN ('active', 'trashed', 'purge_pending', 'purging', "
    "'retry_wait', 'blocked')"
)
_TRASH_STATE_CHECK = (
    "(lifecycle = 'active' AND trash_batch_id IS NULL "
    "AND trashed_at IS NULL AND purge_after IS NULL) OR "
    "(lifecycle <> 'active' AND trash_batch_id IS NOT NULL "
    "AND trashed_at IS NOT NULL AND purge_after IS NOT NULL "
    "AND purge_after > trashed_at)"
)


class FolderRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "folders"
    __table_args__ = (
        UniqueConstraint("workspace_id", "parent_id", "name"),
        CheckConstraint("metadata_revision >= 1", name="ck_folder_metadata_revision"),
        CheckConstraint(_LIFECYCLE_CHECK, name="ck_folder_lifecycle"),
        CheckConstraint(
            "lifecycle_generation >= 1",
            name="ck_folder_lifecycle_generation",
        ),
        CheckConstraint(_TRASH_STATE_CHECK, name="ck_folder_trash_state"),
        ForeignKeyConstraint(
            ["workspace_id", "trash_batch_id"],
            ["asset_trash_batches.workspace_id", "asset_trash_batches.id"],
            name="fk_folder_trash_batch",
            ondelete="RESTRICT",
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    parent_id: Mapped[UUID | None] = mapped_column(ForeignKey("folders.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    metadata_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    lifecycle: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active", server_default="active"
    )
    lifecycle_generation: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=1, server_default="1"
    )
    trash_batch_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    trashed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    purge_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DocumentRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_workspace_id", "workspace_id"),
        CheckConstraint("metadata_revision >= 1", name="ck_document_metadata_revision"),
        CheckConstraint(_LIFECYCLE_CHECK, name="ck_document_lifecycle"),
        CheckConstraint(
            "lifecycle_generation >= 1",
            name="ck_document_lifecycle_generation",
        ),
        CheckConstraint(_TRASH_STATE_CHECK, name="ck_document_trash_state"),
        ForeignKeyConstraint(
            ["workspace_id", "trash_batch_id"],
            ["asset_trash_batches.workspace_id", "asset_trash_batches.id"],
            name="fk_document_trash_batch",
            ondelete="RESTRICT",
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    folder_id: Mapped[UUID | None] = mapped_column(ForeignKey("folders.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    active_version_id: Mapped[UUID | None] = mapped_column(nullable=True)
    metadata_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    lifecycle: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active", server_default="active"
    )
    lifecycle_generation: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=1, server_default="1"
    )
    trash_batch_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    trashed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    purge_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AssetVersionRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "asset_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "number"),
        Index("ix_asset_versions_sha256", "sha256"),
    )

    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    object_key: Mapped[str] = mapped_column(String(700), unique=True, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    media_type: Mapped[str] = mapped_column(String(180), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[VersionStatus] = mapped_column(String(32), nullable=False)
