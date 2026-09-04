from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from ai_workshop.shared.models import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SecretReferenceRecord(TimestampMixin, Base):
    __tablename__ = "rag_secret_references"
    __table_args__ = (
        CheckConstraint(
            "namespace = 'provider_secret'",
            name="ck_rag_secret_references_namespace",
        ),
        CheckConstraint(
            "reference_name ~ '^[a-z][a-z0-9]*-[a-z0-9]+(-[a-z0-9]+)*$' "
            "AND reference_name !~ '^(sk|sess|key|token|secret)-' "
            "AND reference_name !~ '^[0-9a-f]{24,}$'",
            name="ck_rag_secret_references_safe_name",
        ),
    )

    namespace: Mapped[str] = mapped_column(String(32), primary_key=True)
    reference_name: Mapped[str] = mapped_column(String(120), primary_key=True)
    created_by: Mapped[UUID] = mapped_column(Uuid, nullable=False)


class ModelDeploymentRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rag_model_deployments"

    created_by: Mapped[UUID] = mapped_column(Uuid, nullable=False)


class ModelDeploymentVersionRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rag_model_deployment_versions"
    __table_args__ = (
        UniqueConstraint("deployment_id", "version"),
        CheckConstraint("version > 0", name="ck_rag_deployment_versions_positive"),
        CheckConstraint(
            "provider IN ('local_openai_compatible', 'openai_responses')",
            name="ck_rag_deployment_versions_provider",
        ),
        CheckConstraint(
            "location IN ('local', 'on_premise', 'external')",
            name="ck_rag_deployment_versions_location",
        ),
        CheckConstraint(
            "timeout_seconds > 0 AND max_retries >= 0 AND retry_backoff_seconds >= 0",
            name="ck_rag_deployment_versions_retry",
        ),
        CheckConstraint(
            "(secret_ref IS NULL AND secret_ref_namespace IS NULL) OR "
            "(secret_ref IS NOT NULL AND secret_ref_namespace IS NOT NULL "
            "AND secret_ref_namespace = 'provider_secret')",
            name="ck_rag_deployment_versions_secret_ref_pair",
        ),
        ForeignKeyConstraint(
            ["secret_ref_namespace", "secret_ref"],
            ["rag_secret_references.namespace", "rag_secret_references.reference_name"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(location = 'external') = external_transfer",
            name="ck_rag_deployment_versions_external_location",
        ),
    )

    deployment_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_model_deployments.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    display_name: Mapped[str] = mapped_column(String(180), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False)
    model_definition_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_model_definitions.id", ondelete="RESTRICT"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(48), nullable=False)
    location: Mapped[str] = mapped_column(String(24), nullable=False)
    allowed_environments: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    provider_model_id: Mapped[str] = mapped_column(String(180), nullable=False)
    endpoint_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    secret_ref_namespace: Mapped[str | None] = mapped_column(String(32))
    secret_ref: Mapped[str | None] = mapped_column(String(120))
    capabilities: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    external_transfer: Mapped[bool] = mapped_column(Boolean, nullable=False)
    transmitted_data_categories: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    data_processing_notice_ref: Mapped[str | None] = mapped_column(String(180))
    timeout_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False)
    retry_backoff_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    healthcheck_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    development_only: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_by: Mapped[UUID] = mapped_column(Uuid, nullable=False)


class MigratedDeploymentProfileCopyRecord(Base):
    __tablename__ = "rag_llm_deployment_migration_profile_copies"

    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_profiles.id", ondelete="RESTRICT"), primary_key=True
    )
    deployment_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_model_deployment_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )


class DeploymentHealthCheckRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "rag_model_deployment_health_checks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ready', 'failed')",
            name="ck_rag_deployment_health_checks_status",
        ),
        CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0",
            name="ck_rag_deployment_health_checks_latency",
        ),
        Index(
            "ix_rag_deployment_health_checks_version_created",
            "deployment_version_id",
            "created_at",
        ),
    )

    deployment_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_model_deployment_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    safe_error_code: Mapped[str | None] = mapped_column(String(80))
    observed_provider_model_id: Mapped[str | None] = mapped_column(String(180))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    checked_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
