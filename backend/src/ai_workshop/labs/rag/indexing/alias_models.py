"""Independent journal: deliberately no FK to the caller's locked source rows."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ai_workshop.shared.models import Base


class AliasOperationRecord(Base):
    __tablename__ = "rag_alias_operations"
    __table_args__ = (
        CheckConstraint("store_id ~ '^[a-z][a-z0-9_]{0,79}$'", name="ck_rag_alias_store"),
        CheckConstraint("cluster_uuid ~ '^[A-Za-z0-9_-]{1,128}$'", name="ck_rag_alias_cluster"),
        CheckConstraint("alias ~ '^[a-z0-9][a-z0-9._-]{0,254}$'", name="ck_rag_alias_name"),
        CheckConstraint("jsonb_typeof(targets) = 'array'", name="ck_rag_alias_targets"),
        CheckConstraint(
            "(state = 'open' AND closed_at IS NULL AND result_code IS NULL) OR "
            "(state = 'closed' AND closed_at IS NOT NULL AND result_code IS NOT NULL "
            "AND result_code = 'confirmed')",
            name="ck_rag_alias_state",
        ),
        Index(
            "uq_rag_alias_open",
            "cluster_uuid",
            "alias",
            unique=True,
            postgresql_where=text("state = 'open'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    store_id: Mapped[str] = mapped_column(String(80))
    cluster_uuid: Mapped[str] = mapped_column(String(128))
    alias: Mapped[str] = mapped_column(String(255))
    indexing_profile_id: Mapped[UUID] = mapped_column()
    document_processing_profile_id: Mapped[UUID] = mapped_column()
    targets: Mapped[list[str]] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(String(16))
    result_code: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
