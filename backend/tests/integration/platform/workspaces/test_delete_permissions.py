"""Current SQL delete authorization, including stale-session and lock races."""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.sql.elements import ColumnElement

from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.platform.workspaces.domain import MembershipRole, WorkspaceKind
from ai_workshop.platform.workspaces.models import WorkspaceMembershipRecord, WorkspaceRecord
from ai_workshop.platform.workspaces.permissions import (
    require_workspace_delete,
    workspace_delete_allowed,
    workspace_read_allowed,
    workspace_write_allowed,
)
from ai_workshop.shared.errors import AppError
from alembic import command
from tests.integration.platform.assets.test_asset_originals import seed_original
from tests.integration.publishing_support import (
    IsolatedPublishingDatabase,
    isolated_publishing_database,
)


@pytest.fixture(scope="module")
def database() -> Iterator[IsolatedPublishingDatabase]:
    with (
        pytest.MonkeyPatch.context() as patch,
        isolated_publishing_database(patch) as isolated,
    ):
        command.upgrade(isolated.config, "head")
        yield isolated


async def _is_allowed(
    session: AsyncSession,
    workspace_id: UUID,
    condition: ColumnElement[bool],
) -> bool:
    found = await session.scalar(
        select(WorkspaceRecord.id).where(WorkspaceRecord.id == workspace_id, condition)
    )
    return found is not None


async def _capabilities(
    session: AsyncSession, actor_id: UUID, workspace_id: UUID
) -> tuple[bool, bool, bool]:
    return (
        await _is_allowed(session, workspace_id, workspace_read_allowed(actor_id)),
        await _is_allowed(session, workspace_id, workspace_write_allowed(actor_id)),
        await _is_allowed(session, workspace_id, workspace_delete_allowed(actor_id)),
    )


async def _wait_for_database_blocker(
    session: AsyncSession, waiting_pid: int, blocker_pid: int
) -> None:
    async with asyncio.timeout(15):
        while True:
            blocking_pids = await session.scalar(select(func.pg_blocking_pids(waiting_pid)))
            if blocking_pids is not None and blocker_pid in blocking_pids:
                return
            await asyncio.sleep(0.01)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("can_read", "can_write", "can_delete", "expected"),
    [
        (False, False, False, (False, False, False)),
        (True, False, False, (True, False, False)),
        (True, True, False, (True, True, False)),
        (True, False, True, (True, False, True)),
        (True, True, True, (True, True, True)),
    ],
)
async def test_company_member_uses_independent_valid_grants(
    database: IsolatedPublishingDatabase,
    can_read: bool,
    can_write: bool,
    can_delete: bool,
    expected: tuple[bool, bool, bool],
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
                .where(
                    WorkspaceMembershipRecord.workspace_id == seed.workspace_id,
                    WorkspaceMembershipRecord.user_id == seed.user.id,
                )
                .values(
                    role=MembershipRole.MEMBER,
                    can_read=can_read,
                    can_write=can_write,
                    can_delete=can_delete,
                )
            )
        async with sessions() as session:
            assert await _capabilities(session, seed.user.id, seed.workspace_id) == expected
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_company_owner_role_allows_delete_without_stored_grants(
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
                .where(
                    WorkspaceMembershipRecord.workspace_id == seed.workspace_id,
                    WorkspaceMembershipRecord.user_id == seed.user.id,
                )
                .values(
                    role=MembershipRole.OWNER,
                    can_read=False,
                    can_write=False,
                    can_delete=False,
                )
            )
        async with sessions.begin() as session:
            assert await _capabilities(session, seed.user.id, seed.workspace_id) == (
                True,
                True,
                True,
            )
            await require_workspace_delete(session, seed.user.id, seed.workspace_id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_personal_creator_delete_ignores_grants_but_forged_member_is_denied(
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
                .values(kind=WorkspaceKind.PERSONAL, expires_at=None)
            )
            await session.execute(
                update(WorkspaceMembershipRecord)
                .where(
                    WorkspaceMembershipRecord.workspace_id == seed.workspace_id,
                    WorkspaceMembershipRecord.user_id == seed.user.id,
                )
                .values(
                    role=MembershipRole.MEMBER,
                    can_read=False,
                    can_write=False,
                    can_delete=False,
                )
            )
            session.add(
                WorkspaceMembershipRecord(
                    workspace_id=seed.workspace_id,
                    user_id=seed.foreign_user_id,
                    role=MembershipRole.OWNER,
                    can_read=True,
                    can_write=True,
                    can_delete=True,
                )
            )
        async with sessions.begin() as session:
            await require_workspace_delete(session, seed.user.id, seed.workspace_id)
            with pytest.raises(AppError) as denied:
                await require_workspace_delete(session, seed.foreign_user_id, seed.workspace_id)
            assert denied.value.code == "not_found" and denied.value.status_code == 404
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "role", "expires_at", "expected"),
    [
        (WorkspaceKind.TEAM, MembershipRole.OWNER, None, True),
        (WorkspaceKind.TEAM, MembershipRole.MEMBER, None, False),
        (
            WorkspaceKind.TEMPORARY,
            MembershipRole.OWNER,
            datetime.now(UTC) + timedelta(hours=1),
            True,
        ),
        (
            WorkspaceKind.TEMPORARY,
            MembershipRole.MEMBER,
            datetime.now(UTC) + timedelta(hours=1),
            False,
        ),
    ],
)
async def test_non_company_delete_requires_owner_role(
    database: IsolatedPublishingDatabase,
    kind: WorkspaceKind,
    role: MembershipRole,
    expires_at: datetime | None,
    expected: bool,
) -> None:
    seed = await seed_original(database.database_url)
    engine = create_async_engine(database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            await session.execute(
                update(WorkspaceRecord)
                .where(WorkspaceRecord.id == seed.workspace_id)
                .values(kind=kind, expires_at=expires_at)
            )
            await session.execute(
                update(WorkspaceMembershipRecord)
                .where(
                    WorkspaceMembershipRecord.workspace_id == seed.workspace_id,
                    WorkspaceMembershipRecord.user_id == seed.user.id,
                )
                .values(
                    role=role,
                    can_read=True,
                    can_write=True,
                    can_delete=True,
                )
            )
        async with sessions.begin() as session:
            assert await _is_allowed(
                session, seed.workspace_id, workspace_write_allowed(seed.user.id)
            )
            assert (
                await _is_allowed(
                    session, seed.workspace_id, workspace_delete_allowed(seed.user.id)
                )
                is expected
            )
            if expected:
                await require_workspace_delete(session, seed.user.id, seed.workspace_id)
            else:
                with pytest.raises(AppError) as denied:
                    await require_workspace_delete(session, seed.user.id, seed.workspace_id)
                assert denied.value.code == "not_found" and denied.value.status_code == 404
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(("expired", "inactive"), [(True, False), (False, True)])
async def test_delete_denies_expired_workspace_or_inactive_actor(
    database: IsolatedPublishingDatabase,
    expired: bool,
    inactive: bool,
) -> None:
    seed = await seed_original(database.database_url)
    engine = create_async_engine(database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            await session.execute(
                update(WorkspaceRecord)
                .where(WorkspaceRecord.id == seed.workspace_id)
                .values(
                    kind=WorkspaceKind.TEMPORARY,
                    expires_at=datetime.now(UTC)
                    + (timedelta(hours=-1) if expired else timedelta(hours=1)),
                )
            )
            await session.execute(
                update(WorkspaceMembershipRecord)
                .where(
                    WorkspaceMembershipRecord.workspace_id == seed.workspace_id,
                    WorkspaceMembershipRecord.user_id == seed.user.id,
                )
                .values(role=MembershipRole.OWNER)
            )
            if inactive:
                await session.execute(
                    update(UserRecord)
                    .where(UserRecord.id == seed.user.id)
                    .values(is_active=False)
                )
        async with sessions.begin() as session:
            with pytest.raises(AppError) as denied:
                await require_workspace_delete(session, seed.user.id, seed.workspace_id)
            assert denied.value.code == "not_found" and denied.value.status_code == 404
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_delete_uses_current_sql_instead_of_stale_identity_map(
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
                .where(
                    WorkspaceMembershipRecord.workspace_id == seed.workspace_id,
                    WorkspaceMembershipRecord.user_id == seed.user.id,
                )
                .values(
                    role=MembershipRole.MEMBER,
                    can_read=True,
                    can_write=False,
                    can_delete=True,
                )
            )

        async with sessions() as stale_session:
            stale_member = await stale_session.scalar(
                select(WorkspaceMembershipRecord).where(
                    WorkspaceMembershipRecord.workspace_id == seed.workspace_id,
                    WorkspaceMembershipRecord.user_id == seed.user.id,
                )
            )
            assert stale_member is not None and stale_member.can_delete
            async with sessions.begin() as revoking_session:
                await revoking_session.execute(
                    update(WorkspaceMembershipRecord)
                    .where(
                        WorkspaceMembershipRecord.workspace_id == seed.workspace_id,
                        WorkspaceMembershipRecord.user_id == seed.user.id,
                    )
                    .values(can_delete=False)
                )
            assert stale_member.can_delete
            with pytest.raises(AppError) as denied:
                await require_workspace_delete(
                    stale_session, seed.user.id, seed.workspace_id
                )
            assert denied.value.code == "not_found" and denied.value.status_code == 404
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_locked_delete_check_serializes_membership_revocation(
    database: IsolatedPublishingDatabase,
) -> None:
    seed = await seed_original(database.database_url)
    engine = create_async_engine(database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    lock_acquired = asyncio.Event()
    release_lock = asyncio.Event()
    revocation_started = asyncio.Event()
    revocation_finished = asyncio.Event()
    try:
        async with sessions.begin() as session:
            await session.execute(
                update(WorkspaceRecord)
                .where(WorkspaceRecord.id == seed.workspace_id)
                .values(kind=WorkspaceKind.COMPANY, expires_at=None)
            )
            await session.execute(
                update(WorkspaceMembershipRecord)
                .where(
                    WorkspaceMembershipRecord.workspace_id == seed.workspace_id,
                    WorkspaceMembershipRecord.user_id == seed.user.id,
                )
                .values(
                    role=MembershipRole.MEMBER,
                    can_read=True,
                    can_write=False,
                    can_delete=True,
                )
            )

        async def hold_delete_lock() -> None:
            async with sessions.begin() as session:
                await require_workspace_delete(
                    session, seed.user.id, seed.workspace_id, lock=True
                )
                lock_acquired.set()
                await asyncio.wait_for(release_lock.wait(), 15)

        async def revoke_delete() -> None:
            await asyncio.wait_for(lock_acquired.wait(), 15)
            revocation_started.set()
            async with sessions.begin() as session:
                await session.execute(
                    update(WorkspaceMembershipRecord)
                    .where(
                        WorkspaceMembershipRecord.workspace_id == seed.workspace_id,
                        WorkspaceMembershipRecord.user_id == seed.user.id,
                    )
                    .values(can_delete=False)
                )
            revocation_finished.set()

        holder = asyncio.create_task(hold_delete_lock())
        revoker = asyncio.create_task(revoke_delete())
        try:
            await asyncio.wait_for(lock_acquired.wait(), 15)
            await asyncio.wait_for(revocation_started.wait(), 15)
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(revocation_finished.wait(), 0.2)
            release_lock.set()
            await asyncio.wait_for(asyncio.gather(holder, revoker), 15)
        finally:
            release_lock.set()
            for task in (holder, revoker):
                if not task.done():
                    task.cancel()
            await asyncio.gather(holder, revoker, return_exceptions=True)

        async with sessions.begin() as session:
            with pytest.raises(AppError) as denied:
                await require_workspace_delete(session, seed.user.id, seed.workspace_id)
            assert denied.value.code == "not_found" and denied.value.status_code == 404
    finally:
        release_lock.set()
        await engine.dispose()


@pytest.mark.asyncio
async def test_locked_temporary_delete_rechecks_expiry_after_workspace_lock(
    database: IsolatedPublishingDatabase,
) -> None:
    seed = await seed_original(database.database_url)
    engine = create_async_engine(database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    lock_acquired = asyncio.Event()
    expire_requested = asyncio.Event()
    expiry_updated = asyncio.Event()
    release_lock = asyncio.Event()
    authorization_started = asyncio.Event()
    blocker_pid: int | None = None
    authorization_pid: int | None = None
    try:
        async with sessions.begin() as session:
            await session.execute(
                update(WorkspaceMembershipRecord)
                .where(
                    WorkspaceMembershipRecord.workspace_id == seed.workspace_id,
                    WorkspaceMembershipRecord.user_id == seed.user.id,
                )
                .values(role=MembershipRole.OWNER)
            )

        async def hold_workspace_lock_and_expire() -> None:
            nonlocal blocker_pid
            async with sessions.begin() as session:
                blocker_pid = await session.scalar(select(func.pg_backend_pid()))
                await session.scalar(
                    select(WorkspaceRecord.id)
                    .where(WorkspaceRecord.id == seed.workspace_id)
                    .with_for_update()
                )
                lock_acquired.set()
                await asyncio.wait_for(expire_requested.wait(), 15)
                await session.execute(
                    update(WorkspaceRecord)
                    .where(WorkspaceRecord.id == seed.workspace_id)
                    .values(expires_at=datetime.now(UTC))
                )
                expiry_updated.set()
                await asyncio.wait_for(release_lock.wait(), 15)

        async def authorize_delete() -> AppError | None:
            nonlocal authorization_pid
            try:
                async with sessions.begin() as session:
                    authorization_pid = await session.scalar(select(func.pg_backend_pid()))
                    authorization_started.set()
                    await require_workspace_delete(
                        session, seed.user.id, seed.workspace_id, lock=True
                    )
            except AppError as error:
                return error
            return None

        holder = asyncio.create_task(hold_workspace_lock_and_expire())
        authorizer = asyncio.create_task(authorize_delete())
        try:
            await asyncio.wait_for(lock_acquired.wait(), 15)
            await asyncio.wait_for(authorization_started.wait(), 15)
            assert blocker_pid is not None and authorization_pid is not None
            async with sessions() as observer:
                await _wait_for_database_blocker(
                    observer, authorization_pid, blocker_pid
                )
            expire_requested.set()
            await asyncio.wait_for(expiry_updated.wait(), 15)
            release_lock.set()
            error = await asyncio.wait_for(authorizer, 15)
            await asyncio.wait_for(holder, 15)
            assert error is not None
            assert error.code == "not_found" and error.status_code == 404
        finally:
            expire_requested.set()
            release_lock.set()
            for task in (holder, authorizer):
                if not task.done():
                    task.cancel()
            await asyncio.gather(holder, authorizer, return_exceptions=True)
    finally:
        expire_requested.set()
        release_lock.set()
        await engine.dispose()
