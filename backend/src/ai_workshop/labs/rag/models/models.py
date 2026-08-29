from uuid import UUID

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ai_workshop.shared.models import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ModelDefinitionRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rag_model_definitions"
    __table_args__ = (UniqueConstraint("kind", "name", "version"),)

    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    config: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)


class ProfileRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rag_profiles"
    __table_args__ = (
        UniqueConstraint("kind", "name", "version"),
        Index(
            "uq_rag_profiles_default_kind",
            "kind",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )

    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    config: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    evaluation_state: Mapped[str] = mapped_column(String(32), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    bindings: Mapped[list["ProfileModelBindingRecord"]] = relationship(
        back_populates="profile",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class ProfileModelBindingRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rag_profile_model_bindings"
    __table_args__ = (UniqueConstraint("profile_id", "role", "model_id"),)

    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_profiles.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    model_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_model_definitions.id", ondelete="RESTRICT"), nullable=False
    )
    profile: Mapped[ProfileRecord] = relationship(back_populates="bindings")
