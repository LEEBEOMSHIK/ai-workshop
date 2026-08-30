import os
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ai_workshop.labs.rag.documents.domain import (
    EvidenceUnit,
    ParsedDocument,
    ProjectionStatus,
    RagProjection,
    RetrievalChunk,
    SourceLocation,
    StructuralElement,
)
from ai_workshop.labs.rag.documents.models import (
    EvidenceUnitRecord,
    RagProjectionRecord,
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


@dataclass(frozen=True, slots=True)
class ProjectionFixture:
    asset_version_id: UUID
    profile_id: UUID


async def seed_projection_dependencies(
    session: AsyncSession,
    *,
    label: str,
) -> ProjectionFixture:
    owner_id = uuid4()
    workspace_id = uuid4()
    document_id = uuid4()
    asset_version_id = uuid4()
    profile_id = uuid4()
    session.add(
        UserRecord(
            id=owner_id,
            display_name=f"Fixture Owner {label}",
            email=f"fixture-{owner_id}@example.test",
            normalized_email=f"fixture-{owner_id}@example.test",
            password_hash="fixture-password-hash",
            role="owner",
            is_active=True,
        )
    )
    await session.flush()
    session.add(
        WorkspaceRecord(
            id=workspace_id,
            name=f"Fixture Workspace {label}",
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
                name=f"fixture-{label}.txt",
                active_version_id=None,
            ),
            ProfileRecord(
                id=profile_id,
                kind="indexing",
                name=f"fixture-indexing-{profile_id}",
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
            object_key=f"fixtures/public/{label}.txt",
            sha256="a" * 64,
            media_type="text/plain",
            size=30,
            status="stored",
        )
    )
    await session.flush()
    return ProjectionFixture(asset_version_id=asset_version_id, profile_id=profile_id)


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
            EvidenceUnit(
                first_evidence_id,
                chunk_id,
                0,
                "Synthetic",
                location,
                projection.id,
            ),
            EvidenceUnit(
                second_evidence_id,
                chunk_id,
                1,
                "fixture text.",
                location,
                projection.id,
            ),
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
    assert reloaded_element.projection_id == projection.id
    assert reloaded_element.section_path == ["Part I", "Scope"]
    assert reloaded_element.page == 4
    assert reloaded_element.char_start == 21
    assert reloaded_element.char_end == 48
    assert reloaded_element.bbox == [12.5, 18.25, 300.75, 41.5]
    assert reloaded_chunk.id == chunk_id
    assert reloaded_chunk.projection_id == projection.id
    assert reloaded_chunk.section_path == ["Part I", "Scope"]
    assert [item.id for item in reloaded_evidence] == [first_evidence_id, second_evidence_id]
    assert [item.projection_id for item in reloaded_evidence] == [projection.id, projection.id]
    assert [item.retrieval_chunk_id for item in reloaded_evidence] == [chunk_id, chunk_id]
    assert [item.element_id for item in reloaded_evidence] == [element_id, element_id]
    assert [item.page for item in reloaded_evidence] == [4, 4]
    assert [(item.char_start, item.char_end) for item in reloaded_evidence] == [(21, 48), (21, 48)]
    assert [item.bbox for item in reloaded_evidence] == [
        [12.5, 18.25, 300.75, 41.5],
        [12.5, 18.25, 300.75, 41.5],
    ]


@pytest.mark.asyncio
async def test_repository_rejects_a_parsed_document_from_another_asset_version() -> None:
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(bind=connection, expire_on_commit=False) as session:
            first = await seed_projection_dependencies(session, label="first")
            second = await seed_projection_dependencies(session, label="second")
            projection = RagProjection.pending(
                asset_version_id=first.asset_version_id,
                indexing_profile_id=first.profile_id,
            )
            repository = SqlAlchemyRagDocumentRepository(session)
            await repository.add_projection(projection)

            with pytest.raises(ValueError, match="asset version"):
                await repository.save_parsed_document(
                    projection.id,
                    ParsedDocument(
                        asset_version_id=second.asset_version_id,
                        parser_name="fixture-parser",
                        parser_version="1.0",
                        elements=(),
                    ),
                )
        await transaction.rollback()
    await engine.dispose()


@pytest.mark.asyncio
async def test_repository_rejects_ready_projection_creation() -> None:
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(bind=connection, expire_on_commit=False) as session:
            fixture = await seed_projection_dependencies(session, label="ready")
            repository = SqlAlchemyRagDocumentRepository(session)
            ready_projection = RagProjection(
                id=uuid4(),
                asset_version_id=fixture.asset_version_id,
                indexing_profile_id=fixture.profile_id,
                status=ProjectionStatus.READY,
            )

            with pytest.raises(ValueError, match="pending"):
                await repository.add_projection(ready_projection)
        await transaction.rollback()
    await engine.dispose()


@pytest.mark.asyncio
async def test_database_rejects_an_evidence_element_from_another_projection() -> None:
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(bind=connection, expire_on_commit=False) as session:
            first = await seed_projection_dependencies(session, label="cross-first")
            second = await seed_projection_dependencies(session, label="cross-second")
            first_projection = RagProjection.pending(
                asset_version_id=first.asset_version_id,
                indexing_profile_id=first.profile_id,
            )
            second_projection = RagProjection.pending(
                asset_version_id=second.asset_version_id,
                indexing_profile_id=second.profile_id,
            )
            repository = SqlAlchemyRagDocumentRepository(session)
            await repository.add_projection(first_projection)
            await repository.add_projection(second_projection)
            first_element_id = uuid4()
            second_element_id = uuid4()
            await repository.save_parsed_document(
                first_projection.id,
                ParsedDocument(
                    first.asset_version_id,
                    "fixture-parser",
                    "1.0",
                    (
                        StructuralElement(
                            first_element_id,
                            0,
                            "paragraph",
                            "first fixture",
                            ("First",),
                            SourceLocation(first_element_id, 1, 0, 13, None),
                            "fixture-parser",
                            "1.0",
                            1.0,
                        ),
                    ),
                ),
            )
            await repository.save_parsed_document(
                second_projection.id,
                ParsedDocument(
                    second.asset_version_id,
                    "fixture-parser",
                    "1.0",
                    (
                        StructuralElement(
                            second_element_id,
                            0,
                            "paragraph",
                            "second fixture",
                            ("Second",),
                            SourceLocation(second_element_id, 2, 0, 14, None),
                            "fixture-parser",
                            "1.0",
                            1.0,
                        ),
                    ),
                ),
            )
            cross_chunk_id = uuid4()
            with pytest.raises(ValueError, match="containing projection"):
                await repository.replace_chunks(
                    first_projection.id,
                    (
                        RetrievalChunk(
                            cross_chunk_id,
                            first_projection.id,
                            0,
                            "second fixture",
                            ("Second",),
                            (
                                EvidenceUnit(
                                    uuid4(),
                                    cross_chunk_id,
                                    0,
                                    "second fixture",
                                    SourceLocation(second_element_id, 2, 0, 14, None),
                                    first_projection.id,
                                ),
                            ),
                        ),
                    ),
                )
            chunk_id = uuid4()
            session.add(
                RetrievalChunkRecord(
                    id=chunk_id,
                    projection_id=first_projection.id,
                    ordinal=0,
                    text="first fixture",
                    section_path=["First"],
                )
            )
            await session.flush()
            with pytest.raises(IntegrityError):
                async with session.begin_nested():
                    session.add(
                        EvidenceUnitRecord(
                            id=uuid4(),
                            projection_id=first_projection.id,
                            retrieval_chunk_id=chunk_id,
                            ordinal=0,
                            text="second fixture",
                            element_id=second_element_id,
                            page=2,
                            char_start=0,
                            char_end=14,
                            bbox=None,
                        )
                    )
                    await session.flush()
        await transaction.rollback()
    await engine.dispose()


@pytest.mark.asyncio
async def test_repository_validates_a_complete_replacement_before_deleting_chunks() -> None:
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(bind=connection, expire_on_commit=False) as session:
            fixture = await seed_projection_dependencies(session, label="replacement")
            projection = RagProjection.pending(
                asset_version_id=fixture.asset_version_id,
                indexing_profile_id=fixture.profile_id,
            )
            element_id = uuid4()
            repository = SqlAlchemyRagDocumentRepository(session)
            await repository.add_projection(projection)
            await repository.save_parsed_document(
                projection.id,
                ParsedDocument(
                    fixture.asset_version_id,
                    "fixture-parser",
                    "1.0",
                    (
                        StructuralElement(
                            element_id,
                            0,
                            "paragraph",
                            "fixture",
                            ("Scope",),
                            SourceLocation(element_id, 1, 0, 7, None),
                            "fixture-parser",
                            "1.0",
                            1.0,
                        ),
                    ),
                ),
            )
            old_chunk_id = uuid4()
            await repository.replace_chunks(
                projection.id,
                (
                    RetrievalChunk(
                        old_chunk_id,
                        projection.id,
                        0,
                        "fixture",
                        ("Scope",),
                        (
                            EvidenceUnit(
                                uuid4(),
                                old_chunk_id,
                                0,
                                "fixture",
                                SourceLocation(element_id, 1, 0, 7, None),
                                projection.id,
                            ),
                        ),
                    ),
                ),
            )
            invalid_projection_id = uuid4()
            invalid_chunk_id = uuid4()

            with pytest.raises(ValueError, match="projection"):
                await repository.replace_chunks(
                    projection.id,
                    (
                        RetrievalChunk(
                            invalid_chunk_id,
                            invalid_projection_id,
                            0,
                            "fixture",
                            ("Scope",),
                            (
                                EvidenceUnit(
                                    uuid4(),
                                    invalid_chunk_id,
                                    0,
                                    "fixture",
                                    SourceLocation(element_id, 1, 0, 7, None),
                                    invalid_projection_id,
                                ),
                            ),
                        ),
                    ),
                )

            persisted_chunk_ids = list(
                (
                    await session.execute(
                        select(RetrievalChunkRecord.id).where(
                            RetrievalChunkRecord.projection_id == projection.id
                        )
                    )
                ).scalars()
            )
        await transaction.rollback()
    await engine.dispose()

    assert persisted_chunk_ids == [old_chunk_id]


@pytest.mark.asyncio
async def test_repository_refuses_to_replace_elements_after_chunking() -> None:
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(bind=connection, expire_on_commit=False) as session:
            fixture = await seed_projection_dependencies(session, label="parsed-replacement")
            projection = RagProjection.pending(
                asset_version_id=fixture.asset_version_id,
                indexing_profile_id=fixture.profile_id,
            )
            element_id = uuid4()
            repository = SqlAlchemyRagDocumentRepository(session)
            await repository.add_projection(projection)
            document = ParsedDocument(
                fixture.asset_version_id,
                "fixture-parser",
                "1.0",
                (
                    StructuralElement(
                        element_id,
                        0,
                        "paragraph",
                        "fixture",
                        ("Scope",),
                        SourceLocation(element_id, 1, 0, 7, None),
                        "fixture-parser",
                        "1.0",
                        1.0,
                    ),
                ),
            )
            await repository.save_parsed_document(projection.id, document)
            chunk_id = uuid4()
            await repository.replace_chunks(
                projection.id,
                (
                    RetrievalChunk(
                        chunk_id,
                        projection.id,
                        0,
                        "fixture",
                        ("Scope",),
                        (
                            EvidenceUnit(
                                uuid4(),
                                chunk_id,
                                0,
                                "fixture",
                                SourceLocation(element_id, 1, 0, 7, None),
                                projection.id,
                            ),
                        ),
                    ),
                ),
            )

            with pytest.raises(ValueError, match="chunks"):
                await repository.save_parsed_document(projection.id, document)

            evidence_count = (
                await session.execute(
                    select(EvidenceUnitRecord.id).where(
                        EvidenceUnitRecord.retrieval_chunk_id == chunk_id
                    )
                )
            ).scalar_one()
        await transaction.rollback()
    await engine.dispose()

    assert evidence_count is not None


@pytest.mark.asyncio
async def test_database_rejects_unknown_projection_status() -> None:
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(bind=connection, expire_on_commit=False) as session:
            fixture = await seed_projection_dependencies(session, label="invalid-status")
            with pytest.raises(IntegrityError):
                async with session.begin_nested():
                    session.add(
                        RagProjectionRecord(
                            id=uuid4(),
                            asset_version_id=fixture.asset_version_id,
                            indexing_profile_id=fixture.profile_id,
                            status="not-a-projection-status",
                        )
                    )
                    await session.flush()
        await transaction.rollback()
    await engine.dispose()
