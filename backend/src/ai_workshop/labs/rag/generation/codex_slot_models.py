"""Every retained row represents possibly live processes; age is never evidence."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from ai_workshop.shared.models import Base


class CodexExecutionSlotRecord(Base):
    __tablename__ = "rag_codex_execution_slots"
    __table_args__ = (
        CheckConstraint("configuration_sha256 ~ '^[0-9a-f]{64}$'", name="ck_codex_slot_digest"),
        CheckConstraint("max_concurrent BETWEEN 1 AND 64", name="ck_codex_slot_capacity"),
        CheckConstraint(
            "runner_ref ~ '^[a-z][a-z0-9]*-[a-z0-9]+(-[a-z0-9]+)*$'",
            name="ck_codex_slot_reference",
        ),
        Index("ix_codex_execution_slots_runner_ref", "runner_ref"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    request_id: Mapped[UUID] = mapped_column(Uuid)
    runner_ref: Mapped[str] = mapped_column(String(120))
    configuration_sha256: Mapped[str] = mapped_column(String(64))
    max_concurrent: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
