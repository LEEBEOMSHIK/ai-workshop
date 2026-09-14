from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ai_workshop.platform.assets import purge_models as purge_models  # noqa: F401
from ai_workshop.shared.models import Base, UUIDPrimaryKeyMixin

_MACHINE_IDENTIFIER_SQL = r"^[a-z][a-z0-9_]{0,79}$"
_SHA256_SQL = r"^[0-9a-f]{64}$"


class AssetPurgeProofRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "asset_purge_proofs"
    __table_args__ = (
        CheckConstraint(
            "inventory_version > 0",
            name="ck_asset_purge_proofs_inventory_version_positive",
        ),
        CheckConstraint(
            f"inventory_binding ~ '{_SHA256_SQL}'",
            name="ck_asset_purge_proofs_inventory_binding",
        ),
        CheckConstraint(
            f"binding ~ '{_SHA256_SQL}'",
            name="ck_asset_purge_proofs_binding",
        ),
        CheckConstraint(
            "policy_version > 0",
            name="ck_asset_purge_proofs_policy_version_positive",
        ),
        CheckConstraint(
            "backup_state = 'pending'",
            name="ck_asset_purge_proofs_backup_state",
        ),
        CheckConstraint(
            "external_state = 'unverified'",
            name="ck_asset_purge_proofs_external_state",
        ),
        UniqueConstraint(
            "workspace_id",
            "job_id",
            name="uq_asset_purge_proofs_workspace_job",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "job_id"],
            ["asset_purge_jobs.workspace_id", "asset_purge_jobs.id"],
            name="fk_asset_purge_proofs_job",
            ondelete="RESTRICT",
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    job_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    inventory_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    inventory_binding: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    binding: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    policy_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    backup_state: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="pending"
    )
    external_state: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="unverified"
    )


class AssetPurgeProofTargetRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "asset_purge_proof_targets"
    __table_args__ = (
        CheckConstraint(
            "target_kind IN ('document','folder')",
            name="ck_asset_purge_proof_targets_kind",
        ),
        CheckConstraint(
            "generation > 0",
            name="ck_asset_purge_proof_targets_generation_positive",
        ),
        CheckConstraint(
            "(target_kind='document' AND asset_version_id IS NOT NULL) OR "
            "(target_kind='folder' AND asset_version_id IS NULL)",
            name="ck_asset_purge_proof_targets_shape",
        ),
        Index(
            "uq_asset_purge_proof_document_versions",
            "proof_id",
            "target_id",
            "asset_version_id",
            unique=True,
            postgresql_where=text("target_kind = 'document'"),
        ),
        Index(
            "uq_asset_purge_proof_folders",
            "proof_id",
            "target_id",
            unique=True,
            postgresql_where=text("target_kind = 'folder'"),
        ),
    )

    proof_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "asset_purge_proofs.id",
            name="fk_asset_purge_proof_targets_proof",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    target_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    asset_version_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)


class AssetPurgeProofParticipantRecord(Base):
    __tablename__ = "asset_purge_proof_participants"
    __table_args__ = (
        PrimaryKeyConstraint(
            "proof_id",
            "participant",
            name="pk_asset_purge_proof_participants",
        ),
        CheckConstraint(
            f"participant ~ '{_MACHINE_IDENTIFIER_SQL}'",
            name="ck_asset_purge_proof_participants_participant",
        ),
        CheckConstraint(
            "contract_version > 0",
            name="ck_asset_purge_proof_participants_contract_positive",
        ),
        CheckConstraint(
            "attempt > 0",
            name="ck_asset_purge_proof_participants_attempt_positive",
        ),
        CheckConstraint(
            "deleted >= 0 AND retained_shared >= 0 AND residual_owned >= 0",
            name="ck_asset_purge_proof_participants_counts_nonnegative",
        ),
        CheckConstraint(
            "verified AND residual_owned = 0",
            name="ck_asset_purge_proof_participants_successful",
        ),
    )

    proof_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "asset_purge_proofs.id",
            name="fk_asset_purge_proof_participants_proof",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    participant: Mapped[str] = mapped_column(String(80), nullable=False)
    contract_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    attempt: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deleted: Mapped[int] = mapped_column(BigInteger, nullable=False)
    retained_shared: Mapped[int] = mapped_column(BigInteger, nullable=False)
    residual_owned: Mapped[int] = mapped_column(BigInteger, nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False)
