import os
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ai_workshop.labs.rag.documents.models import (
    RagIndexBuildRecord,
    RagProjectionRecord,
)
from ai_workshop.labs.rag.models.models import ProfileRecord
from ai_workshop.labs.rag.retrieval.scope import (
    SearchScopeResolver,
    SqlAlchemySearchScopeRepository,
)
from ai_workshop.platform.assets.domain import VersionStatus
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.identity.domain import UserRole
from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.platform.workspaces.domain import MembershipRole, WorkspaceKind
from ai_workshop.platform.workspaces.models import (
    WorkspaceMembershipRecord,
    WorkspaceRecord,
)

pytestmark = pytest.mark.integration
TEST_DATABASE_URL = os.getenv(
    "AI_WORKSHOP_TEST_DATABASE_URL",
    "postgresql+psycopg://ai_workshop:ai_workshop@127.0.0.1:5432/ai_workshop",
)


@dataclass(frozen=True, slots=True)
class LifecycleTarget:
    asset_version_id: UUID
    build_id: UUID


async def _add_version(
    session: AsyncSession,
    *,
    document_id: UUID,
    number: int,
    profile_id: UUID,
    projection_status: str,
    build_status: str | None,
    build_active: bool,
) -> LifecycleTarget:
    asset_version_id = uuid4()
    projection_id = uuid4()
    build_id = uuid4()
    session.add(
        AssetVersionRecord(
            id=asset_version_id,
            document_id=document_id,
            number=number,
            object_key=f"task14a/{asset_version_id}",
            sha256=f"{number}" * 64,
            media_type="text/plain",
            size=1,
            status=VersionStatus.READY,
        )
    )
    await session.flush()
    session.add(
        RagProjectionRecord(
            id=projection_id,
            asset_version_id=asset_version_id,
            indexing_profile_id=profile_id,
            status=projection_status,
        )
    )
    await session.flush()
    session.add(
        RagIndexBuildRecord(
            id=build_id,
            projection_id=projection_id,
            indexing_profile_id=profile_id,
            index_name=f"task14a-{build_id}",
            expected_document_count=1,
            indexed_document_count=1 if build_status == "ready" else 0,
            vector_dimension=2,
            status=build_status,
            is_active=build_active,
        )
    )
    await session.flush()
    return LifecycleTarget(asset_version_id, build_id)


async def _seed_authorized_scope(
    session: AsyncSession,
) -> tuple[UUID, UUID, UUID]:
    actor_id = uuid4()
    workspace_id = uuid4()
    profile_id = uuid4()
    session.add(
        UserRecord(
            id=actor_id,
            display_name="Task 14A Actor",
            email=f"{actor_id}@example.test",
            normalized_email=f"{actor_id}@example.test",
            password_hash="fixture-hash",
            role=UserRole.OWNER,
            is_active=True,
        )
    )
    await session.flush()
    session.add_all(
        [
            WorkspaceRecord(
                id=workspace_id,
                name="Task 14A Workspace",
                kind=WorkspaceKind.COMPANY,
                created_by=actor_id,
                expires_at=None,
            ),
            ProfileRecord(
                id=profile_id,
                kind="indexing",
                name=f"task14a-{profile_id}",
                version=1,
                config={"chunker": {}},
                evaluation_state="draft",
                is_default=False,
            ),
        ]
    )
    await session.flush()
    session.add(
        WorkspaceMembershipRecord(
            id=uuid4(),
            workspace_id=workspace_id,
            user_id=actor_id,
            role=MembershipRole.OWNER,
        )
    )
    await session.flush()
    return actor_id, workspace_id, profile_id


async def _resolve(
    session: AsyncSession,
    *,
    actor_id: UUID,
    workspace_id: UUID,
    profile_id: UUID,
):
    return await SearchScopeResolver(
        SqlAlchemySearchScopeRepository(session)
    ).resolve(
        actor_id=actor_id,
        workspace_ids=(workspace_id,),
        folder_ids=(),
        indexing_profile_id=profile_id,
    )


@pytest.mark.asyncio
async def test_a1_is_excluded_after_active_pointer_switch_before_a2_finalizes() -> None:
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            actor_id, workspace_id, profile_id = await _seed_authorized_scope(session)
            document_a = DocumentRecord(
                id=uuid4(),
                workspace_id=workspace_id,
                folder_id=None,
                name="A.txt",
                active_version_id=None,
            )
            document_b = DocumentRecord(
                id=uuid4(),
                workspace_id=workspace_id,
                folder_id=None,
                name="B.txt",
                active_version_id=None,
            )
            session.add_all([document_a, document_b])
            await session.flush()
            a1 = await _add_version(
                session,
                document_id=document_a.id,
                number=1,
                profile_id=profile_id,
                projection_status="ready",
                build_status="ready",
                build_active=True,
            )
            a2 = await _add_version(
                session,
                document_id=document_a.id,
                number=2,
                profile_id=profile_id,
                projection_status="indexing",
                build_status="indexing",
                build_active=False,
            )
            b = await _add_version(
                session,
                document_id=document_b.id,
                number=1,
                profile_id=profile_id,
                projection_status="ready",
                build_status="ready",
                build_active=True,
            )
            document_a.active_version_id = a2.asset_version_id
            document_b.active_version_id = b.asset_version_id
            await session.flush()

            scope = await _resolve(
                session,
                actor_id=actor_id,
                workspace_id=workspace_id,
                profile_id=profile_id,
            )

            assert scope.asset_version_ids == (b.asset_version_id,)
            assert scope.index_build_ids == (b.build_id,)
            assert a1.asset_version_id not in scope.asset_version_ids
            assert a1.build_id not in scope.index_build_ids
        finally:
            await session.close()
            await transaction.rollback()
    await engine.dispose()


@pytest.mark.asyncio
async def test_es_visible_a2_with_db_inactive_build_is_excluded_and_b_remains() -> None:
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            actor_id, workspace_id, profile_id = await _seed_authorized_scope(session)
            document_a = DocumentRecord(
                id=uuid4(),
                workspace_id=workspace_id,
                folder_id=None,
                name="A.txt",
                active_version_id=None,
            )
            document_b = DocumentRecord(
                id=uuid4(),
                workspace_id=workspace_id,
                folder_id=None,
                name="B.txt",
                active_version_id=None,
            )
            session.add_all([document_a, document_b])
            await session.flush()
            a2 = await _add_version(
                session,
                document_id=document_a.id,
                number=2,
                profile_id=profile_id,
                projection_status="ready",
                build_status="ready",
                build_active=False,
            )
            b = await _add_version(
                session,
                document_id=document_b.id,
                number=1,
                profile_id=profile_id,
                projection_status="ready",
                build_status="ready",
                build_active=True,
            )
            document_a.active_version_id = a2.asset_version_id
            document_b.active_version_id = b.asset_version_id
            await session.flush()

            scope = await _resolve(
                session,
                actor_id=actor_id,
                workspace_id=workspace_id,
                profile_id=profile_id,
            )

            assert scope.asset_version_ids == (b.asset_version_id,)
            assert scope.index_build_ids == (b.build_id,)
            assert a2.asset_version_id not in scope.asset_version_ids
            assert a2.build_id not in scope.index_build_ids
        finally:
            await session.close()
            await transaction.rollback()
    await engine.dispose()
