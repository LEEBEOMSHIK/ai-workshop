from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from ai_workshop.platform.assets import models as asset_models  # noqa: F401
from ai_workshop.shared.models import Base, UUIDPrimaryKeyMixin

_MACHINE_IDENTIFIER_SQL = r"^[a-z][a-z0-9_]{0,79}$"
_RELATION_KIND_CHECK = (
    "relation_kind IN ('source_copy','derived_artifact','authored_reference')"
)


class AssetSourceRelationRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "asset_source_relations"
    __table_args__ = (
        CheckConstraint(
            f"participant ~ '{_MACHINE_IDENTIFIER_SQL}'",
            name="ck_asset_source_relations_participant",
        ),
        CheckConstraint(
            f"kind ~ '{_MACHINE_IDENTIFIER_SQL}'",
            name="ck_asset_source_relations_kind",
        ),
        CheckConstraint(
            "resource_revision > 0",
            name="ck_asset_source_relations_resource_revision_positive",
        ),
        CheckConstraint(
            _RELATION_KIND_CHECK,
            name="ck_asset_source_relations_relation_kind",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "document_id"],
            ["documents.workspace_id", "documents.id"],
            name="fk_asset_source_relations_document",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["document_id", "asset_version_id"],
            ["asset_versions.document_id", "asset_versions.id"],
            name="fk_asset_source_relations_asset_version",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "workspace_id",
            "document_id",
            "asset_version_id",
            "participant",
            "kind",
            "resource_id",
            "resource_revision",
            "relation_kind",
            name="uq_asset_source_relations_source_resource_relation",
        ),
        Index(
            "ix_asset_source_relations_resource",
            "workspace_id",
            "participant",
            "kind",
            "resource_id",
            "resource_revision",
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    document_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    asset_version_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    participant: Mapped[str] = mapped_column(String(80), nullable=False)
    kind: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    resource_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    relation_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
