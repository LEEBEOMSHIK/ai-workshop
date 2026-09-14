from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ai_workshop.platform.assets import purge_models as purge_models  # noqa: F401
from ai_workshop.shared.models import Base, UUIDPrimaryKeyMixin

_MACHINE_IDENTIFIER_SQL = r"^[a-z][a-z0-9_]{0,79}$"
_SHA256_SQL = r"^[0-9a-f]{64}$"


class AssetPurgeInventoryRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "asset_purge_inventories"
    __table_args__ = (
        CheckConstraint(
            "version > 0",
            name="ck_asset_purge_inventories_version_positive",
        ),
        CheckConstraint(
            f"binding ~ '{_SHA256_SQL}'",
            name="ck_asset_purge_inventories_binding",
        ),
        UniqueConstraint(
            "workspace_id",
            "job_id",
            "version",
            name="uq_asset_purge_inventories_workspace_job_version",
        ),
        UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_asset_purge_inventories_workspace_id",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "job_id"],
            ["asset_purge_jobs.workspace_id", "asset_purge_jobs.id"],
            name="fk_asset_purge_inventories_job",
            ondelete="RESTRICT",
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    job_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    binding: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AssetPurgeInventoryTargetRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "asset_purge_inventory_targets"
    __table_args__ = (
        CheckConstraint(
            "target_kind IN ('document','folder')",
            name="ck_asset_purge_inventory_targets_kind",
        ),
        CheckConstraint(
            "generation > 0",
            name="ck_asset_purge_inventory_targets_generation_positive",
        ),
        CheckConstraint(
            "(target_kind='document' AND asset_version_id IS NOT NULL) OR "
            "(target_kind='folder' AND asset_version_id IS NULL)",
            name="ck_asset_purge_inventory_targets_shape",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "inventory_id"],
            ["asset_purge_inventories.workspace_id", "asset_purge_inventories.id"],
            name="fk_asset_purge_inventory_targets_inventory",
            ondelete="RESTRICT",
        ),
        Index(
            "uq_asset_purge_inventory_document_versions",
            "inventory_id",
            "target_id",
            "asset_version_id",
            unique=True,
            postgresql_where=text("target_kind = 'document'"),
        ),
        Index(
            "uq_asset_purge_inventory_folders",
            "inventory_id",
            "target_id",
            unique=True,
            postgresql_where=text("target_kind = 'folder'"),
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    inventory_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    target_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    asset_version_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)


class AssetPurgeInventoryParticipantRecord(Base):
    __tablename__ = "asset_purge_inventory_participants"
    __table_args__ = (
        PrimaryKeyConstraint(
            "inventory_id",
            "participant",
            name="pk_asset_purge_inventory_participants",
        ),
        CheckConstraint(
            f"participant ~ '{_MACHINE_IDENTIFIER_SQL}'",
            name="ck_asset_purge_inventory_participants_participant",
        ),
        CheckConstraint(
            "contract_version > 0",
            name="ck_asset_purge_inventory_participants_contract_positive",
        ),
        UniqueConstraint(
            "workspace_id",
            "inventory_id",
            "participant",
            name="uq_asset_purge_inventory_participants_workspace_inventory_key",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "inventory_id"],
            ["asset_purge_inventories.workspace_id", "asset_purge_inventories.id"],
            name="fk_asset_purge_inventory_participants_inventory",
            ondelete="RESTRICT",
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    inventory_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    participant: Mapped[str] = mapped_column(String(80), nullable=False)
    contract_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    exhausted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    supported: Mapped[bool] = mapped_column(Boolean, nullable=False)
    legacy_resolved: Mapped[bool] = mapped_column(Boolean, nullable=False)


class AssetPurgeInventoryResourceRecord(Base):
    __tablename__ = "asset_purge_inventory_resources"
    __table_args__ = (
        PrimaryKeyConstraint(
            "inventory_id",
            "participant",
            "kind",
            "resource_id",
            "resource_revision",
            name="pk_asset_purge_inventory_resources",
        ),
        CheckConstraint(
            f"kind ~ '{_MACHINE_IDENTIFIER_SQL}'",
            name="ck_asset_purge_inventory_resources_kind",
        ),
        CheckConstraint(
            "resource_revision > 0",
            name="ck_asset_purge_inventory_resources_revision_positive",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "inventory_id", "participant"],
            [
                "asset_purge_inventory_participants.workspace_id",
                "asset_purge_inventory_participants.inventory_id",
                "asset_purge_inventory_participants.participant",
            ],
            name="fk_asset_purge_inventory_resources_participant",
            ondelete="RESTRICT",
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    inventory_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    participant: Mapped[str] = mapped_column(String(80), nullable=False)
    kind: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    resource_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)


class AssetPurgeReceiptRecord(Base):
    __tablename__ = "asset_purge_receipts"
    __table_args__ = (
        PrimaryKeyConstraint(
            "inventory_id",
            "participant",
            "attempt",
            name="pk_asset_purge_receipts",
        ),
        CheckConstraint("attempt > 0", name="ck_asset_purge_receipts_attempt_positive"),
        CheckConstraint(
            f"binding ~ '{_SHA256_SQL}'",
            name="ck_asset_purge_receipts_binding",
        ),
        CheckConstraint(
            "contract_version > 0",
            name="ck_asset_purge_receipts_contract_positive",
        ),
        CheckConstraint(
            "deleted >= 0 AND retained_shared >= 0 AND residual_owned >= 0",
            name="ck_asset_purge_receipts_counts_nonnegative",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "inventory_id", "participant"],
            [
                "asset_purge_inventory_participants.workspace_id",
                "asset_purge_inventory_participants.inventory_id",
                "asset_purge_inventory_participants.participant",
            ],
            name="fk_asset_purge_receipts_participant",
            ondelete="RESTRICT",
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    inventory_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    participant: Mapped[str] = mapped_column(String(80), nullable=False)
    attempt: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    binding: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    contract_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    deleted: Mapped[int] = mapped_column(BigInteger, nullable=False)
    retained_shared: Mapped[int] = mapped_column(BigInteger, nullable=False)
    residual_owned: Mapped[int] = mapped_column(BigInteger, nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False)
