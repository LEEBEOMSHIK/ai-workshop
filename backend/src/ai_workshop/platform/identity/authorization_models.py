from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ai_workshop.shared.models import Base


class AuthorizationStateRecord(Base):
    __tablename__ = "authorization_state"
    __table_args__ = (CheckConstraint("id = 1", name="ck_authorization_state_singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    initialized: Mapped[bool] = mapped_column(Boolean, nullable=False)


class UserAuthorizationStateRecord(Base):
    __tablename__ = "user_authorization_states"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_user_authorization_user"),
        CheckConstraint(
            "revision >= 0",
            name="ck_user_authorization_revision_nonnegative",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True
    )
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class TechnologyGrantRecord(Base):
    __tablename__ = "technology_grants"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "technology_key",
            name="uq_technology_grant_user_key",
        ),
        CheckConstraint(
            "can_view OR (NOT can_configure AND NOT can_execute)",
            name="ck_technology_grant_view_prerequisite",
        ),
        CheckConstraint("can_view", name="ck_technology_grant_nonempty"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True
    )
    technology_key: Mapped[str] = mapped_column(String(80), primary_key=True)
    can_view: Mapped[bool] = mapped_column(Boolean, nullable=False)
    can_configure: Mapped[bool] = mapped_column(Boolean, nullable=False)
    can_execute: Mapped[bool] = mapped_column(Boolean, nullable=False)


class AuthorityAuditRecord(Base):
    __tablename__ = "authority_audit"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    actor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    target_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    technology_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    before: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    after: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
