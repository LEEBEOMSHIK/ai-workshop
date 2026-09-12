from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from ai_workshop.shared.models import Base, TimestampMixin, UUIDPrimaryKeyMixin


class RagDomainRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rag_domains"
    __table_args__ = (
        CheckConstraint(
            "slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'",
            name="ck_rag_domains_slug",
        ),
        UniqueConstraint("slug", name="uq_rag_domains_slug"),
        ForeignKeyConstraint(
            ["active_connection_version_id", "id"],
            ["rag_domain_connection_versions.id", "rag_domain_connection_versions.domain_id"],
            name="fk_rag_domains_active_connection",
            ondelete="RESTRICT",
        ),
    )

    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    display_name: Mapped[str] = mapped_column(String(180), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False)
    active_connection_version_id: Mapped[UUID | None] = mapped_column(
        Uuid, nullable=True
    )
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )


class RagDomainConnectionVersionRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rag_domain_connection_versions"
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_rag_domain_connections_positive"),
        UniqueConstraint(
            "domain_id",
            "version",
            name="uq_rag_domain_connection_versions_domain_version",
        ),
        UniqueConstraint(
            "id",
            "domain_id",
            name="uq_rag_domain_connection_versions_id_domain",
        ),
        UniqueConstraint(
            "id",
            "configuration_version_id",
            name="uq_rag_domain_connection_versions_id_configuration",
        ),
    )

    domain_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_domains.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    configuration_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_configuration_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )


class RagDomainConnectionWorkspaceRecord(Base):
    __tablename__ = "rag_domain_connection_workspaces"
    __table_args__ = (
        ForeignKeyConstraint(
            ["connection_version_id", "configuration_version_id"],
            [
                "rag_domain_connection_versions.id",
                "rag_domain_connection_versions.configuration_version_id",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["configuration_version_id", "workspace_id"],
            [
                "rag_configuration_workspace_subscriptions.configuration_version_id",
                "rag_configuration_workspace_subscriptions.workspace_id",
            ],
            ondelete="RESTRICT",
        ),
    )

    connection_version_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    configuration_version_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)


class RagDomainConnectionScopeSealRecord(Base):
    __tablename__ = "rag_domain_connection_scope_seals"

    connection_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_domain_connection_versions.id", ondelete="RESTRICT"),
        primary_key=True,
    )
