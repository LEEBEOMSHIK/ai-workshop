from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ai_workshop.shared.models import Base, TimestampMixin, UUIDPrimaryKeyMixin


class IssueCategory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "issue_categories"
    __table_args__ = (
        UniqueConstraint("code", name="uq_issue_categories_code"),
        PrimaryKeyConstraint("id", name="pk_issue_categories"),
        CheckConstraint("revision > 0", name="ck_issue_categories_1"),
    )
    code: Mapped[str] = mapped_column(String(100), unique=False)
    name: Mapped[str] = mapped_column(String(200))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)


class Issue(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "issues"
    __table_args__ = (
        UniqueConstraint("issue_key", name="uq_issues_issue_key"),
        PrimaryKeyConstraint("id", name="pk_issues"),
        CheckConstraint("revision > 0", name="ck_issues_1"),
        CheckConstraint("status IN ('open','implemented','verified')", name="ck_issues_2"),
        Index("ix_issues_updated_id", "updated_at", "id"),
    )
    issue_key: Mapped[str] = mapped_column(String(100), unique=False)
    category_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("issue_categories.id", ondelete="RESTRICT", name="fk_issues_issue_categories"),
    )
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20))
    symptom: Mapped[str] = mapped_column(Text, default="")
    cause: Mapped[str] = mapped_column(Text, default="")
    resolution: Mapped[str] = mapped_column(Text, default="")
    verification: Mapped[list[str]] = mapped_column(JSONB, default=list)
    remaining: Mapped[list[str]] = mapped_column(JSONB, default=list)
    commits: Mapped[list[str]] = mapped_column(JSONB, default=list)
    revision: Mapped[int] = mapped_column(Integer, default=1)


class IssueEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "issue_events"
    __table_args__ = (PrimaryKeyConstraint("id", name="pk_issue_events"),)
    issue_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("issues.id", ondelete="RESTRICT", name="fk_issue_events_issues"),
        index=True,
    )
    event_date: Mapped[date] = mapped_column(Date)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    actor_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT", name="fk_issue_events_users")
    )
    kind: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(Text)
    before_revision: Mapped[int | None] = mapped_column(Integer)
    after_revision: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)


class IssueDocument(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "issue_documents"
    __table_args__ = (
        UniqueConstraint("import_source_key", name="uq_issue_documents_import_source_key"),
        PrimaryKeyConstraint("id", name="pk_issue_documents"),
        CheckConstraint("revision > 0 AND current_version > 0", name="ck_issue_documents_1"),
        ForeignKeyConstraint(
            ["id", "current_version"],
            ["issue_document_versions.document_id", "issue_document_versions.version"],
            name="fk_issue_document_current_version",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
    )
    title: Mapped[str] = mapped_column(String(200))
    import_source_key: Mapped[str | None] = mapped_column(String(2000), unique=False)
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    revision: Mapped[int] = mapped_column(Integer, default=1)


class IssueDocumentVersion(Base):
    __tablename__ = "issue_document_versions"
    __table_args__ = (
        PrimaryKeyConstraint("document_id", "version", name="pk_issue_document_versions"),
        CheckConstraint("version > 0", name="ck_issue_document_versions_1"),
        CheckConstraint("octet_length(content) <= 524288", name="ck_issue_document_versions_2"),
        UniqueConstraint("document_id", "sha256", name="uq_issue_document_versions_content"),
    )
    document_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "issue_documents.id",
            ondelete="RESTRICT",
            name="fk_issue_document_versions_issue_documents",
        ),
        primary_key=True,
    )
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    content: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    source_path: Mapped[str | None] = mapped_column(String(2000))
    source_commit: Mapped[str | None] = mapped_column(String(200))
    actor_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT", name="fk_issue_document_versions_users")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class IssueDocumentLink(Base):
    __tablename__ = "issue_document_links"
    __table_args__ = (
        PrimaryKeyConstraint("issue_id", "document_id", "version", name="pk_issue_document_links"),
        ForeignKeyConstraint(
            ["document_id", "version"],
            ["issue_document_versions.document_id", "issue_document_versions.version"],
            name="fk_issue_document_links_version",
            ondelete="RESTRICT",
        ),
    )
    issue_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("issues.id", ondelete="RESTRICT", name="fk_issue_document_links_issues"),
        primary_key=True,
    )
    document_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    sort_order: Mapped[int] = mapped_column(Integer)


class IssueImportRun(Base):
    __tablename__ = "issue_import_runs"
    __table_args__ = (PrimaryKeyConstraint("source_key", name="pk_issue_import_runs"),)
    source_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    manifest_hash: Mapped[str] = mapped_column(String(64))
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    actor_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT", name="fk_issue_import_runs_users")
    )
    summary: Mapped[dict[str, object]] = mapped_column(JSONB)


class IssueCommand(Base):
    __tablename__ = "issue_commands"
    __table_args__ = (
        PrimaryKeyConstraint("actor_id", "operation", "request_id", name="pk_issue_commands"),
    )
    actor_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_issue_commands_users"),
        primary_key=True,
    )
    operation: Mapped[str] = mapped_column(String(200), primary_key=True)
    request_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict[str, object]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
