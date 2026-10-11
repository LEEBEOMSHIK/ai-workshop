from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ai_workshop.shared.models import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ConversationRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rag_conversations"
    __table_args__ = (
        CheckConstraint("title_origin IN ('auto','manual','legacy')", name="ck_rag_title_origin"),
        CheckConstraint(
            "title_derivation IN ('extracted','preserved','fallback')",
            name="ck_rag_title_derivation",
        ),
        CheckConstraint("legacy_state IN ('active','draft_pending')", name="ck_rag_legacy_state"),
        CheckConstraint("revision >= 1", name="ck_rag_conversation_revision"),
        Index("ix_rag_conversations_owner_domain_updated", "owner_id", "domain_id", "updated_at"),
    )
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    domain_id: Mapped[UUID] = mapped_column(ForeignKey("rag_domains.id", ondelete="RESTRICT"))
    title: Mapped[str] = mapped_column(String(180))
    revision: Mapped[int] = mapped_column(Integer)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    title_origin: Mapped[str] = mapped_column(String(12), server_default="legacy")
    title_source_turn_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("rag_conversation_turns.id", ondelete="RESTRICT", use_alter=True)
    )
    title_derivation: Mapped[str | None] = mapped_column(String(12))
    title_policy_version: Mapped[str | None] = mapped_column(String(64))
    title_error_code: Mapped[str | None] = mapped_column(String(80))
    legacy_state: Mapped[str] = mapped_column(String(24), server_default="active")


class ConversationTurnRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rag_conversation_turns"
    __table_args__ = (
        UniqueConstraint("conversation_id", "request_id", name="uq_rag_turn_request"),
        UniqueConstraint("conversation_id", "sequence", name="uq_rag_turn_sequence"),
        CheckConstraint("sequence >= 1 AND segment >= 1", name="ck_rag_turn_sequence"),
        CheckConstraint(
            "status IN ('running','completed','failed','cancelled','interrupted')",
            name="ck_rag_turn_status",
        ),
    )
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_conversations.id", ondelete="RESTRICT")
    )
    request_id: Mapped[UUID] = mapped_column(Uuid)
    sequence: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    query: Mapped[str] = mapped_column(Text)
    request: Mapped[dict[str, object]] = mapped_column(JSONB)
    request_digest: Mapped[str] = mapped_column(String(64))
    scope_identity: Mapped[str] = mapped_column(String(64))
    segment: Mapped[int] = mapped_column(Integer)
    response: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True))
    error_code: Mapped[str | None] = mapped_column(String(100))
    dependencies: Mapped[list[str]] = mapped_column(JSONB)
    execution_terminated: Mapped[bool]


class ConversationStartRecord(Base):
    __tablename__ = "rag_conversation_starts"
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True
    )
    domain_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_domains.id", ondelete="RESTRICT"), primary_key=True
    )
    request_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    request_digest: Mapped[str] = mapped_column(String(64))
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_conversations.id", ondelete="RESTRICT"), unique=True
    )
    first_turn_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_conversation_turns.id", ondelete="RESTRICT"), unique=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AttachmentDraftRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rag_attachment_drafts"
    __table_args__ = (
        UniqueConstraint("owner_id", "domain_id", "create_request_id", name="uq_rag_draft_create"),
        UniqueConstraint("legacy_conversation_id", name="uq_rag_draft_legacy"),
        CheckConstraint(
            "state IN ('open','bound','abandoned','expired')", name="ck_rag_draft_state"
        ),
        CheckConstraint("revision >= 1", name="ck_rag_draft_revision"),
        CheckConstraint(
            "(state = 'bound') = (bound_conversation_id IS NOT NULL)", name="ck_rag_draft_bound"
        ),
        Index("ix_rag_draft_open_expiry", "state", "expires_at"),
    )
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    domain_id: Mapped[UUID] = mapped_column(ForeignKey("rag_domains.id", ondelete="RESTRICT"))
    state: Mapped[str] = mapped_column(String(12))
    revision: Mapped[int] = mapped_column(Integer)
    create_request_id: Mapped[UUID] = mapped_column(Uuid)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    bound_conversation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("rag_conversations.id", ondelete="RESTRICT"), unique=True
    )
    legacy_conversation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("rag_conversations.id", ondelete="RESTRICT")
    )
    start_request_id: Mapped[UUID | None] = mapped_column(Uuid)
    start_request_digest: Mapped[str | None] = mapped_column(String(64))
