"""Durable cutover ownership and append-only external action facts."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ai_workshop.shared.models import Base


class AccessEpochKeyEventRecord(Base):
    __tablename__ = "rag_access_epoch_key_events"
    __table_args__ = (
        UniqueConstraint("execution_id", "sequence", name="uq_rag_epoch_key_event_sequence"),
        UniqueConstraint("action_id", "outcome", name="uq_rag_epoch_key_action_outcome"),
        Index(
            "uq_rag_epoch_key_issue",
            "issuance_id",
            unique=True,
            postgresql_where=text("outcome='pending' AND kind='issue'"),
        ),
        Index(
            "uq_rag_epoch_key_invalidate",
            "issuance_id",
            unique=True,
            postgresql_where=text("outcome='pending' AND kind='invalidate'"),
        ),
        CheckConstraint("sequence > 0 AND action_sequence > 0", name="ck_rag_epoch_key_sequence"),
        CheckConstraint("role IN ('reader','writer','collector')", name="ck_rag_epoch_key_role"),
        CheckConstraint("kind IN ('issue','invalidate')", name="ck_rag_epoch_key_kind"),
        CheckConstraint(
            "outcome IN ('pending','unknown','settled')", name="ck_rag_epoch_key_outcome"
        ),
        CheckConstraint(
            "permissions_sha256 ~ '^[0-9a-f]{64}$'", name="ck_rag_epoch_key_permissions"
        ),
        CheckConstraint(
            "(outcome='pending') = (manifest_json IS NULL)", name="ck_rag_epoch_key_manifest"
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    execution_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_access_epoch_executions.id", name="fk_rag_epoch_key_execution")
    )
    parent_action_id: Mapped[UUID] = mapped_column()
    action_id: Mapped[UUID] = mapped_column()
    sequence: Mapped[int] = mapped_column(Integer)
    action_sequence: Mapped[int] = mapped_column(Integer)
    executor_generation: Mapped[str] = mapped_column(String(36))
    role: Mapped[str] = mapped_column(String(16))
    issuance_id: Mapped[UUID] = mapped_column()
    kind: Mapped[str] = mapped_column(String(16))
    key_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    replaces_issuance_id: Mapped[UUID | None] = mapped_column(nullable=True)
    permissions_sha256: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(16))
    manifest_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AccessEpochRecord(Base):
    __tablename__ = "rag_access_epochs"
    __table_args__ = (
        UniqueConstraint("request_id", name="uq_rag_access_epoch_request"),
        CheckConstraint("gate_revision > 0", name="ck_rag_access_epoch_gate_revision"),
        CheckConstraint("store_id ~ '^[a-z][a-z0-9_]{0,79}$'", name="ck_rag_access_epoch_store"),
        CheckConstraint(
            "cluster_uuid ~ '^[A-Za-z0-9_-]{1,128}$'", name="ck_rag_access_epoch_cluster"
        ),
        CheckConstraint(
            "ordinal > 0 AND previous_floor >= 0 AND ordinal > previous_floor",
            name="ck_rag_access_epoch_ordinal",
        ),
        CheckConstraint(
            "phase IN ('prepared','old_stopped','old_retired',"
            "'secured_started','verified','receipted')",
            name="ck_rag_access_epoch_phase",
        ),
        CheckConstraint(
            "snapshot_sha256 ~ '^[0-9a-f]{64}$'", name="ck_rag_access_epoch_manifest_digest"
        ),
        Index(
            "uq_rag_access_epoch_active_cluster",
            "cluster_uuid",
            unique=True,
            postgresql_where=text("phase <> 'receipted'"),
        ),
        Index("uq_rag_access_epoch_cluster_ordinal", "cluster_uuid", "ordinal", unique=True),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    request_id: Mapped[UUID] = mapped_column()
    operation_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_alias_operations.id", name="fk_rag_access_epoch_operation")
    )
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", name="fk_rag_access_epoch_actor"))
    store_id: Mapped[str] = mapped_column(String(80))
    cluster_uuid: Mapped[str] = mapped_column(String(128))
    snapshot_sha256: Mapped[str] = mapped_column(String(64))
    gate_revision: Mapped[int] = mapped_column(Integer)
    ordinal: Mapped[int] = mapped_column(Integer)
    previous_floor: Mapped[int] = mapped_column(Integer)
    phase: Mapped[str] = mapped_column(String(24))
    original: Mapped[dict[str, object]] = mapped_column(JSONB)
    verified: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    manifests: Mapped[dict[str, str] | None] = mapped_column(JSONB, nullable=True)
    stopped_sequence: Mapped[int | None] = mapped_column(Integer)
    retired_sequence: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    receipted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AccessEpochExecutionRecord(Base):
    __tablename__ = "rag_access_epoch_executions"
    __table_args__ = (UniqueConstraint("epoch_id", name="uq_rag_access_epoch_execution"),)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    epoch_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_access_epochs.id", name="fk_rag_access_epoch_execution")
    )
    executor_generation: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AccessEpochEventRecord(Base):
    __tablename__ = "rag_access_epoch_events"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('pending','unknown','settled')", name="ck_rag_access_epoch_event_outcome"
        ),
        CheckConstraint(
            "sequence > 0 AND action_sequence > 0", name="ck_rag_access_epoch_event_sequence"
        ),
        CheckConstraint(
            "jsonb_typeof(expected_json::jsonb) = 'object' AND "
            "(manifest_json IS NULL OR jsonb_typeof(manifest_json::jsonb) = 'object')",
            name="ck_rag_access_epoch_event_json",
        ),
        UniqueConstraint("execution_id", "sequence", name="uq_rag_access_epoch_event_sequence"),
        UniqueConstraint("action_id", "outcome", name="uq_rag_access_epoch_action_outcome"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    execution_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_access_epoch_executions.id", name="fk_rag_access_epoch_event_execution")
    )
    action_id: Mapped[UUID] = mapped_column()
    sequence: Mapped[int] = mapped_column(Integer)
    action_sequence: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32))
    outcome: Mapped[str] = mapped_column(String(16))
    expected_json: Mapped[str] = mapped_column(Text)
    executor_generation: Mapped[str] = mapped_column(String(128))
    manifest_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AccessEpochFloorRecord(Base):
    __tablename__ = "rag_access_epoch_floors"
    __table_args__ = (
        CheckConstraint("ordinal > 0", name="ck_rag_access_epoch_floor"),
        UniqueConstraint("epoch_id", name="uq_rag_access_epoch_floor_epoch"),
    )
    cluster_uuid: Mapped[str] = mapped_column(String(128), primary_key=True)
    store_id: Mapped[str] = mapped_column(String(80))
    ordinal: Mapped[int] = mapped_column(Integer)
    epoch_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_access_epochs.id", name="fk_rag_access_epoch_floor_epoch")
    )
    identity: Mapped[dict[str, object]] = mapped_column(JSONB)
