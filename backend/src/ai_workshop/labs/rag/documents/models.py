from uuid import UUID

from sqlalchemy import JSON, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ai_workshop.labs.rag.documents.domain import ProjectionStatus
from ai_workshop.shared.models import Base, TimestampMixin, UUIDPrimaryKeyMixin


class RagProjectionRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rag_document_projections"
    __table_args__ = (UniqueConstraint("asset_version_id", "indexing_profile_id"),)

    asset_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("asset_versions.id", ondelete="CASCADE"), nullable=False
    )
    indexing_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[ProjectionStatus] = mapped_column(String(32), nullable=False)


class StructuralElementRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rag_structural_elements"
    __table_args__ = (UniqueConstraint("projection_id", "ordinal"),)

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
    __table_args__ = (UniqueConstraint("projection_id", "ordinal"),)

    projection_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_document_projections.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    section_path: Mapped[list[str]] = mapped_column(JSON, nullable=False)


class EvidenceUnitRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rag_evidence_units"
    __table_args__ = (UniqueConstraint("retrieval_chunk_id", "ordinal"),)

    retrieval_chunk_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_retrieval_chunks.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    element_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_structural_elements.id", ondelete="CASCADE"), nullable=False
    )
    page: Mapped[int | None] = mapped_column(Integer)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    bbox: Mapped[list[float] | None] = mapped_column(JSON)


class RagIndexBuildRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rag_index_builds"

    projection_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag_document_projections.id", ondelete="CASCADE"), nullable=False
    )
