from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ai_workshop.shared.models import Base, TimestampMixin, UUIDPrimaryKeyMixin


class RagConfigurationRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rag_configurations"
    __table_args__ = (
        UniqueConstraint("owner_id", "name"),
        CheckConstraint(
            "(is_system AND owner_id IS NULL) OR "
            "(NOT is_system AND owner_id IS NOT NULL)",
            name="ck_rag_configurations_system_owner",
        ),
        Index(
            "uq_rag_configurations_system_name",
            "name",
            unique=True,
            postgresql_where=text("is_system"),
        ),
    )

    owner_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class AnswerPolicyVersionRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rag_answer_policy_versions"
    __table_args__ = (
        UniqueConstraint("configuration_id", "version"),
        UniqueConstraint("configuration_id", "id"),
        CheckConstraint("version > 0", name="ck_rag_answer_policy_versions_positive"),
        CheckConstraint("mode = 'extractive'", name="ck_rag_answer_policy_versions_mode"),
        CheckConstraint(
            "min_semantic_score >= 0 AND min_semantic_score <= 1",
            name="ck_rag_answer_policy_versions_semantic_score",
        ),
        CheckConstraint(
            "min_keyword_coverage >= 0 AND min_keyword_coverage <= 1",
            name="ck_rag_answer_policy_versions_keyword_coverage",
        ),
        CheckConstraint(
            "require_complete_provenance",
            name="ck_rag_answer_policy_versions_provenance",
        ),
        CheckConstraint(
            "conflict_mode = 'separate_sources'",
            name="ck_rag_answer_policy_versions_conflict_mode",
        ),
    )

    configuration_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_configurations.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    min_semantic_score: Mapped[float] = mapped_column(Float, nullable=False)
    min_keyword_coverage: Mapped[float] = mapped_column(Float, nullable=False)
    require_complete_provenance: Mapped[bool] = mapped_column(Boolean, nullable=False)
    conflict_mode: Mapped[str] = mapped_column(String(32), nullable=False)


class RagConfigurationVersionRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rag_configuration_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["configuration_id", "answer_policy_version_id"],
            [
                "rag_answer_policy_versions.configuration_id",
                "rag_answer_policy_versions.id",
            ],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("configuration_id", "version"),
        CheckConstraint("version > 0", name="ck_rag_configuration_versions_positive"),
        CheckConstraint(
            "generation_profile_id IS NULL",
            name="ck_rag_configuration_versions_no_generation_v1",
        ),
        CheckConstraint(
            "evaluation_state IN ('draft', 'pending', 'passed', 'failed')",
            name="ck_rag_configuration_versions_evaluation_state",
        ),
        CheckConstraint(
            "NOT is_default OR evaluation_state = 'passed'",
            name="ck_rag_configuration_versions_default_passed",
        ),
        Index(
            "uq_rag_configuration_versions_passed_default",
            "is_default",
            unique=True,
            postgresql_where=text("is_default AND evaluation_state = 'passed'"),
        ),
    )

    configuration_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_configurations.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    indexing_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    retrieval_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    generation_profile_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("rag_profiles.id", ondelete="RESTRICT"), nullable=True
    )
    answer_policy_version_id: Mapped[UUID] = mapped_column(nullable=False)
    evaluation_state: Mapped[str] = mapped_column(String(32), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class RagConfigurationWorkspaceSubscriptionRecord(
    UUIDPrimaryKeyMixin, TimestampMixin, Base
):
    __tablename__ = "rag_configuration_workspace_subscriptions"
    __table_args__ = (UniqueConstraint("configuration_version_id", "workspace_id"),)

    configuration_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_configuration_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
