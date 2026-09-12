from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ai_workshop.shared.models import Base


class PublishingStudyRow(Base):
    __tablename__ = "publishing_studies"
    __table_args__ = (
        CheckConstraint(
            "current_revision > 0",
            name="ck_publishing_studies_current_revision_positive",
        ),
        CheckConstraint(
            "sequence >= 0",
            name="ck_publishing_studies_sequence_nonnegative",
        ),
        CheckConstraint(
            "applied_sequence >= 0 AND applied_sequence <= sequence",
            name="ck_publishing_studies_applied_sequence",
        ),
        CheckConstraint(
            "(applied_sequence = 0 AND applied_action IS NULL AND applied_revision IS NULL) "
            "OR (applied_sequence > 0 AND ((applied_action = 'publish' AND "
            "applied_revision IS NOT NULL AND applied_revision > 0) OR "
            "(applied_action = 'withdraw' AND applied_revision IS NULL)))",
            name="ck_publishing_studies_applied_state",
        ),
        ForeignKeyConstraint(
            ["slug", "current_revision"],
            ["publishing_revisions.slug", "publishing_revisions.revision"],
            name="fk_publishing_studies_current_revision",
            deferrable=True,
            initially="DEFERRED",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        Index("ix_publishing_studies_updated_slug", "updated_at", "slug"),
        PrimaryKeyConstraint("slug", name="pk_publishing_studies"),
    )

    slug: Mapped[str] = mapped_column(String(200), primary_key=True)
    current_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    approved_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    applied_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    applied_action: Mapped[str | None] = mapped_column(String(16), nullable=True)
    applied_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PublishingRevisionRow(Base):
    __tablename__ = "publishing_revisions"
    __table_args__ = (
        CheckConstraint(
            "revision > 0",
            name="ck_publishing_revisions_revision_positive",
        ),
        ForeignKeyConstraint(
            ["slug"],
            ["publishing_studies.slug"],
            name="fk_publishing_revisions_study",
            ondelete="RESTRICT",
        ),
        PrimaryKeyConstraint("slug", "revision", name="pk_publishing_revisions"),
    )

    slug: Mapped[str] = mapped_column(String(200), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    canonical_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PublishingCommandRow(Base):
    __tablename__ = "publishing_commands"
    __table_args__ = (
        CheckConstraint(
            "sequence > 0",
            name="ck_publishing_commands_sequence_positive",
        ),
        CheckConstraint(
            "expected_revision > 0",
            name="ck_publishing_commands_expected_revision_positive",
        ),
        CheckConstraint(
            "(action = 'publish' AND export_payload IS NOT NULL) OR "
            "(action = 'withdraw' AND export_payload IS NULL)",
            name="ck_publishing_commands_action_payload",
        ),
        CheckConstraint(
            "(applied_at IS NULL AND receipt_slug IS NULL AND receipt_sequence IS NULL "
            "AND receipt_request_id IS NULL AND receipt_action IS NULL) OR "
            "(applied_at IS NOT NULL AND receipt_slug = slug AND receipt_sequence = sequence "
            "AND receipt_request_id = request_id AND receipt_action = action)",
            name="ck_publishing_commands_receipt_state",
        ),
        ForeignKeyConstraint(
            ["slug"],
            ["publishing_studies.slug"],
            name="fk_publishing_commands_study",
            ondelete="RESTRICT",
        ),
        Index("ix_publishing_commands_pending", "applied_at", "created_at"),
        PrimaryKeyConstraint("request_id", name="pk_publishing_commands"),
        UniqueConstraint(
            "slug",
            "sequence",
            name="uq_publishing_commands_slug_sequence",
        ),
    )

    request_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    expected_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    export_payload: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    receipt_slug: Mapped[str | None] = mapped_column(String(200), nullable=True)
    receipt_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    receipt_request_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    receipt_action: Mapped[str | None] = mapped_column(String(16), nullable=True)
    delivery_error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
