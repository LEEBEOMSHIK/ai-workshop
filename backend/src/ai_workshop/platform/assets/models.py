from uuid import UUID

from sqlalchemy import BigInteger, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ai_workshop.platform.assets.domain import VersionStatus
from ai_workshop.shared.models import Base, TimestampMixin, UUIDPrimaryKeyMixin


class FolderRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "folders"
    __table_args__ = (UniqueConstraint("workspace_id", "parent_id", "name"),)

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    parent_id: Mapped[UUID | None] = mapped_column(ForeignKey("folders.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(180), nullable=False)


class DocumentRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("workspace_id", "folder_id", "name"),)

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    folder_id: Mapped[UUID | None] = mapped_column(ForeignKey("folders.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    active_version_id: Mapped[UUID | None] = mapped_column(nullable=True)


class AssetVersionRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "asset_versions"
    __table_args__ = (UniqueConstraint("document_id", "number"),)

    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    object_key: Mapped[str] = mapped_column(String(700), unique=True, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    media_type: Mapped[str] = mapped_column(String(180), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[VersionStatus] = mapped_column(String(32), nullable=False)
