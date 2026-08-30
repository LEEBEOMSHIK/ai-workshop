import os
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ai_workshop.labs.rag.documents.domain import (
    EvidenceUnit,
    ParsedDocument,
    RagProjection,
    RetrievalChunk,
    SourceLocation,
    StructuralElement,
)
from ai_workshop.labs.rag.documents.models import (
    EvidenceUnitRecord,
    RetrievalChunkRecord,
    StructuralElementRecord,
)
from ai_workshop.labs.rag.documents.repository import SqlAlchemyRagDocumentRepository
from ai_workshop.labs.rag.models.models import ProfileRecord
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.platform.workspaces.models import WorkspaceRecord

TEST_DATABASE_URL = os.environ.get(
    "AI_WORKSHOP_TEST_DATABASE_URL",
    "postgresql+psycopg://ai_workshop:ai_workshop@127.0.0.1:5432/ai_workshop",
)


@pytest.mark.asyncio
async def test_repository_preserves_document_provenance_exactly() -> None:
    engine = create_async_engine(TEST_DATABASE_URL)
    owner_id = UUID("10000000-0000-0000-0000-000000000001")
    workspace_id = UUID("10000000-0000-0000-0000-000000000002")
    document_id = UUID("10000000-0000-0000-0000-000000000003")
    asset_version_id = UUID("10000000-0000-0000-0000-000000000004")
    profile_id = UUID("10000000-0000-0000-0000-000000000005")
    element_id = UUID("10000000-0000-0000-0000-000000000006")
    projection = RagProjection.pending(
        asset_version_id=asset_version_id,
        indexing_profile_id=profile_id,
    )
    location = SourceLocation(
        element_id=element_id,
        page=4,
        char_start=21,
        char_end=48,
        bbox=(12.5, 18.25, 300.75, 41.5),
    )
    element = StructuralElement(
        id=element_id,
        ordinal=0,
        kind="paragraph",
        text="Synthetic public fixture text.",
        section_path=("Part I", "Scope"),
        location=location,
        parser_name="fixture-parser",
        parser_version="1.0",
        confidence=0.99,
    )
    chunk_id = UUID("10000000-0000-0000-0000-000000000007")
    first_evidence_id = UUID("10000000-0000-0000-0000-000000000008")
    second_evidence_id = UUID("10000000-0000-0000-0000-000000000009")
    chunk = RetrievalChunk(
        id=chunk_id,
        projection_id=projection.id,
        ordinal=0,
        text="Synthetic public fixture text.",
        section_path=("Part I", "Scope"),
        evidence_units=(
            EvidenceUnit(first_evidence_id, chunk_id, 0, "Synthetic", location),
            EvidenceUnit(second_evidence_id, chunk_id, 1, "fixture text.", location),
        ),
    )

    async with engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(bind=connection, expire_on_commit=False) as session:
            session.add(
                UserRecord(
                    id=owner_id,
                    display_name="Fixture Owner",
                    email="fixture-owner@example.test",
                    normalized_email="fixture-owner@example.test",
                    password_hash="fixture-password-hash",
                    role="owner",
                    is_active=True,
                )
            )
            await session.flush()
            session.add(
                WorkspaceRecord(
                    id=workspace_id,
                    name="Fixture Workspace",
                    kind="personal",
                    created_by=owner_id,
                    expires_at=None,
                )
            )
            await session.flush()
            session.add_all(
                [
                    DocumentRecord(
                        id=document_id,
                        workspace_id=workspace_id,
                        folder_id=None,
                        name="fixture.txt",
                        active_version_id=None,
                    ),
                    ProfileRecord(
                        id=profile_id,
                        kind="indexing",
                        name="fixture-indexing",
                        version=1,
                        config={"chunker": {"name": "fixture"}},
                        evaluation_state="draft",
                        is_default=False,
                    ),
                ]
            )
            await session.flush()
            session.add(
                AssetVersionRecord(
                    id=asset_version_id,
                    document_id=document_id,
                    number=1,
                    object_key="fixtures/public/fixture.txt",
                    sha256="a" * 64,
                    media_type="text/plain",
                    size=30,
                    status="stored",
                )
            )
            await session.flush()
            repository = SqlAlchemyRagDocumentRepository(session)

            await repository.add_projection(projection)
            await repository.save_parsed_document(
                projection.id,
                ParsedDocument(
                    asset_version_id=asset_version_id,
                    parser_name="fixture-parser",
                    parser_version="1.0",
                    elements=(element,),
                ),
            )
            await repository.replace_chunks(projection.id, (chunk,))
            await session.flush()
            session.expire_all()

            reloaded_projection = await repository.find_projection(
                asset_version_id=asset_version_id,
                indexing_profile_id=profile_id,
            )
            reloaded_element = (
                await session.execute(
                    select(StructuralElementRecord).where(StructuralElementRecord.id == element_id)
                )
            ).scalar_one()
            reloaded_chunk = (
                await session.execute(
                    select(RetrievalChunkRecord).where(RetrievalChunkRecord.id == chunk_id)
                )
            ).scalar_one()
            reloaded_evidence = list(
                (
                    await session.execute(
                        select(EvidenceUnitRecord)
                        .where(EvidenceUnitRecord.retrieval_chunk_id == chunk_id)
                        .order_by(EvidenceUnitRecord.ordinal)
                    )
                ).scalars()
            )
        await transaction.rollback()

    await engine.dispose()

    assert reloaded_projection == projection
    assert reloaded_element.id == element_id
    assert reloaded_element.section_path == ["Part I", "Scope"]
    assert reloaded_element.char_start == 21
    assert reloaded_element.char_end == 48
    assert reloaded_element.bbox == [12.5, 18.25, 300.75, 41.5]
    assert reloaded_chunk.id == chunk_id
    assert reloaded_chunk.section_path == ["Part I", "Scope"]
    assert [item.id for item in reloaded_evidence] == [first_evidence_id, second_evidence_id]
    assert [(item.char_start, item.char_end) for item in reloaded_evidence] == [(21, 48), (21, 48)]
    assert [item.bbox for item in reloaded_evidence] == [
        [12.5, 18.25, 300.75, 41.5],
        [12.5, 18.25, 300.75, 41.5],
    ]
