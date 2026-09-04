from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from ai_workshop.shared.models import Base, UUIDPrimaryKeyMixin


class GenerationExecutionAuditRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "rag_generation_execution_audits"
    __table_args__ = (
        CheckConstraint(
            "status IN ('allowed', 'denied', 'succeeded', 'failed')",
            name="ck_rag_generation_audits_status",
        ),
        CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name="ck_rag_generation_audits_input_tokens",
        ),
        CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name="ck_rag_generation_audits_output_tokens",
        ),
        CheckConstraint("latency_ms >= 0", name="ck_rag_generation_audits_latency"),
        Index(
            "ix_rag_generation_audits_actor_created", "actor_id", "created_at"
        ),
        Index(
            "ix_rag_generation_audits_configuration_created",
            "configuration_version_id",
            "created_at",
        ),
        Index(
            "ix_rag_generation_audits_deployment_created",
            "deployment_version_id",
            "created_at",
        ),
    )

    actor_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    configuration_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_configuration_versions.id", ondelete="RESTRICT"), nullable=False
    )
    generation_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    deployment_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_model_deployment_versions.id", ondelete="RESTRICT"), nullable=False
    )
    installation_policy_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_installation_data_policy_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(48), nullable=False)
    provider_model_id: Mapped[str] = mapped_column(String(180), nullable=False)
    location: Mapped[str] = mapped_column(String(24), nullable=False)
    external_transfer: Mapped[bool] = mapped_column(Boolean, nullable=False)
    policy_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    policy_reason_code: Mapped[str | None] = mapped_column(String(80))
    prompt_ref: Mapped[str] = mapped_column(String(180), nullable=False)
    prompt_version: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_ids: Mapped[list[UUID]] = mapped_column(ARRAY(Uuid), nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_reported_input_tokens: Mapped[int | None] = mapped_column(Integer)
    provider_reported_output_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_basis_version: Mapped[str | None] = mapped_column(String(80))
    estimated_cost_microunits: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    safe_error_code: Mapped[str | None] = mapped_column(String(80))
    correlation_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GenerationAuditWorkspacePolicySnapshotRecord(Base):
    __tablename__ = "rag_generation_audit_workspace_policies"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_policy_version_id", "workspace_id"],
            [
                "rag_workspace_data_policy_versions.id",
                "rag_workspace_data_policy_versions.workspace_id",
            ],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("audit_id", "workspace_id"),
    )

    audit_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_generation_execution_audits.id", ondelete="CASCADE"),
        primary_key=True,
    )
    workspace_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    workspace_policy_version_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
