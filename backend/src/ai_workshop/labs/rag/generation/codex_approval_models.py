"""Private server-owned, body-free approvals and durable replay protection."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ai_workshop.shared.models import Base


class CodexCallApprovalRecord(Base):
    __tablename__ = "rag_codex_call_approvals"
    __table_args__ = (
        CheckConstraint(
            "operation IN ('search','evaluation','connection_check')",
            name="ck_codex_call_operation",
        ),
        CheckConstraint("stage IN ('contextualize','generate')", name="ck_codex_call_stage"),
        CheckConstraint("approved_payload_sha256 ~ '^[0-9a-f]{64}$'", name="ck_codex_call_digest"),
        CheckConstraint("expires_at > issued_at", name="ck_codex_call_expiry"),
        CheckConstraint(
            "input_classification IN ('public','synthetic')", name="ck_codex_call_classification"
        ),
        CheckConstraint("jsonb_typeof(binding) = 'object'", name="ck_codex_call_binding"),
        CheckConstraint(
            "binding->'version' IS NOT DISTINCT FROM '3'::jsonb", name="ck_codex_call_v3"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    approved_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    request_id: Mapped[UUID] = mapped_column(Uuid)
    configuration_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_configuration_versions.id", ondelete="RESTRICT")
    )
    deployment_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_model_deployment_versions.id", ondelete="RESTRICT")
    )
    generation_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_profiles.id", ondelete="RESTRICT")
    )
    operation: Mapped[str] = mapped_column(String(32))
    stage: Mapped[str] = mapped_column(String(32))
    binding: Mapped[dict[str, object]] = mapped_column(JSONB)
    approved_payload_sha256: Mapped[str] = mapped_column(String(64))
    input_classification: Mapped[str] = mapped_column(String(32))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consented: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CodexEvidenceApprovalRecord(Base):
    __tablename__ = "rag_codex_evidence_approvals"
    __table_args__ = (
        CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="ck_codex_evidence_digest"),
        CheckConstraint(
            "classification IN ('public','synthetic')", name="ck_codex_evidence_classification"
        ),
    )

    revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("asset_versions.id", ondelete="RESTRICT"), primary_key=True
    )
    content_sha256: Mapped[str] = mapped_column(String(64))
    classification: Mapped[str] = mapped_column(String(32))
    approved_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CodexCallConsumptionRecord(Base):
    __tablename__ = "rag_codex_call_consumptions"
    __table_args__ = (
        CheckConstraint("stage IN ('contextualize','generate')", name="ck_codex_consumption_stage"),
    )

    # Deliberately NO FK: the independent commit cannot wait on the locked approval.
    approval_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    request_id: Mapped[UUID] = mapped_column(Uuid)
    stage: Mapped[str] = mapped_column(String(32))
    consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EvidenceApprovalStateRecord(Base):
    """Current authority; legacy approvals remain untouched as historical records."""

    __tablename__ = "rag_evidence_approval_states"
    __table_args__ = (
        CheckConstraint("generation > 0", name="ck_evidence_state_generation"),
        CheckConstraint("status IN ('approved','revoked')", name="ck_evidence_state_status"),
        CheckConstraint("classification IN ('public','synthetic')", name="ck_evidence_state_class"),
        CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="ck_evidence_state_digest"),
    )

    revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("asset_versions.id", ondelete="RESTRICT"), primary_key=True
    )
    provider: Mapped[str] = mapped_column(String(64), primary_key=True)
    generation: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    content_sha256: Mapped[str] = mapped_column(String(64))
    classification: Mapped[str] = mapped_column(String(32))
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EvidenceApprovalEventRecord(Base):
    """Append-only transition and request receipt, containing no document bodies."""

    __tablename__ = "rag_evidence_approval_events"
    __table_args__ = (
        UniqueConstraint("actor_id", "request_id", name="uq_evidence_event_request"),
        CheckConstraint("generation > 0", name="ck_evidence_event_generation"),
        CheckConstraint("action IN ('approve','revoke')", name="ck_evidence_event_action"),
        CheckConstraint("classification IN ('public','synthetic')", name="ck_evidence_event_class"),
        CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="ck_evidence_event_content"),
        CheckConstraint(
            "request_digest IS NULL OR request_digest ~ '^[0-9a-f]{64}$'",
            name="ck_evidence_event_digest",
        ),
        CheckConstraint(
            "(request_id IS NULL) = (request_digest IS NULL)", name="ck_evidence_event_receipt"
        ),
    )

    revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("asset_versions.id", ondelete="RESTRICT"), primary_key=True
    )
    provider: Mapped[str] = mapped_column(String(64), primary_key=True)
    generation: Mapped[int] = mapped_column(Integer, primary_key=True)
    action: Mapped[str] = mapped_column(String(16))
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    classification: Mapped[str] = mapped_column(String(32))
    content_sha256: Mapped[str] = mapped_column(String(64))
    request_id: Mapped[UUID | None] = mapped_column(Uuid)
    request_digest: Mapped[str | None] = mapped_column(String(64))
