"""Additive storage; extractive-v1 tables and acceptance remain unchanged."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ai_workshop.shared.models import Base, TimestampMixin, UUIDPrimaryKeyMixin


class GenerativePolicyRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rag_generative_policies"
    __table_args__ = (UniqueConstraint("owner_id", "name", "version"),)

    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(180))
    version: Mapped[int] = mapped_column(Integer)
    definition: Mapped[dict[str, object]] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))


class GenerativeRunRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rag_generative_runs"
    __table_args__ = (
        Index("ix_rag_generative_runs_owner", "owner_id", "created_at"),
        UniqueConstraint("owner_id", "request_id"),
    )

    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    request_id: Mapped[UUID] = mapped_column()
    dataset_snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_evaluation_datasets.id", ondelete="RESTRICT"),
    )
    policy_id: Mapped[UUID] = mapped_column(ForeignKey("rag_generative_policies.id"))
    metric_version: Mapped[str] = mapped_column(String(32), default="generative-v1")
    snapshot: Mapped[dict[str, object]] = mapped_column(JSON)
    snapshot_bytes: Mapped[bytes] = mapped_column(LargeBinary)
    snapshot_digest: Mapped[str] = mapped_column(String(64))
    expected_rules: Mapped[dict[str, object]] = mapped_column(JSON)
    rules_digest: Mapped[str] = mapped_column(String(64))
    repetition_count: Mapped[int] = mapped_column(Integer)
    input_approval: Mapped[dict[str, object] | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    claim_token: Mapped[UUID | None] = mapped_column()
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    runtime_environment: Mapped[dict[str, object] | None] = mapped_column(JSON)


class GenerativeAttemptRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rag_generative_attempts"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "configuration_version_id",
            "case_id",
            "repetition",
            "attempt_number",
        ),
    )

    run_id: Mapped[UUID] = mapped_column(ForeignKey("rag_generative_runs.id", ondelete="CASCADE"))
    configuration_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_configuration_versions.id", ondelete="RESTRICT"),
    )
    case_id: Mapped[UUID] = mapped_column()
    repetition: Mapped[int] = mapped_column(Integer)
    attempt_number: Mapped[int] = mapped_column(Integer)
    execution_id: Mapped[UUID] = mapped_column(unique=True)
    claim_token: Mapped[UUID | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(32), default="pending")
    result: Mapped[dict[str, object] | None] = mapped_column(JSON)
    result_bytes: Mapped[bytes | None] = mapped_column(LargeBinary)
    result_digest: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(100))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GenerativeJudgmentRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rag_generative_judgments"

    attempt_id: Mapped[UUID] = mapped_column(ForeignKey("rag_generative_attempts.id"))
    reviewer_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    result_digest: Mapped[str] = mapped_column(String(64))
    rule_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str] = mapped_column(String(1000))
