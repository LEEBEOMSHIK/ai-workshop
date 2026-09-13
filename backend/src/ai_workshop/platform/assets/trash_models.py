from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from ai_workshop.shared.models import Base, UUIDPrimaryKeyMixin


class AssetRetentionPolicyRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "asset_retention_policies"
    __table_args__ = (
        CheckConstraint(
            "version > 0",
            name="ck_asset_retention_policies_version_positive",
        ),
        CheckConstraint(
            "days > 0",
            name="ck_asset_retention_policies_days_positive",
        ),
        UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_asset_retention_policies_workspace_id",
        ),
        UniqueConstraint(
            "workspace_id",
            "version",
            name="uq_asset_retention_policies_workspace_version",
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "workspaces.id",
            name="fk_asset_retention_policies_workspace",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    days: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class AssetTrashBatchRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "asset_trash_batches"
    __table_args__ = (
        CheckConstraint(
            "purge_after > trashed_at",
            name="ck_asset_trash_batches_deadline",
        ),
        UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_asset_trash_batches_workspace_id",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "policy_version_id"],
            ["asset_retention_policies.workspace_id", "asset_retention_policies.id"],
            name="fk_asset_trash_batches_policy",
            ondelete="RESTRICT",
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "workspaces.id",
            name="fk_asset_trash_batches_workspace",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    actor_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    policy_version_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    trashed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    purge_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
