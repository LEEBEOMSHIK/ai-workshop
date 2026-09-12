from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ai_workshop.shared.models import Base


class LearningRecordRow(Base):
    __tablename__ = "learning_records"
    __table_args__ = (
        CheckConstraint(
            "current_revision > 0",
            name="ck_learning_records_current_revision_positive",
        ),
        CheckConstraint(
            "kind IN ('note', 'experiment')",
            name="ck_learning_records_kind",
        ),
        ForeignKeyConstraint(
            ["id", "current_revision"],
            ["learning_record_revisions.record_id", "learning_record_revisions.revision"],
            name="fk_learning_records_current_revision",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
            ondelete="RESTRICT",
        ),
        Index("ix_learning_records_owner_updated_id", "owner_id", "updated_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    topic_keys: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False)
    current_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LearningRecordRevisionRow(Base):
    __tablename__ = "learning_record_revisions"
    __table_args__ = (
        CheckConstraint(
            "revision > 0",
            name="ck_learning_record_revisions_revision_positive",
        ),
    )

    record_id: Mapped[UUID] = mapped_column(
        ForeignKey("learning_records.id", ondelete="RESTRICT"), primary_key=True
    )
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
