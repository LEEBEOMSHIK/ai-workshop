from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ai_workshop.labs.rag.documents.domain import ProjectionStatus
from ai_workshop.shared.models import Base, TimestampMixin, UUIDPrimaryKeyMixin


class RagProjectionRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rag_document_projections"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'parsing', 'chunking', 'embedding', 'indexing', "
            "'ready', 'failed', 'partial_ready')",
            name="ck_rag_document_projections_status",
        ),
        UniqueConstraint("asset_version_id", "indexing_profile_id"),
    )

    asset_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("asset_versions.id", ondelete="CASCADE"), nullable=False
    )
    indexing_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[ProjectionStatus] = mapped_column(String(32), nullable=False)


class StructuralElementRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rag_structural_elements"
    __table_args__ = (
        UniqueConstraint("projection_id", "ordinal"),
        UniqueConstraint("projection_id", "id"),
    )

    projection_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_document_projections.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    section_path: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    page: Mapped[int | None] = mapped_column(Integer)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    bbox: Mapped[list[float] | None] = mapped_column(JSON)
    parser_name: Mapped[str] = mapped_column(String(180), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(180), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)


class RetrievalChunkRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rag_retrieval_chunks"
    __table_args__ = (
        UniqueConstraint("projection_id", "ordinal"),
        UniqueConstraint("projection_id", "id"),
    )

    projection_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_document_projections.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    section_path: Mapped[list[str]] = mapped_column(JSON, nullable=False)


class EvidenceUnitRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rag_evidence_units"
    __table_args__ = (
        ForeignKeyConstraint(
            ["projection_id", "retrieval_chunk_id"],
            ["rag_retrieval_chunks.projection_id", "rag_retrieval_chunks.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["projection_id", "element_id"],
            ["rag_structural_elements.projection_id", "rag_structural_elements.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("retrieval_chunk_id", "ordinal"),
    )

    projection_id: Mapped[UUID] = mapped_column(nullable=False)
    retrieval_chunk_id: Mapped[UUID] = mapped_column(nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    element_id: Mapped[UUID] = mapped_column(nullable=False)
    page: Mapped[int | None] = mapped_column(Integer)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    bbox: Mapped[list[float] | None] = mapped_column(JSON)


class RagIndexBuildRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rag_index_builds"
    __table_args__ = (
        UniqueConstraint("projection_id"),
        UniqueConstraint("index_name"),
    )

    projection_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_document_projections.id", ondelete="CASCADE"), nullable=False
    )
    indexing_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    index_name: Mapped[str | None] = mapped_column(String(700))
    expected_document_count: Mapped[int | None] = mapped_column(Integer)
    indexed_document_count: Mapped[int | None] = mapped_column(Integer)
    vector_dimension: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str | None] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
