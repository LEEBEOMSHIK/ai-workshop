"""Planned identities survive rollback; actual source pins appear only at attachment."""

from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ai_workshop.platform.assets import upload_models as upload_models  # noqa: F401
from ai_workshop.shared.models import Base, TimestampMixin, UUIDPrimaryKeyMixin


class UploadIntakeRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "http_upload_intakes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "existing_document_id"],
            ["documents.workspace_id", "documents.id"],
            name="fk_intake_existing_document",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["original_attempt_id", "workspace_id", "document_id", "asset_version_id"],
            [
                "original_upload_attempts.id",
                "original_upload_attempts.workspace_id",
                "original_upload_attempts.document_id",
                "original_upload_attempts.asset_version_id",
            ],
            name="fk_intake_original_source",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "actual_document_id"],
            ["documents.workspace_id", "documents.id"],
            name="fk_intake_actual_document",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["actual_document_id", "actual_version_id"],
            ["asset_versions.document_id", "asset_versions.id"],
            name="fk_intake_actual_version",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["attached_original_id"],
            ["original_file_resources.id"],
            name="fk_intake_attached_original",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("original_attempt_id", name="uq_intake_original_attempt"),
        CheckConstraint("store_id ~ '^[a-z][a-z0-9_]{0,79}$'", name="ck_intake_store"),
        CheckConstraint(
            "(new_document AND generation IS NULL AND existing_document_id IS NULL) OR "
            "(NOT new_document AND generation IS NOT NULL AND generation >= 1 AND "
            "existing_document_id IS NOT NULL AND existing_document_id = document_id)",
            name="ck_intake_existing_source",
        ),
        CheckConstraint(
            "(NOT attached AND actual_document_id IS NULL AND actual_version_id IS NULL "
            "AND attached_original_id IS NULL) OR "
            "(attached AND original_attempt_id IS NOT NULL AND actual_document_id IS NOT NULL "
            "AND actual_version_id IS NOT NULL AND attached_original_id IS NOT NULL "
            "AND actual_document_id = document_id AND actual_version_id = asset_version_id "
            "AND attached_original_id = original_attempt_id)",
            name="ck_intake_attachment",
        ),
        CheckConstraint(
            "state IN ('open','closed','cleaning','cleaned') AND revision = "
            "CASE state WHEN 'open' THEN 1 WHEN 'closed' THEN 2 WHEN 'cleaning' THEN 3 "
            "WHEN 'cleaned' THEN 4 END + CASE WHEN original_attempt_id IS NULL THEN 0 ELSE 1 END "
            "+ CASE WHEN attached THEN 1 ELSE 0 END",
            name="ck_intake_state_revision",
        ),
        CheckConstraint(
            "error_code IS NULL OR error_code IN "
            "('writer_unconfirmed','cleanup_unconfirmed','ownership_failed')",
            name="ck_intake_error_code",
        ),
        Index("ix_intake_document", "workspace_id", "document_id"),
        Index("ix_intake_unattached", "workspace_id", "attached"),
    )
    workspace_id: Mapped[UUID]
    document_id: Mapped[UUID]
    asset_version_id: Mapped[UUID]
    user_id: Mapped[UUID]
    new_document: Mapped[bool]
    generation: Mapped[int | None] = mapped_column(BigInteger)
    existing_document_id: Mapped[UUID | None]
    original_attempt_id: Mapped[UUID | None]
    actual_document_id: Mapped[UUID | None]
    actual_version_id: Mapped[UUID | None]
    attached_original_id: Mapped[UUID | None]
    attached: Mapped[bool]
    store_id: Mapped[str] = mapped_column(String(80))
    binding_id: Mapped[UUID]
    state: Mapped[str] = mapped_column(String(16))
    revision: Mapped[int] = mapped_column(BigInteger)
    error_code: Mapped[str | None] = mapped_column(String(32))
