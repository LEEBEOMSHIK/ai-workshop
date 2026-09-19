"""RAG-owned index ledger; tracking children prevent premature cascading deletion."""

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ai_workshop.labs.rag.documents.models import RagIndexBuildRecord, RagProjectionRecord
from ai_workshop.labs.rag.indexing.tracking_contracts import INDEX_RESULT_CODES
from ai_workshop.labs.rag.ingestion import artifact_models as _artifact_models  # noqa: F401
from ai_workshop.labs.rag.ingestion.models import RagIngestionJobRecord
from ai_workshop.shared.models import Base, TimestampMixin, UUIDPrimaryKeyMixin

PROFILES = ("document_processing_profile_id", "indexing_profile_id")
PARENT_KEYS = (
    (
        RagIndexBuildRecord.__table__,
        "uq_rag_index_builds_tracking_identity",
        ("id", "projection_id", *PROFILES),
    ),
    (
        RagProjectionRecord.__table__,
        "uq_rag_projections_tracking_identity",
        ("id", "asset_version_id", *PROFILES),
    ),
    (
        RagIngestionJobRecord.__table__,
        "uq_rag_ingestion_tracking_identity",
        ("job_id", "projection_id", "asset_version_id", *PROFILES),
    ),
)
for table, name, columns in PARENT_KEYS:
    parent_table = cast(Table, table)
    if not any(c.name == name for c in parent_table.constraints):
        parent_table.append_constraint(UniqueConstraint(*columns, name=name))


def _fk(
    local: tuple[str, ...], remote: str, columns: tuple[str, ...], label: str
) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        local,
        [f"{remote}.{column}" for column in columns],
        name=f"fk_rag_index_resources_{label}",
        ondelete="RESTRICT",
    )


class RagIndexResourceRecord(TimestampMixin, Base):
    __tablename__ = "rag_index_resources"
    __table_args__ = (
        _fk(
            ("build_id", "projection_id", *PROFILES),
            "rag_index_builds",
            ("id", "projection_id", *PROFILES),
            "build",
        ),
        _fk(
            ("projection_id", "asset_version_id", *PROFILES),
            "rag_document_projections",
            ("id", "asset_version_id", *PROFILES),
            "projection",
        ),
        _fk(
            ("job_id", "projection_id", "asset_version_id", *PROFILES),
            "rag_ingestion_jobs",
            ("job_id", "projection_id", "asset_version_id", *PROFILES),
            "ingestion",
        ),
        _fk(
            ("job_id", "workspace_id", "asset_version_id"),
            "jobs",
            ("id", "workspace_id", "asset_version_id"),
            "job",
        ),
        _fk(("workspace_id", "document_id"), "documents", ("workspace_id", "id"), "document"),
        _fk(
            ("document_id", "asset_version_id"), "asset_versions", ("document_id", "id"), "version"
        ),
        UniqueConstraint("cluster_uuid", "index_name", name="uq_rag_index_resources_cluster_name"),
        CheckConstraint(
            "(input_fingerprint IS NULL AND chunk_ids_sha256 IS NULL) OR "
            "(input_fingerprint IS NOT NULL AND chunk_ids_sha256 IS NOT NULL "
            "AND chunk_ids_sha256 ~ '^[0-9a-f]{64}$')",
            name="ck_rag_index_resources_input_pair",
        ),
        CheckConstraint("revision > 0", name="ck_rag_index_resources_revision"),
        CheckConstraint("store_id ~ '^[a-z][a-z0-9_]{0,79}$'", name="ck_rag_index_resources_store"),
        CheckConstraint(
            "cluster_uuid ~ '^[A-Za-z0-9_-]{1,128}$'", name="ck_rag_index_resources_cluster"
        ),
        CheckConstraint(
            "index_uuid IS NULL OR index_uuid ~ '^[A-Za-z0-9_-]{1,128}$'",
            name="ck_rag_index_resources_uuid",
        ),
        CheckConstraint(
            "input_fingerprint IS NULL OR input_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_rag_index_resources_fingerprint",
        ),
        CheckConstraint(
            "index_name ~ '^[a-z0-9][a-z0-9._-]{0,254}$' AND "
            "alias ~ '^[a-z0-9][a-z0-9._-]{0,254}$'",
            name="ck_rag_index_resources_names",
        ),
        CheckConstraint(
            "name_contract_version = 1 AND mapping_version > 0 AND "
            "vector_dimension > 0 AND similarity = 'cosine'",
            name="ck_rag_index_resources_descriptor",
        ),
    )
    build_id: Mapped[UUID] = mapped_column(primary_key=True)
    projection_id: Mapped[UUID] = mapped_column(nullable=False)
    job_id: Mapped[UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(nullable=False)
    document_id: Mapped[UUID] = mapped_column(nullable=False)
    asset_version_id: Mapped[UUID] = mapped_column(nullable=False)
    document_processing_profile_id: Mapped[UUID] = mapped_column(nullable=False)
    indexing_profile_id: Mapped[UUID] = mapped_column(nullable=False)
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    store_id: Mapped[str] = mapped_column(String(80), nullable=False)
    cluster_uuid: Mapped[str] = mapped_column(String(128), nullable=False)
    index_name: Mapped[str] = mapped_column(String(255), nullable=False)
    alias: Mapped[str] = mapped_column(String(255), nullable=False)
    name_contract_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    mapping_version: Mapped[int] = mapped_column(Integer, nullable=False)
    vector_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    similarity: Mapped[str] = mapped_column(String(32), nullable=False)
    index_uuid: Mapped[str | None] = mapped_column(String(128))
    input_fingerprint: Mapped[str | None] = mapped_column(String(64))
    chunk_ids_sha256: Mapped[str | None] = mapped_column(String(64))


class RagIndexAttemptRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "rag_index_attempts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["build_id"],
            ["rag_index_resources.build_id"],
            name="fk_rag_index_attempts_resource",
            ondelete="RESTRICT",
        ),
        Index(
            "uq_rag_index_attempts_open_resource",
            "build_id",
            unique=True,
            postgresql_where=text("state = 'open'"),
        ),
        CheckConstraint("operation = 'prepare'", name="ck_rag_index_attempts_operation"),
        CheckConstraint("state IN ('open','closed')", name="ck_rag_index_attempts_state"),
        CheckConstraint(
            "result_code IS NULL OR result_code IN ("
            + ",".join(repr(c) for c in sorted(INDEX_RESULT_CODES))
            + ")",
            name="ck_rag_index_attempts_result",
        ),
        CheckConstraint(
            "(state = 'open' AND closed_at IS NULL AND result_code IS NULL) OR "
            "(state = 'closed' AND closed_at IS NOT NULL AND result_code IS NOT NULL)",
            name="ck_rag_index_attempts_close_shape",
        ),
    )
    build_id: Mapped[UUID] = mapped_column(nullable=False)
    operation: Mapped[str] = mapped_column(String(16), nullable=False, default="prepare")
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    result_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
