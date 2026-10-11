"""Independent journal: deliberately no FK to the caller's locked source rows."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ai_workshop.shared.models import Base


class AliasOperationRecord(Base):
    __tablename__ = "rag_alias_operations"
    __table_args__ = (
        CheckConstraint("store_id ~ '^[a-z][a-z0-9_]{0,79}$'", name="ck_rag_alias_store"),
        CheckConstraint("cluster_uuid ~ '^[A-Za-z0-9_-]{1,128}$'", name="ck_rag_alias_cluster"),
        CheckConstraint("alias ~ '^[a-z0-9][a-z0-9._-]{0,254}$'", name="ck_rag_alias_name"),
        CheckConstraint("jsonb_typeof(targets) = 'array'", name="ck_rag_alias_targets"),
        CheckConstraint(
            "(state = 'open' AND closed_at IS NULL AND result_code IS NULL) OR "
            "(state = 'closed' AND closed_at IS NOT NULL AND result_code IS NOT NULL "
            "AND result_code IN ('confirmed', 'not_dispatched', 'recovered_terminated'))",
            name="ck_rag_alias_state",
        ),
        CheckConstraint(
            "phase IN ('legacy_unknown', 'reserved', 'dispatching')", name="ck_rag_alias_phase"
        ),
        CheckConstraint(
            "result_code IS NULL OR (result_code = 'not_dispatched' AND phase = 'reserved') OR "
            "(result_code IN ('confirmed', 'recovered_terminated') AND "
            "phase IN ('legacy_unknown', 'dispatching'))",
            name="ck_rag_alias_terminal_phase",
        ),
        Index(
            "uq_rag_alias_open",
            "cluster_uuid",
            "alias",
            unique=True,
            postgresql_where=text("state = 'open'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    store_id: Mapped[str] = mapped_column(String(80))
    cluster_uuid: Mapped[str] = mapped_column(String(128))
    alias: Mapped[str] = mapped_column(String(255))
    indexing_profile_id: Mapped[UUID] = mapped_column()
    document_processing_profile_id: Mapped[UUID] = mapped_column()
    targets: Mapped[list[str]] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(String(16))
    phase: Mapped[str] = mapped_column(String(24), server_default="legacy_unknown")
    result_code: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AliasClusterGateRecord(Base):
    __tablename__ = "rag_alias_cluster_gates"
    __table_args__ = (
        CheckConstraint(
            "cluster_uuid ~ '^[A-Za-z0-9_-]{1,128}$'", name="ck_rag_alias_gate_cluster"
        ),
        CheckConstraint("state IN ('admitted', 'frozen')", name="ck_rag_alias_gate_state"),
        CheckConstraint("revision >= 0", name="ck_rag_alias_gate_revision"),
        CheckConstraint(
            "(request_id IS NULL AND actor_id IS NULL AND operation_id IS NULL AND "
            "snapshot_sha256 IS NULL AND revision = 0 AND state = 'admitted') OR "
            "(request_id IS NOT NULL AND actor_id IS NOT NULL AND operation_id IS NOT NULL "
            "AND snapshot_sha256 IS NOT NULL AND snapshot_sha256 ~ '^[0-9a-f]{64}$' "
            "AND revision > 0)",
            name="ck_rag_alias_gate_claim",
        ),
    )

    cluster_uuid: Mapped[str] = mapped_column(String(128), primary_key=True)
    state: Mapped[str] = mapped_column(String(16), server_default="admitted")
    revision: Mapped[int] = mapped_column(Integer, server_default="0")
    request_id: Mapped[UUID | None] = mapped_column(unique=True)
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    operation_id: Mapped[UUID | None] = mapped_column(ForeignKey("rag_alias_operations.id"))
    snapshot_sha256: Mapped[str | None] = mapped_column(String(64))


class AliasRecoveryReceiptRecord(Base):
    __tablename__ = "rag_alias_recovery_receipts"
    __mapper_args__ = {"eager_defaults": False}
    __table_args__ = (
        CheckConstraint(
            "result_code IN ('not_dispatched', 'recovered_terminated')",
            name="ck_rag_alias_receipt_result",
        ),
        CheckConstraint(
            "snapshot_sha256 ~ '^[0-9a-f]{64}$' AND proof_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_rag_alias_receipt_digest",
        ),
        CheckConstraint("gate_revision > 0", name="ck_rag_alias_receipt_revision"),
        CheckConstraint(
            "jsonb_typeof(proof) = 'object' AND ((schema_version = 1 AND ("
            "(result_code = 'not_dispatched' AND proof_kind = 'reserved_cas' "
            "AND proof = '{}'::jsonb) OR (result_code = 'recovered_terminated' AND "
            "proof_kind = 'local_single_node_controlled_restart' AND "
            "proof->>'proof_kind' = proof_kind AND (proof->>'schema_version')::integer = 1 AND "
            "proof->>'request_id' = request_id::text AND "
            "proof->>'operation_id' = operation_id::text AND "
            "proof->>'snapshot_sha256' = snapshot_sha256 AND "
            "proof->>'cluster_uuid' = cluster_uuid))) OR "
            "(schema_version = 2 AND result_code = 'recovered_terminated' AND "
            "proof_kind = 'local_single_node_access_epoch' AND "
            "proof->>'proof_kind' = proof_kind AND proof->>'schema_version' = '2' AND "
            "proof->>'request_id' = request_id::text AND "
            "proof->>'operation_id' = operation_id::text AND "
            "proof->>'actor_id' = actor_id::text AND proof->>'cluster_uuid' = cluster_uuid AND "
            "proof->>'snapshot_sha256' = snapshot_sha256 AND "
            "proof->>'gate_revision' = gate_revision::text))",
            name="ck_rag_alias_receipt_proof",
        ),
        CheckConstraint(
            "(schema_version=1 AND access_epoch_id IS NULL AND execution_id IS NULL) OR "
            "(schema_version=2 AND access_epoch_id IS NOT NULL AND execution_id IS NOT NULL)",
            name="ck_rag_alias_receipt_epoch_binding",
        ),
    )

    request_id: Mapped[UUID] = mapped_column(primary_key=True)
    operation_id: Mapped[UUID] = mapped_column(ForeignKey("rag_alias_operations.id"), unique=True)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    cluster_uuid: Mapped[str] = mapped_column(String(128))
    snapshot_sha256: Mapped[str] = mapped_column(String(64))
    gate_revision: Mapped[int] = mapped_column(Integer)
    result_code: Mapped[str] = mapped_column(String(32))
    proof_kind: Mapped[str] = mapped_column(String(48))
    schema_version: Mapped[int] = mapped_column(Integer)
    proof: Mapped[dict[str, object]] = mapped_column(JSONB)
    proof_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # 0061 v1 SELECT/INSERT remain valid until the separately approved migration;
    # 0062 fills linkage in its BEFORE INSERT trigger, then checks it atomically.
    access_epoch_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "rag_access_epochs.id",
            name="fk_rag_alias_receipt_access_epoch",
            deferrable=True,
            initially="DEFERRED",
        ),
        deferred=True,
        server_default=text("NULL"),
    )
    execution_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "rag_access_epoch_executions.id",
            name="fk_rag_alias_receipt_execution",
            deferrable=True,
            initially="DEFERRED",
        ),
        deferred=True,
        server_default=text("NULL"),
    )
