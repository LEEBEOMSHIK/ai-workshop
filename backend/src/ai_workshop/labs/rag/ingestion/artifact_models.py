from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ai_workshop.labs.rag.documents.models import RagProjectionRecord
from ai_workshop.labs.rag.ingestion.models import RagIngestionJobRecord
from ai_workshop.platform.jobs.models import JobRecord
from ai_workshop.shared.models import Base, TimestampMixin, UUIDPrimaryKeyMixin

_MACHINE_IDENTIFIER_SQL = r"^[a-z][a-z0-9_]{0,79}$"
_SHA256_SQL = r"^[0-9a-f]{64}$"


def _append_required_source_unique_constraints() -> None:
    required = (
        (
            cast(Table, JobRecord.__table__),
            UniqueConstraint(
                "id",
                "workspace_id",
                "asset_version_id",
                name="uq_jobs_id_workspace_asset_version",
            ),
        ),
        (
            cast(Table, RagProjectionRecord.__table__),
            UniqueConstraint(
                "id",
                "asset_version_id",
                name="uq_rag_document_projections_id_asset_version",
            ),
        ),
        (
            cast(Table, RagIngestionJobRecord.__table__),
            UniqueConstraint(
                "job_id",
                "projection_id",
                "asset_version_id",
                name="uq_rag_ingestion_jobs_job_projection_asset_version",
            ),
        ),
    )
    for table, constraint in required:
        if constraint.name not in {item.name for item in table.constraints}:
            table.append_constraint(constraint)


_append_required_source_unique_constraints()


class RagArtifactBundleRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rag_artifact_bundles"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "document_id"],
            ["documents.workspace_id", "documents.id"],
            name="fk_rag_artifact_bundles_document",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["document_id", "asset_version_id"],
            ["asset_versions.document_id", "asset_versions.id"],
            name="fk_rag_artifact_bundles_asset_version",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["job_id", "workspace_id", "asset_version_id"],
            ["jobs.id", "jobs.workspace_id", "jobs.asset_version_id"],
            name="fk_rag_artifact_bundles_job_source",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["job_id", "projection_id", "asset_version_id"],
            [
                "rag_ingestion_jobs.job_id",
                "rag_ingestion_jobs.projection_id",
                "rag_ingestion_jobs.asset_version_id",
            ],
            name="fk_rag_artifact_bundles_ingestion_source",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["projection_id", "asset_version_id"],
            ["rag_document_projections.id", "rag_document_projections.asset_version_id"],
            name="fk_rag_artifact_bundles_projection_source",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("projection_id", name="uq_rag_artifact_bundles_projection"),
        CheckConstraint("revision > 0", name="ck_rag_artifact_bundles_revision_positive"),
    )

    projection_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    job_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    document_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    asset_version_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False)


class RagArtifactSlotRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rag_artifact_slots"
    __table_args__ = (
        UniqueConstraint(
            "bundle_id", "role", name="uq_rag_artifact_slots_bundle_role"
        ),
        UniqueConstraint(
            "store_id", "canonical_key", name="uq_rag_artifact_slots_store_key"
        ),
        UniqueConstraint(
            "id",
            "store_id",
            "store_binding_id",
            name="uq_rag_artifact_slots_id_store_binding",
        ),
        CheckConstraint(
            "role IN ('parsed','chunks','embeddings')",
            name="ck_rag_artifact_slots_role",
        ),
        CheckConstraint(
            f"store_id ~ '{_MACHINE_IDENTIFIER_SQL}'",
            name="ck_rag_artifact_slots_store_id",
        ),
        CheckConstraint(
            "char_length(canonical_key) > 0",
            name="ck_rag_artifact_slots_canonical_key_nonempty",
        ),
        CheckConstraint(
            "state IN ('reserved','verified')",
            name="ck_rag_artifact_slots_state",
        ),
        CheckConstraint(
            "(state = 'reserved' AND published_size IS NULL AND published_sha256 IS NULL) OR "
            "(state = 'verified' AND published_size IS NOT NULL AND published_size >= 0 AND "
            "published_sha256 IS NOT NULL AND "
            f"published_sha256 ~ '{_SHA256_SQL}')",
            name="ck_rag_artifact_slots_publication_shape",
        ),
    )

    bundle_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "rag_artifact_bundles.id",
            name="fk_rag_artifact_slots_bundle",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    store_id: Mapped[str] = mapped_column(String(80), nullable=False)
    store_binding_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    canonical_key: Mapped[str] = mapped_column(String(700), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    published_size: Mapped[int | None] = mapped_column(BigInteger)
    published_sha256: Mapped[str | None] = mapped_column(String(64))


class RagArtifactAttemptRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "rag_artifact_attempts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["slot_id", "store_id", "store_binding_id"],
            [
                "rag_artifact_slots.id",
                "rag_artifact_slots.store_id",
                "rag_artifact_slots.store_binding_id",
            ],
            name="fk_rag_artifact_attempts_slot_store_binding",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "store_id", "temporary_key", name="uq_rag_artifact_attempts_store_temp_key"
        ),
        Index(
            "uq_rag_artifact_attempts_open_slot",
            "slot_id",
            unique=True,
            postgresql_where=text("state = 'open'"),
        ),
        CheckConstraint(
            f"store_id ~ '{_MACHINE_IDENTIFIER_SQL}'",
            name="ck_rag_artifact_attempts_store_id",
        ),
        CheckConstraint(
            "char_length(temporary_key) > 0",
            name="ck_rag_artifact_attempts_temporary_key_nonempty",
        ),
        CheckConstraint(
            "proposed_size >= 0",
            name="ck_rag_artifact_attempts_proposed_size_nonnegative",
        ),
        CheckConstraint(
            f"proposed_sha256 ~ '{_SHA256_SQL}'",
            name="ck_rag_artifact_attempts_proposed_sha256",
        ),
        CheckConstraint(
            "state IN ('open','closed')",
            name="ck_rag_artifact_attempts_state",
        ),
        CheckConstraint(
            "result_code IS NULL OR "
            f"result_code ~ '{_MACHINE_IDENTIFIER_SQL}'",
            name="ck_rag_artifact_attempts_result_code",
        ),
        CheckConstraint(
            "(state = 'open' AND result_code IS NULL AND closed_at IS NULL) OR "
            "(state = 'closed' AND result_code IS NOT NULL AND closed_at IS NOT NULL)",
            name="ck_rag_artifact_attempts_close_shape",
        ),
    )

    slot_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    store_id: Mapped[str] = mapped_column(String(80), nullable=False)
    store_binding_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    temporary_key: Mapped[str] = mapped_column(String(700), nullable=False)
    proposed_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    proposed_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    result_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
