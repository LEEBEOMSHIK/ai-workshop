import os
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ai_workshop.labs.rag.documents.domain import EvidenceUnit, SourceLocation
from ai_workshop.labs.rag.documents.models import (
    EvidenceUnitRecord,
    RagIndexBuildRecord,
    RagProjectionRecord,
    RetrievalChunkRecord,
    StructuralElementRecord,
)
from ai_workshop.labs.rag.ingestion.models import RagIngestionJobRecord
from ai_workshop.labs.rag.models.models import ProfileRecord
from ai_workshop.labs.rag.retrieval.domain import FusedHit, RetrievedChunk
from ai_workshop.labs.rag.search.repository import SqlAlchemySearchSourceResolver
from ai_workshop.labs.rag.search.viewer_repository import (
    SqlAlchemyViewerResourceAccessRepository,
)
from ai_workshop.platform.assets.domain import VersionStatus
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.identity.domain import UserRole
from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.platform.jobs.domain import JobStatus, JobType
from ai_workshop.platform.jobs.models import JobRecord
from ai_workshop.platform.workspaces.domain import MembershipRole, WorkspaceKind
from ai_workshop.platform.workspaces.models import (
    WorkspaceMembershipRecord,
    WorkspaceRecord,
)

TEST_DATABASE_URL = os.getenv(
    "AI_WORKSHOP_TEST_DATABASE_URL",
    "postgresql+psycopg://ai_workshop:ai_workshop@127.0.0.1:5432/ai_workshop",
)


@dataclass(frozen=True)
class StoredSource:
    hit: FusedHit
    document_id: UUID
    asset_version_id: UUID
    projection_id: UUID
    chunk_id: UUID
    text: str


async def _add_source(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    profile_id: UUID,
    title: str,
    text: str,
    active: bool,
    active_build: bool,
    add_viewer_artifact: bool = False,
) -> StoredSource:
    document_id = uuid4()
    asset_version_id = uuid4()
    active_version_id = asset_version_id if active else uuid4()
    session.add(
        DocumentRecord(
            id=document_id,
            workspace_id=workspace_id,
            folder_id=None,
            name=title,
            active_version_id=active_version_id,
        )
    )
    await session.flush()
    session.add(
        AssetVersionRecord(
            id=asset_version_id,
            document_id=document_id,
            number=1,
            object_key=f"synthetic/{asset_version_id}",
            sha256="1" * 64,
            media_type="text/plain",
            size=len(text.encode()),
            status=VersionStatus.READY,
        )
    )
    if not active:
        session.add(
            AssetVersionRecord(
                id=active_version_id,
                document_id=document_id,
                number=2,
                object_key=f"synthetic/{active_version_id}",
                sha256="2" * 64,
                media_type="text/plain",
                size=1,
                status=VersionStatus.READY,
            )
        )
    await session.flush()

    projection_id = uuid4()
    element_id = uuid4()
    chunk_id = uuid4()
    evidence_id = uuid4()
    build_id = uuid4()
    location = SourceLocation(element_id, None, 10, 10 + len(text), None)
    session.add(
        RagProjectionRecord(
            id=projection_id,
            asset_version_id=asset_version_id,
            indexing_profile_id=profile_id,
            status="ready",
        )
    )
    await session.flush()
    session.add(
        StructuralElementRecord(
            id=element_id,
            projection_id=projection_id,
            ordinal=0,
            kind="paragraph",
            text=text,
            section_path=["약관"],
            page=None,
            char_start=10,
            char_end=10 + len(text),
            bbox=None,
            parser_name="fixture",
            parser_version="1",
            confidence=1.0,
        )
    )
    session.add(
        RetrievalChunkRecord(
            id=chunk_id,
            projection_id=projection_id,
            ordinal=0,
            text=text,
            section_path=["약관"],
        )
    )
    await session.flush()
    session.add(
        EvidenceUnitRecord(
            id=evidence_id,
            projection_id=projection_id,
            retrieval_chunk_id=chunk_id,
            ordinal=0,
            text=text,
            element_id=element_id,
            page=None,
            char_start=10,
            char_end=10 + len(text),
            bbox=None,
        )
    )
    session.add(
        RagIndexBuildRecord(
            id=build_id,
            projection_id=projection_id,
            indexing_profile_id=profile_id,
            index_name=f"fixture-{build_id}",
            expected_document_count=1,
            indexed_document_count=1,
            vector_dimension=2,
            status="ready",
            is_active=active_build,
        )
    )
    await session.flush()

    if add_viewer_artifact:
        job_id = uuid4()
        session.add(
            JobRecord(
                id=job_id,
                user_id=(await session.get(WorkspaceRecord, workspace_id)).created_by,
                workspace_id=workspace_id,
                asset_version_id=asset_version_id,
                type=JobType.RAG_INGESTION,
                idempotency_key=f"viewer-{asset_version_id}",
                status=JobStatus.SUCCEEDED,
                stage="ready",
                attempt=1,
                error_code=None,
                error_message=None,
                started_at=None,
                finished_at=None,
            )
        )
        await session.flush()
        session.add(
            RagIngestionJobRecord(
                job_id=job_id,
                projection_id=projection_id,
                asset_version_id=asset_version_id,
                indexing_profile_id=profile_id,
                requested_by=(await session.get(WorkspaceRecord, workspace_id)).created_by,
                parsed_object_key=f"rag/parsed/{projection_id}.json",
                parsed_sha256="3" * 64,
                chunk_object_key=f"rag/chunks/{projection_id}.json",
                chunk_sha256="4" * 64,
                embedding_object_key=f"rag/embeddings/{projection_id}.json",
                embedding_sha256="5" * 64,
                index_build_id=build_id,
                parsed_element_count=1,
                chunk_count=1,
                embedding_count=1,
                indexed_document_count=1,
                index_alias_verified=True,
            )
        )
        await session.flush()

    stale_evidence = EvidenceUnit(
        id=evidence_id,
        chunk_id=chunk_id,
        projection_id=projection_id,
        ordinal=0,
        text="stale Elasticsearch evidence",
        location=location,
    )
    stale_chunk = RetrievedChunk(
        chunk_id=chunk_id,
        projection_id=projection_id,
        asset_version_id=asset_version_id,
        workspace_id=workspace_id,
        folder_id=None,
        index_build_id=build_id,
        title="stale Elasticsearch title",
        section_path=("stale",),
        text="stale Elasticsearch text",
        evidence_units=(stale_evidence,),
    )
    return StoredSource(
        hit=FusedHit(
            chunk_id=chunk_id,
            score=0.5,
            best_rank=1,
            sparse_rank=1,
            dense_rank=1,
            chunk=stale_chunk,
        ),
        document_id=document_id,
        asset_version_id=asset_version_id,
        projection_id=projection_id,
        chunk_id=chunk_id,
        text=text,
    )


@pytest.mark.asyncio
async def test_source_and_viewer_repositories_enforce_authoritative_active_access() -> None:
    engine = create_async_engine(TEST_DATABASE_URL)
    actor_id = uuid4()
    other_id = uuid4()
    company_workspace_id = uuid4()
    private_workspace_id = uuid4()
    profile_id = uuid4()

    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            session.add_all(
                [
                    UserRecord(
                        id=actor_id,
                        display_name="Fixture Actor",
                        email=f"{actor_id}@example.com",
                        normalized_email=f"{actor_id}@example.com",
                        password_hash="hash",
                        role=UserRole.OWNER,
                        is_active=True,
                    ),
                    UserRecord(
                        id=other_id,
                        display_name="Other Fixture Actor",
                        email=f"{other_id}@example.com",
                        normalized_email=f"{other_id}@example.com",
                        password_hash="hash",
                        role=UserRole.OWNER,
                        is_active=True,
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    WorkspaceRecord(
                        id=company_workspace_id,
                        name="Fixture Company",
                        kind=WorkspaceKind.COMPANY,
                        created_by=actor_id,
                        expires_at=None,
                    ),
                    WorkspaceRecord(
                        id=private_workspace_id,
                        name="Other Private",
                        kind=WorkspaceKind.PERSONAL,
                        created_by=other_id,
                        expires_at=None,
                    ),
                    ProfileRecord(
                        id=profile_id,
                        kind="indexing",
                        name=f"fixture-{profile_id}",
                        version=1,
                        config={"chunker": {}},
                        evaluation_state="draft",
                        is_default=False,
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    WorkspaceMembershipRecord(
                        id=uuid4(),
                        workspace_id=company_workspace_id,
                        user_id=actor_id,
                        role=MembershipRole.OWNER,
                    ),
                    WorkspaceMembershipRecord(
                        id=uuid4(),
                        workspace_id=private_workspace_id,
                        user_id=other_id,
                        role=MembershipRole.OWNER,
                    ),
                ]
            )
            await session.flush()

            public = await _add_source(
                session,
                workspace_id=company_workspace_id,
                profile_id=profile_id,
                title="authoritative-public.txt",
                text="authoritative public evidence",
                active=True,
                active_build=True,
                add_viewer_artifact=True,
            )
            inactive = await _add_source(
                session,
                workspace_id=company_workspace_id,
                profile_id=profile_id,
                title="inactive.txt",
                text="inactive old evidence",
                active=False,
                active_build=False,
            )
            private = await _add_source(
                session,
                workspace_id=private_workspace_id,
                profile_id=profile_id,
                title="private.txt",
                text="private evidence",
                active=True,
                active_build=False,
            )

            resolved = await SqlAlchemySearchSourceResolver(session).resolve(
                actor_id=actor_id,
                indexing_profile_id=profile_id,
                hits=(public.hit, private.hit, inactive.hit),
            )

            assert len(resolved) == 1
            assert resolved[0].document_id == public.document_id
            assert resolved[0].chunk.title == "authoritative-public.txt"
            assert resolved[0].chunk.text == public.text
            assert resolved[0].chunk.evidence_units[0].text == public.text
            assert resolved[0].chunk.evidence_units[0].location.char_start == 10

            viewer = SqlAlchemyViewerResourceAccessRepository(session)
            allowed = await viewer.resolve(
                actor_id=actor_id,
                asset_version_id=public.asset_version_id,
                projection_id=public.projection_id,
            )
            inactive_viewer = await viewer.resolve(
                actor_id=actor_id,
                asset_version_id=inactive.asset_version_id,
                projection_id=inactive.projection_id,
            )
            private_viewer = await viewer.resolve(
                actor_id=actor_id,
                asset_version_id=private.asset_version_id,
                projection_id=private.projection_id,
            )

            assert allowed is not None
            assert allowed.document_id == public.document_id
            assert allowed.parsed_object_key == f"rag/parsed/{public.projection_id}.json"
            assert inactive_viewer is None
            assert private_viewer is None
        finally:
            await session.close()
            await transaction.rollback()
    await engine.dispose()
