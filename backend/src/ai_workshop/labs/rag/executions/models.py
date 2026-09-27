from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ai_workshop.shared.models import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ExecutionRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rag_executions"
    __table_args__ = (
        UniqueConstraint("turn_id", name="uq_rag_execution_turn"),
        UniqueConstraint("evaluation_attempt_id", name="uq_rag_execution_attempt"),
        CheckConstraint(
            "(turn_id IS NULL) <> (evaluation_attempt_id IS NULL)", name="ck_rag_execution_parent"
        ),
        CheckConstraint(
            "status IN ('running','completed','failed','cancelled','interrupted')",
            name="ck_rag_execution_status",
        ),
        Index("ix_rag_executions_actor_created", "actor_id", "created_at"),
    )
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    turn_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("rag_conversation_turns.id", ondelete="RESTRICT")
    )
    evaluation_attempt_id: Mapped[UUID | None]
    status: Mapped[str] = mapped_column(String(20), default="running")
    answer_status: Mapped[str | None] = mapped_column(String(40))
    error_code: Mapped[str | None] = mapped_column(String(100))
    complete: Mapped[bool] = mapped_column(default=True)
    stages: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
