"""Append-only, body-free exact-configuration verification and stage audit."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ai_workshop.shared.models import Base


class CodexVerificationAttemptRecord(Base):
    __tablename__ = "rag_codex_verification_attempts"
    __table_args__ = (
        CheckConstraint(
            "binding IS NULL OR jsonb_typeof(binding) = 'object'", name="ck_codex_verify_binding"
        ),
        CheckConstraint(
            "(success AND binding IS NOT NULL AND usage_present AND safe_error_code IS NULL) "
            "OR (NOT success AND safe_error_code IS NOT NULL)",
            name="ck_codex_verify_outcome",
        ),
        Index("ix_codex_verify_configuration_sequence", "configuration_version_id", "sequence"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    sequence: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    configuration_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_configuration_versions.id", ondelete="RESTRICT")
    )
    generation_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_profiles.id", ondelete="RESTRICT")
    )
    deployment_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_model_deployment_versions.id", ondelete="RESTRICT")
    )
    checked_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    binding: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True))
    success: Mapped[bool] = mapped_column(Boolean)
    usage_present: Mapped[bool] = mapped_column(Boolean)
    safe_error_code: Mapped[str | None] = mapped_column(String(80))
    requested_provider_model_id: Mapped[str] = mapped_column(String(180))
    observed_provider_model_id: Mapped[str | None] = mapped_column(String(180))


class CodexStageAuditRecord(Base):
    __tablename__ = "rag_codex_stage_audits"
    __table_args__ = (
        CheckConstraint("stage IN ('contextualize','generate')", name="ck_codex_audit_stage"),
        CheckConstraint("jsonb_typeof(details) = 'object'", name="ck_codex_audit_details"),
        Index("ix_codex_stage_audit_request", "request_id", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    request_id: Mapped[UUID] = mapped_column(Uuid)
    configuration_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_configuration_versions.id", ondelete="RESTRICT")
    )
    generation_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_profiles.id", ondelete="RESTRICT")
    )
    deployment_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_model_deployment_versions.id", ondelete="RESTRICT")
    )
    stage: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    details: Mapped[dict[str, object]] = mapped_column(JSONB)
