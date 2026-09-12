"""Company grants are authoritative across read/write and concurrent transactions."""

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_workshop.config import Settings
from ai_workshop.infrastructure.object_store.local import LocalObjectStore
from ai_workshop.labs.rag.configurations.repository import SqlAlchemyRagConfigurationRepository
from ai_workshop.labs.rag.domains.repository import SqlAlchemyDomainRepository
from ai_workshop.labs.rag.generation.evidence_approval_request_schemas import (
    EvidenceApprovalRequestCreate,
)
from ai_workshop.labs.rag.generation.evidence_approval_requests import EvidenceApprovalRequests
from ai_workshop.labs.rag.retrieval.scope import (
    SearchScopeResolver,
    SqlAlchemySearchScopeRepository,
)
from ai_workshop.platform.assets.library_repository import SqlAlchemyLibraryRepository
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.assets.originals import SqlAlchemyOriginalRepository
from ai_workshop.platform.assets.repository import SqlAlchemyAssetRepository
from ai_workshop.platform.assets.service import AssetService, AssetUploadCoordinator
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.domain import UserRole
from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.platform.jobs.domain import Job, JobType
from ai_workshop.platform.jobs.models import JobRecord
from ai_workshop.platform.jobs.repository import SqlAlchemyJobRepository
from ai_workshop.platform.jobs.service import JobService
from ai_workshop.platform.workspaces.api import router
from ai_workshop.platform.workspaces.domain import MembershipRole, WorkspaceGrants, WorkspaceKind
from ai_workshop.platform.workspaces.member_repository import SqlAlchemyWorkspaceMemberRepository
from ai_workshop.platform.workspaces.models import (
    WorkspaceMembershipRecord,
    WorkspacePermissionAuditRecord,
    WorkspaceRecord,
)
from ai_workshop.platform.workspaces.repository import SqlAlchemyWorkspaceRepository
from ai_workshop.shared.db import get_session
from ai_workshop.shared.errors import AppError, register_error_handlers
from alembic import command
from tests.integration.platform.assets.test_asset_originals import seed_original
from tests.integration.publishing_support import (
    IsolatedPublishingDatabase,
    isolated_publishing_database,
)


@pytest.fixture
def database(monkeypatch: pytest.MonkeyPatch) -> Iterator[IsolatedPublishingDatabase]:
    with isolated_publishing_database(monkeypatch) as isolated:
        command.upgrade(isolated.config, "head")
        yield isolated


async def content() -> AsyncIterator[bytes]:
    yield b"Synthetic permission test"


@pytest.mark.asyncio
async def test_new_company_member_can_read_but_cannot_write(
    database: IsolatedPublishingDatabase, tmp_path: Path
) -> None:
    seed = await seed_original(database.database_url)
    engine = create_async_engine(database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    root = Path("\\\\?\\" + str(tmp_path)) if os.name == "nt" else tmp_path
    store = LocalObjectStore(root)
    try:
        async with sessions.begin() as session:
            await session.execute(
                update(WorkspaceRecord)
                .where(WorkspaceRecord.id == seed.workspace_id)
                .values(kind=WorkspaceKind.COMPANY, expires_at=None)
            )
        async with sessions.begin() as session:
            repository = SqlAlchemyAssetRepository(session)
            service = AssetService(repository, store, max_upload_bytes=1024)
            assert await repository.has_workspace_access(seed.user.id, seed.workspace_id)
            with pytest.raises(AppError) as denied:
                await service.create_folder(
                    user=seed.user, workspace_id=seed.workspace_id, parent_id=None, name="Denied"
                )
            assert denied.value.status_code == 404
            with pytest.raises(AppError) as denied:
                await service.upload(
                    user=seed.user,
                    workspace_id=seed.workspace_id,
                    folder_id=None,
                    filename="denied.txt",
                    media_type="text/plain",
                    content=content(),
                )
            assert denied.value.status_code == 404
            with pytest.raises(AppError) as denied:
                await service.upload_version(
                    user=seed.user,
                    document_id=seed.document_id,
                    filename="denied.txt",
                    media_type="text/plain",
                    content=content(),
                )
            assert denied.value.status_code == 404
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_compare_and_swap_has_one_winner_and_atomic_audit(
    database: IsolatedPublishingDatabase,
) -> None:
    seed = await seed_original(database.database_url)
    engine = create_async_engine(database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            await session.execute(
                update(WorkspaceRecord)
                .where(WorkspaceRecord.id == seed.workspace_id)
                .values(kind=WorkspaceKind.COMPANY, expires_at=None)
            )
            await session.execute(
                update(WorkspaceMembershipRecord)
                .where(WorkspaceMembershipRecord.workspace_id == seed.workspace_id)
                .values(role=MembershipRole.OWNER, can_read=True, can_write=True, can_delete=True)
            )

        async def change() -> int:
            try:
                async with sessions.begin() as session:
                    await SqlAlchemyWorkspaceMemberRepository(session).put_member(
                        seed.user.id,
                        seed.workspace_id,
                        seed.foreign_user_id,
                        grants=WorkspaceGrants(),
                        expected_revision=0,
                    )
                return 200
            except AppError as error:
                return error.status_code

        assert sorted(await asyncio.wait_for(asyncio.gather(change(), change()), 15)) == [200, 409]
        async with sessions() as session:
            audits = (await session.scalars(select(WorkspacePermissionAuditRecord))).all()
            assert len(audits) == 1
            assert audits[0].before_permissions is None
            assert audits[0].after_permissions == {"read": True, "write": False, "delete": False}
            assert audits[0].permission_revision == 1
        with pytest.raises(RuntimeError, match="rollback"):
            async with sessions.begin() as session:
                await SqlAlchemyWorkspaceMemberRepository(session).put_member(
                    seed.user.id,
                    seed.workspace_id,
                    seed.foreign_user_id,
                    grants=WorkspaceGrants(False, False, False),
                    expected_revision=1,
                )
                raise RuntimeError("rollback")
        async with sessions() as session:
            assert (
                await session.scalar(
                    select(func.count()).select_from(WorkspacePermissionAuditRecord)
                )
                == 1
            )
            member = await session.scalar(
                select(WorkspaceMembershipRecord).where(
                    WorkspaceMembershipRecord.user_id == seed.foreign_user_id
                )
            )
            assert member is not None and member.can_read and member.permission_revision == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("new_version", [False, True])
async def test_streaming_write_revoked_before_save_leaves_no_document_job_or_object(
    database: IsolatedPublishingDatabase,
    tmp_path: Path,
    new_version: bool,
) -> None:
    seed = await seed_original(database.database_url)
    engine = create_async_engine(database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    member = replace(seed.user, id=seed.foreign_user_id)
    root = Path("\\\\?\\" + str(tmp_path)) if os.name == "nt" else tmp_path
    store = LocalObjectStore(root)
    received, proceed = asyncio.Event(), asyncio.Event()
    try:
        async with sessions.begin() as session:
            await session.execute(
                update(WorkspaceRecord)
                .where(WorkspaceRecord.id == seed.workspace_id)
                .values(kind=WorkspaceKind.COMPANY, expires_at=None)
            )
            await session.execute(
                update(WorkspaceMembershipRecord)
                .where(WorkspaceMembershipRecord.workspace_id == seed.workspace_id)
                .values(role=MembershipRole.OWNER, can_read=True, can_write=True, can_delete=True)
            )
            await SqlAlchemyWorkspaceMemberRepository(session).put_member(
                seed.user.id,
                seed.workspace_id,
                member.id,
                grants=WorkspaceGrants(True, True, False),
                expected_revision=0,
            )

        async def stream() -> AsyncIterator[bytes]:
            yield b"Synthetic pending upload"
            received.set()
            await asyncio.wait_for(proceed.wait(), 15)
            yield b" complete"

        async def upload() -> int:
            try:
                async with sessions.begin() as session:
                    coordinator = AssetUploadCoordinator(
                        AssetService(
                            SqlAlchemyAssetRepository(session), store, max_upload_bytes=1024
                        ),
                        JobService(SqlAlchemyJobRepository(session)),
                        commit=session.commit,
                    )
                    if new_version:
                        await coordinator.upload_version(
                            user=member,
                            document_id=seed.document_id,
                            filename="new.txt",
                            media_type="text/plain",
                            content=stream(),
                        )
                    else:
                        await coordinator.upload(
                            user=member,
                            workspace_id=seed.workspace_id,
                            folder_id=None,
                            filename="new.txt",
                            media_type="text/plain",
                            content=stream(),
                        )
                return 200
            except AppError as error:
                return error.status_code

        upload_task = asyncio.create_task(upload())
        await asyncio.wait_for(received.wait(), 15)
        async with sessions.begin() as session:
            await SqlAlchemyWorkspaceMemberRepository(session).put_member(
                seed.user.id,
                seed.workspace_id,
                member.id,
                grants=WorkspaceGrants(),
                expected_revision=1,
            )
        proceed.set()
        assert await asyncio.wait_for(upload_task, 15) == 404
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(DocumentRecord)) == 1
            assert await session.scalar(select(func.count()).select_from(AssetVersionRecord)) == 2
            assert await session.scalar(select(func.count()).select_from(JobRecord)) == 0
        assert [path for path in root.rglob("*") if path.is_file()] == []
    finally:
        proceed.set()
        await engine.dispose()


@pytest.mark.asyncio
async def test_workspace_owner_api_grants_audits_and_rejects_stale_revision(
    database: IsolatedPublishingDatabase,
) -> None:
    seed = await seed_original(database.database_url)
    engine = create_async_engine(database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(router)
    actor = seed.user

    async def session_dependency():
        async with sessions.begin() as session:
            yield session

    app.dependency_overrides[get_session] = session_dependency
    app.dependency_overrides[get_current_user] = lambda: actor
    try:
        async with sessions.begin() as session:
            await session.execute(
                update(WorkspaceRecord)
                .where(WorkspaceRecord.id == seed.workspace_id)
                .values(kind=WorkspaceKind.COMPANY, expires_at=None)
            )
            await session.execute(
                update(WorkspaceMembershipRecord)
                .where(WorkspaceMembershipRecord.workspace_id == seed.workspace_id)
                .values(role=MembershipRole.OWNER, can_read=True, can_write=True, can_delete=True)
            )
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            base = f"/api/v1/workspaces/{seed.workspace_id}"
            capability = await client.get(base + "/capabilities")
            assert capability.status_code == 200
            assert capability.json() == {
                "read": True,
                "write": True,
                "delete": True,
                "manage_members": True,
            }
            target = base + f"/members/{seed.foreign_user_id}"
            payload = {"read": True, "write": False, "delete": False, "expected_revision": 0}
            created = await client.put(target, json=payload)
            assert created.status_code == 200
            assert created.json()["permission_revision"] == 1
            assert (await client.put(target, json=payload)).status_code == 409
            members = await client.get(base + "/members")
            assert members.status_code == 200
            assert len(members.json()["items"]) == 2
            assert "password_hash" not in members.text and "normalized_email" not in members.text
            page_one = (await client.get(base + "/members?limit=1")).json()
            page_two = (
                await client.get(
                    base + "/members",
                    params={
                        "limit": 1,
                        "after": page_one["next_after"],
                    },
                )
            ).json()
            assert {page_one["items"][0]["user_id"], page_two["items"][0]["user_id"]} == {
                str(seed.user.id),
                str(seed.foreign_user_id),
            }
            assert page_two["next_after"] is None
            async with sessions.begin() as session:
                await session.execute(
                    update(UserRecord)
                    .where(UserRecord.id == seed.foreign_user_id)
                    .values(role=UserRole.OWNER)
                )
            actor = replace(seed.user, id=seed.foreign_user_id, role=UserRole.OWNER)
            assert (await client.get(base + "/capabilities")).json() == {
                "read": True,
                "write": False,
                "delete": False,
                "manage_members": False,
            }
            assert (await client.get(base + "/members")).status_code == 404
            assert (await client.put(target, json=payload)).status_code == 404
            actor = seed.user
            payload["expected_revision"] = 1
            payload["read"] = False
            revoked = await client.put(target, json=payload)
            assert revoked.status_code == 200
            assert revoked.json()["permission_revision"] == 2
            for bad in (True, -1, "2"):
                invalid = {**payload, "expected_revision": bad}
                assert (await client.put(target, json=invalid)).status_code == 422
            assert (
                await client.put(base + f"/members/{seed.user.id}", json=payload)
            ).status_code == 404
            actor = replace(seed.user, id=seed.foreign_user_id, role=UserRole.OWNER)
            assert (await client.get(base + "/members")).status_code == 404
            assert (await client.get(base + "/capabilities")).status_code == 404
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_revoked_company_membership_is_not_a_read_allowlist(
    database: IsolatedPublishingDatabase,
) -> None:
    seed = await seed_original(database.database_url)
    engine = create_async_engine(database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    requests = EvidenceApprovalRequests(
        sessions, Settings(secret_key="synthetic-permission-key-32-characters")
    )
    try:
        async with sessions.begin() as session:
            await session.execute(
                update(WorkspaceRecord)
                .where(WorkspaceRecord.id == seed.workspace_id)
                .values(kind=WorkspaceKind.COMPANY, expires_at=None)
            )
            job = await SqlAlchemyJobRepository(session).add(
                Job.create(
                    user_id=seed.user.id,
                    workspace_id=seed.workspace_id,
                    asset_version_id=seed.ready_version_id,
                    type=JobType.VERIFY_ASSET,
                    idempotency_key="synthetic-revocation-job",
                )
            )
            assert await SqlAlchemyJobRepository(session).find_for_user(seed.user.id, job.id)
            assert await SqlAlchemyDomainRepository(session).workspace_options_for_actor(
                seed.user.id, (seed.workspace_id,)
            )
            assert await SqlAlchemyRagConfigurationRepository(session).authorized_workspace_ids(
                seed.user.id, (seed.workspace_id,)
            ) == (seed.workspace_id,)
        body = EvidenceApprovalRequestCreate(
            request_id=uuid4(),
            revision_id=seed.ready_version_id,
            provider="development_codex_exec",
            expected_approval_generation=0,
        )
        assert (await requests.create(actor_id=seed.user.id, body=body)).status == "pending"
        assert len((await requests.list(actor_id=seed.user.id)).items) == 1
        async with sessions.begin() as session:
            await session.execute(
                update(WorkspaceMembershipRecord)
                .where(WorkspaceMembershipRecord.workspace_id == seed.workspace_id)
                .values(can_read=False, can_write=False, can_delete=False)
            )
        async with sessions() as session:
            assert (
                await SqlAlchemyJobRepository(session).find_for_user(seed.user.id, job.id) is None
            )
            assert (
                await SqlAlchemyDomainRepository(session).workspace_options_for_actor(
                    seed.user.id, (seed.workspace_id,)
                )
                == ()
            )
            assert (
                await SqlAlchemyRagConfigurationRepository(session).authorized_workspace_ids(
                    seed.user.id, (seed.workspace_id,)
                )
                == ()
            )
            assert await SqlAlchemyWorkspaceRepository(session).list_for_user(seed.user.id) == []
            assets = SqlAlchemyAssetRepository(session)
            assert await assets.list_documents(seed.user.id, seed.workspace_id) == []
            assert await assets.find_document_for_user(seed.user.id, seed.document_id) is None
            assert (
                await SqlAlchemyOriginalRepository(session).resolve(
                    user_id=seed.user.id,
                    document_id=seed.document_id,
                    version_id=seed.ready_version_id,
                )
                is None
            )
            assert (
                await SqlAlchemyLibraryRepository(session).workspace_for_user(
                    seed.user.id, seed.workspace_id
                )
                is None
            )
            with pytest.raises(AppError) as denied:
                await SearchScopeResolver(SqlAlchemySearchScopeRepository(session)).resolve(
                    actor_id=seed.user.id,
                    workspace_ids=(seed.workspace_id,),
                    folder_ids=(),
                    indexing_profile_id=seed.document_id,
                )
            assert denied.value.status_code == 404
        assert (await requests.list(actor_id=seed.user.id)).items == []
        with pytest.raises(AppError) as denied:
            await requests.list(actor_id=seed.user.id, revision_id=seed.ready_version_id)
        assert denied.value.status_code == 404
        with pytest.raises(AppError) as denied:
            await requests.create(
                actor_id=seed.user.id, body=body.model_copy(update={"request_id": uuid4()})
            )
        assert denied.value.status_code == 404
    finally:
        await engine.dispose()
