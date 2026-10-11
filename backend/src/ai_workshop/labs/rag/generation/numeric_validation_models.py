"""Immutable numeric receipts contain identifiers and digests, never source values."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ai_workshop.shared.models import Base, UUIDPrimaryKeyMixin


class NumericValidationRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "rag_generation_numeric_validations"
    __table_args__ = (
        CheckConstraint("schema_version = 3", name="ck_numeric_schema"),
        CheckConstraint("policy_ref = 'source-numeric-proof-v1'", name="ck_numeric_policy"),
        *(
            CheckConstraint(f"{name} ~ '^[0-9a-f]{{64}}$'", name=f"ck_numeric_{name}")
            for name in ("policy_digest", "catalogue_digest", "payload_digest")
        ),
    )
    audit_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_generation_execution_audits.id", ondelete="RESTRICT"), unique=True
    )
    request_id: Mapped[UUID] = mapped_column(unique=True)
    execution_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("rag_executions.id", ondelete="RESTRICT"), unique=True
    )
    configuration_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_configuration_versions.id", ondelete="RESTRICT")
    )
    generation_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_profiles.id", ondelete="RESTRICT")
    )
    schema_version: Mapped[int] = mapped_column(Integer)
    policy_ref: Mapped[str] = mapped_column(String(80))
    policy_digest: Mapped[str] = mapped_column(String(64))
    catalogue_digest: Mapped[str] = mapped_column(String(64))
    payload_digest: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
