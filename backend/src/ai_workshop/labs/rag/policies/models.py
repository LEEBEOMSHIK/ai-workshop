from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from ai_workshop.shared.models import Base, TimestampMixin, UUIDPrimaryKeyMixin


class InstallationDataPolicyRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rag_installation_data_policies"

    singleton_key: Mapped[bool] = mapped_column(Boolean, nullable=False, unique=True)


class InstallationDataPolicyVersionRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rag_installation_data_policy_versions"
    __table_args__ = (
        UniqueConstraint("policy_id", "version"),
        CheckConstraint("version > 0", name="ck_rag_installation_policy_versions_positive"),
        CheckConstraint(
            "outbound_mode IN ('deny', 'approved_providers')",
            name="ck_rag_installation_policy_versions_mode",
        ),
    )

    policy_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_installation_data_policies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    outbound_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    approved_providers: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    changed_by: Mapped[UUID] = mapped_column(Uuid, nullable=False)


class WorkspaceDataPolicyRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rag_workspace_data_policies"
    __table_args__ = (UniqueConstraint("id", "workspace_id"),)

    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False, unique=True
    )


class WorkspaceDataPolicyVersionRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rag_workspace_data_policy_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["policy_id", "workspace_id"],
            ["rag_workspace_data_policies.id", "rag_workspace_data_policies.workspace_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("policy_id", "version"),
        UniqueConstraint("id", "workspace_id"),
        Index(
            "ix_rag_workspace_policy_versions_workspace_version",
            "workspace_id",
            "version",
        ),
        CheckConstraint("version > 0", name="ck_rag_workspace_policy_versions_positive"),
        CheckConstraint(
            "outbound_mode IN ('inherit', 'deny', 'approved_providers')",
            name="ck_rag_workspace_policy_versions_mode",
        ),
    )

    policy_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    outbound_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    approved_providers: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    changed_by: Mapped[UUID] = mapped_column(Uuid, nullable=False)
