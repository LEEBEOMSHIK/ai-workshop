from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine

from ai_workshop.config import get_settings
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
from ai_workshop.shared.errors import AppError
from tests.integration.rag_isolation_support import isolated_rag_resources  # noqa: F401

pytestmark = pytest.mark.integration


@dataclass(frozen=True, slots=True)
class LifecycleTarget:
    asset_version_id: UUID
    build_id: UUID


@asynccontextmanager
async def _isolated_connection() -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.connect() as connection:
            yield connection
    finally:
        await engine.dispose()


async def _add_version(
    session: AsyncSession,
    *,
    document_id: UUID,
    number: int,
    profile_id: UUID,
    processing_profile_id: UUID,
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
            document_processing_profile_id=processing_profile_id,
            indexing_profile_id=profile_id,
            status=projection_status,
        )
    )
    await session.flush()
    session.add(
        RagIndexBuildRecord(
            id=build_id,
            projection_id=projection_id,
            document_processing_profile_id=processing_profile_id,
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
) -> tuple[UUID, UUID, UUID, UUID]:
    actor_id = uuid4()
    workspace_id = uuid4()
    profile_id = uuid4()
    processing_profile_id = uuid4()
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
            ProfileRecord(
                id=processing_profile_id,
                kind="document_processing",
                name=f"task14a-processing-{processing_profile_id}",
                version=1,
                config={"parser": {}, "chunker": {}},
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
    return actor_id, workspace_id, profile_id, processing_profile_id


async def _resolve(
    session: AsyncSession,
    *,
    actor_id: UUID,
    workspace_id: UUID,
    profile_id: UUID,
    document_ids: tuple[UUID, ...] | None = None,
    processing_profile_id: UUID | None = None,
):
    return await SearchScopeResolver(
        SqlAlchemySearchScopeRepository(session)
    ).resolve(
        actor_id=actor_id,
        workspace_ids=(workspace_id,),
        folder_ids=(),
        indexing_profile_id=profile_id,
        document_ids=document_ids,
        document_processing_profile_id=processing_profile_id,
    )


@pytest.mark.asyncio
async def test_a1_is_excluded_after_active_pointer_switch_before_a2_finalizes(
    isolated_rag_resources: None,  # noqa: F811
) -> None:
    del isolated_rag_resources
    async with _isolated_connection() as connection:
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            actor_id, workspace_id, profile_id, processing_profile_id = (
                await _seed_authorized_scope(session)
            )
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
                processing_profile_id=processing_profile_id,
                projection_status="ready",
                build_status="ready",
                build_active=True,
            )
            a2 = await _add_version(
                session,
                document_id=document_a.id,
                number=2,
                profile_id=profile_id,
                processing_profile_id=processing_profile_id,
                projection_status="indexing",
                build_status="indexing",
                build_active=False,
            )
            b = await _add_version(
                session,
                document_id=document_b.id,
                number=1,
                profile_id=profile_id,
                processing_profile_id=processing_profile_id,
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

            with pytest.raises(AppError) as selected_error:
                await _resolve(
                    session,
                    actor_id=actor_id,
                    workspace_id=workspace_id,
                    profile_id=profile_id,
                    document_ids=(document_a.id,),
                    processing_profile_id=processing_profile_id,
                )
            assert (
                selected_error.value.code,
                selected_error.value.status_code,
            ) == ("selected_documents_not_ready", 409)
        finally:
            await session.close()
            await transaction.rollback()


@pytest.mark.asyncio
async def test_selected_scope_contains_only_exact_documents_and_processing_profile(
    isolated_rag_resources: None,  # noqa: F811
) -> None:
    del isolated_rag_resources
    async with _isolated_connection() as connection:
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            actor_id, workspace_id, profile_id, processing_profile_id = (
                await _seed_authorized_scope(session)
            )
            selected = DocumentRecord(
                id=uuid4(),
                workspace_id=workspace_id,
                folder_id=None,
                name="Selected.txt",
                active_version_id=None,
            )
            excluded = DocumentRecord(
                id=uuid4(),
                workspace_id=workspace_id,
                folder_id=None,
                name="Excluded.txt",
                active_version_id=None,
            )
            session.add_all([selected, excluded])
            await session.flush()
            selected_lifecycle = await _add_version(
                session,
                document_id=selected.id,
                number=1,
                profile_id=profile_id,
                processing_profile_id=processing_profile_id,
                projection_status="ready",
                build_status="ready",
                build_active=True,
            )
            excluded_lifecycle = await _add_version(
                session,
                document_id=excluded.id,
                number=1,
                profile_id=profile_id,
                processing_profile_id=processing_profile_id,
                projection_status="ready",
                build_status="ready",
                build_active=True,
            )
            selected.active_version_id = selected_lifecycle.asset_version_id
            excluded.active_version_id = excluded_lifecycle.asset_version_id
            await session.flush()

            scope = await _resolve(
                session,
                actor_id=actor_id,
                workspace_id=workspace_id,
                profile_id=profile_id,
                document_ids=(selected.id,),
                processing_profile_id=processing_profile_id,
            )

            assert scope.document_ids == (selected.id,)
            assert scope.asset_version_ids == (selected_lifecycle.asset_version_id,)
            assert scope.index_build_ids == (selected_lifecycle.build_id,)
            assert excluded_lifecycle.asset_version_id not in scope.asset_version_ids
            assert excluded_lifecycle.build_id not in scope.index_build_ids


            with pytest.raises(AppError) as profile_error:
                await _resolve(
                    session,
                    actor_id=actor_id,
                    workspace_id=workspace_id,
                    profile_id=profile_id,
                    document_ids=(selected.id,),
                    processing_profile_id=uuid4(),
                )
            assert (profile_error.value.code, profile_error.value.status_code) == (
                "selected_documents_not_ready",
                409,
            )
        finally:
            await session.close()
            await transaction.rollback()


@pytest.mark.asyncio
async def test_es_visible_a2_with_db_inactive_build_is_excluded_and_b_remains(
    isolated_rag_resources: None,  # noqa: F811
) -> None:
    del isolated_rag_resources
    async with _isolated_connection() as connection:
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            actor_id, workspace_id, profile_id, processing_profile_id = (
                await _seed_authorized_scope(session)
            )
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
                processing_profile_id=processing_profile_id,
                projection_status="ready",
                build_status="ready",
                build_active=False,
            )
            b = await _add_version(
                session,
                document_id=document_b.id,
                number=1,
                profile_id=profile_id,
                processing_profile_id=processing_profile_id,
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
