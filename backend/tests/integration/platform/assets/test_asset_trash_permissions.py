"""PostgreSQL authorization regressions for asset trash actions."""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ai_workshop.platform.assets.trash_authorization import require_trash_action
from ai_workshop.platform.assets.trash_policy import TrashAction
from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.platform.workspaces.domain import MembershipRole, WorkspaceKind
from ai_workshop.platform.workspaces.models import WorkspaceMembershipRecord, WorkspaceRecord
from ai_workshop.platform.workspaces.permissions import workspace_delete_allowed
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


async def _configure_workspace(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    actor_id: UUID,
    kind: WorkspaceKind,
    role: MembershipRole,
    can_read: bool,
    can_write: bool,
    can_delete: bool,
    expires_at: datetime | None = None,
) -> None:
    await session.execute(
        update(WorkspaceRecord)
        .where(WorkspaceRecord.id == workspace_id)
        .values(kind=kind, expires_at=expires_at)
    )
    await session.execute(
        update(WorkspaceMembershipRecord)
        .where(
            WorkspaceMembershipRecord.workspace_id == workspace_id,
            WorkspaceMembershipRecord.user_id == actor_id,
        )
        .values(
            role=role,
            can_read=can_read,
            can_write=can_write,
            can_delete=can_delete,
        )
    )


async def _sql_delete_allowed(
    session: AsyncSession, actor_id: UUID, workspace_id: UUID
) -> bool:
    found = await session.scalar(
        select(WorkspaceRecord.id).where(
            WorkspaceRecord.id == workspace_id,
            workspace_delete_allowed(actor_id),
        )
    )
    return found is not None


async def _assert_denied(
    session: AsyncSession, actor_id: UUID, workspace_id: UUID, action: TrashAction
) -> None:
    with pytest.raises(AppError) as denied:
        await require_trash_action(session, actor_id, workspace_id, action)
    assert denied.value.code == "not_found"
    assert denied.value.status_code == 404


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
    ("can_read", "can_write", "can_delete", "expected_caps", "expected_actions"),
    [
        (False, False, False, None, (False, False, False, False)),
        (True, False, False, (True, False, False, False), (False, False, False, False)),
        (True, True, False, (True, True, False, False), (False, False, False, False)),
        (True, False, True, (True, False, True, False), (True, True, False, True)),
        (True, True, True, (True, True, True, False), (True, True, True, True)),
    ],
)
async def test_company_valid_grants_match_sql_delete_and_each_trash_action(
    database: IsolatedPublishingDatabase,
    can_read: bool,
    can_write: bool,
    can_delete: bool,
    expected_caps: tuple[bool, bool, bool, bool] | None,
    expected_actions: tuple[bool, bool, bool, bool],
) -> None:
    seed = await seed_original(database.database_url)
    engine = create_async_engine(database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            await _configure_workspace(
                session,
                workspace_id=seed.workspace_id,
                actor_id=seed.user.id,
                kind=WorkspaceKind.COMPANY,
                role=MembershipRole.MEMBER,
                can_read=can_read,
                can_write=can_write,
                can_delete=can_delete,
            )
        async with sessions.begin() as session:
            assert await _sql_delete_allowed(session, seed.user.id, seed.workspace_id) is can_delete
            for action, expected in zip(TrashAction, expected_actions, strict=True):
                if not expected:
                    await _assert_denied(session, seed.user.id, seed.workspace_id, action)
                    continue
                caps = await require_trash_action(session, seed.user.id, seed.workspace_id, action)
                assert (caps.read, caps.write, caps.delete, caps.manage_members) == expected_caps
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_company_owner_allows_every_trash_action_without_stored_grants(
    database: IsolatedPublishingDatabase,
) -> None:
    seed = await seed_original(database.database_url)
    engine = create_async_engine(database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            await _configure_workspace(
                session,
                workspace_id=seed.workspace_id,
                actor_id=seed.user.id,
                kind=WorkspaceKind.COMPANY,
                role=MembershipRole.OWNER,
                can_read=False,
                can_write=False,
                can_delete=False,
            )
        async with sessions.begin() as session:
            assert await _sql_delete_allowed(session, seed.user.id, seed.workspace_id)
            for action in TrashAction:
                caps = await require_trash_action(session, seed.user.id, seed.workspace_id, action)
                assert (caps.read, caps.write, caps.delete, caps.manage_members) == (
                    True,
                    True,
                    True,
                    True,
                )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_personal_creator_is_allowed_but_foreign_member_is_hidden(
    database: IsolatedPublishingDatabase,
) -> None:
    seed = await seed_original(database.database_url)
    engine = create_async_engine(database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            await _configure_workspace(
                session,
                workspace_id=seed.workspace_id,
                actor_id=seed.user.id,
                kind=WorkspaceKind.PERSONAL,
                role=MembershipRole.MEMBER,
                can_read=False,
                can_write=False,
                can_delete=False,
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
            caps = await require_trash_action(
                session, seed.user.id, seed.workspace_id, TrashAction.RESTORE
            )
            assert (caps.read, caps.write, caps.delete) == (True, True, True)
            assert await _sql_delete_allowed(session, seed.user.id, seed.workspace_id)
            assert not await _sql_delete_allowed(
                session, seed.foreign_user_id, seed.workspace_id
            )
            await _assert_denied(
                session, seed.foreign_user_id, seed.workspace_id, TrashAction.LIST
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "role", "expected"),
    [
        (WorkspaceKind.TEAM, MembershipRole.OWNER, True),
        (WorkspaceKind.TEAM, MembershipRole.MEMBER, False),
        (WorkspaceKind.TEMPORARY, MembershipRole.OWNER, True),
        (WorkspaceKind.TEMPORARY, MembershipRole.MEMBER, False),
    ],
)
async def test_legacy_workspace_delete_requires_owner(
    database: IsolatedPublishingDatabase,
    kind: WorkspaceKind,
    role: MembershipRole,
    expected: bool,
) -> None:
    seed = await seed_original(database.database_url)
    engine = create_async_engine(database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    expires_at = datetime.now(UTC) + timedelta(hours=1) if kind is WorkspaceKind.TEMPORARY else None
    try:
        async with sessions.begin() as session:
            await _configure_workspace(
                session,
                workspace_id=seed.workspace_id,
                actor_id=seed.user.id,
                kind=kind,
                role=role,
                can_read=True,
                can_write=True,
                can_delete=True,
                expires_at=expires_at,
            )
        async with sessions.begin() as session:
            assert await _sql_delete_allowed(session, seed.user.id, seed.workspace_id) is expected
            if expected:
                caps = await require_trash_action(
                    session, seed.user.id, seed.workspace_id, TrashAction.PURGE
                )
                assert (caps.read, caps.write, caps.delete) == (True, True, True)
            else:
                await _assert_denied(
                    session, seed.user.id, seed.workspace_id, TrashAction.PURGE
                )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(("expired", "inactive"), [(True, False), (False, True)])
async def test_expired_workspace_or_inactive_actor_is_hidden(
    database: IsolatedPublishingDatabase,
    expired: bool,
    inactive: bool,
) -> None:
    seed = await seed_original(database.database_url)
    engine = create_async_engine(database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            await _configure_workspace(
                session,
                workspace_id=seed.workspace_id,
                actor_id=seed.user.id,
                kind=WorkspaceKind.TEMPORARY,
                role=MembershipRole.OWNER,
                can_read=True,
                can_write=True,
                can_delete=True,
                expires_at=datetime.now(UTC)
                + (timedelta(hours=-1) if expired else timedelta(hours=1)),
            )
            if inactive:
                await session.execute(
                    update(UserRecord).where(UserRecord.id == seed.user.id).values(is_active=False)
                )
        async with sessions.begin() as session:
            assert not await _sql_delete_allowed(session, seed.user.id, seed.workspace_id)
            await _assert_denied(session, seed.user.id, seed.workspace_id, TrashAction.LIST)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_unknown_trash_action_is_hidden(
    database: IsolatedPublishingDatabase,
) -> None:
    seed = await seed_original(database.database_url)
    engine = create_async_engine(database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            await _configure_workspace(
                session,
                workspace_id=seed.workspace_id,
                actor_id=seed.user.id,
                kind=WorkspaceKind.COMPANY,
                role=MembershipRole.OWNER,
                can_read=False,
                can_write=False,
                can_delete=False,
            )
        async with sessions.begin() as session:
            await _assert_denied(
                session,
                seed.user.id,
                seed.workspace_id,
                cast(TrashAction, "archive"),
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_trash_action_uses_current_grants_instead_of_stale_identity_map(
    database: IsolatedPublishingDatabase,
) -> None:
    seed = await seed_original(database.database_url)
    engine = create_async_engine(database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            await _configure_workspace(
                session,
                workspace_id=seed.workspace_id,
                actor_id=seed.user.id,
                kind=WorkspaceKind.COMPANY,
                role=MembershipRole.MEMBER,
                can_read=True,
                can_write=False,
                can_delete=True,
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
            await _assert_denied(
                stale_session, seed.user.id, seed.workspace_id, TrashAction.TRASH
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_list_checks_current_grants_without_holding_membership_lock(
    database: IsolatedPublishingDatabase,
) -> None:
    seed = await seed_original(database.database_url)
    engine = create_async_engine(database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            await _configure_workspace(
                session,
                workspace_id=seed.workspace_id,
                actor_id=seed.user.id,
                kind=WorkspaceKind.COMPANY,
                role=MembershipRole.MEMBER,
                can_read=True,
                can_write=False,
                can_delete=True,
            )
        async with sessions.begin() as listing_session:
            await require_trash_action(
                listing_session, seed.user.id, seed.workspace_id, TrashAction.LIST
            )
            async with sessions.begin() as revoking_session:
                await asyncio.wait_for(
                    revoking_session.execute(
                        update(WorkspaceMembershipRecord)
                        .where(
                            WorkspaceMembershipRecord.workspace_id == seed.workspace_id,
                            WorkspaceMembershipRecord.user_id == seed.user.id,
                        )
                        .values(can_delete=False)
                    ),
                    2,
                )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_mutating_action_rechecks_revoked_grant_after_waiting_for_lock(
    database: IsolatedPublishingDatabase,
) -> None:
    seed = await seed_original(database.database_url)
    engine = create_async_engine(database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    blocker_pid: int | None = None
    authorization_pid: int | None = None
    lock_acquired = asyncio.Event()
    revoke_requested = asyncio.Event()
    revocation_finished = asyncio.Event()
    release_lock = asyncio.Event()
    authorization_started = asyncio.Event()
    try:
        async with sessions.begin() as session:
            await _configure_workspace(
                session,
                workspace_id=seed.workspace_id,
                actor_id=seed.user.id,
                kind=WorkspaceKind.COMPANY,
                role=MembershipRole.MEMBER,
                can_read=True,
                can_write=False,
                can_delete=True,
            )

        async def hold_workspace_lock_and_revoke() -> None:
            nonlocal blocker_pid
            async with sessions.begin() as session:
                blocker_pid = await session.scalar(select(func.pg_backend_pid()))
                await session.scalar(
                    select(WorkspaceRecord.id)
                    .where(WorkspaceRecord.id == seed.workspace_id)
                    .with_for_update()
                )
                lock_acquired.set()
                await asyncio.wait_for(revoke_requested.wait(), 15)
                await session.execute(
                    update(WorkspaceMembershipRecord)
                    .where(
                        WorkspaceMembershipRecord.workspace_id == seed.workspace_id,
                        WorkspaceMembershipRecord.user_id == seed.user.id,
                    )
                    .values(can_delete=False)
                )
                revocation_finished.set()
                await asyncio.wait_for(release_lock.wait(), 15)

        async def authorize_trash() -> AppError | None:
            nonlocal authorization_pid
            try:
                async with sessions.begin() as session:
                    authorization_pid = await session.scalar(select(func.pg_backend_pid()))
                    authorization_started.set()
                    await require_trash_action(
                        session, seed.user.id, seed.workspace_id, TrashAction.TRASH
                    )
            except AppError as error:
                return error
            return None

        holder = asyncio.create_task(hold_workspace_lock_and_revoke())
        authorizer = asyncio.create_task(authorize_trash())
        try:
            await asyncio.wait_for(lock_acquired.wait(), 15)
            await asyncio.wait_for(authorization_started.wait(), 15)
            assert blocker_pid is not None and authorization_pid is not None
            async with sessions() as observer:
                await _wait_for_database_blocker(observer, authorization_pid, blocker_pid)
            revoke_requested.set()
            await asyncio.wait_for(revocation_finished.wait(), 15)
            release_lock.set()
            error = await asyncio.wait_for(authorizer, 15)
            await asyncio.wait_for(holder, 15)
            assert error is not None
            assert error.code == "not_found" and error.status_code == 404
        finally:
            revoke_requested.set()
            release_lock.set()
            for task in (holder, authorizer):
                if not task.done():
                    task.cancel()
            await asyncio.gather(holder, authorizer, return_exceptions=True)
    finally:
        revoke_requested.set()
        release_lock.set()
        await engine.dispose()


@pytest.mark.asyncio
async def test_mutating_action_rechecks_expiry_after_waiting_for_workspace_lock(
    database: IsolatedPublishingDatabase,
) -> None:
    seed = await seed_original(database.database_url)
    engine = create_async_engine(database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    blocker_pid: int | None = None
    authorization_pid: int | None = None
    lock_acquired = asyncio.Event()
    expire_requested = asyncio.Event()
    expiry_updated = asyncio.Event()
    release_lock = asyncio.Event()
    authorization_started = asyncio.Event()
    try:
        async with sessions.begin() as session:
            await _configure_workspace(
                session,
                workspace_id=seed.workspace_id,
                actor_id=seed.user.id,
                kind=WorkspaceKind.TEMPORARY,
                role=MembershipRole.OWNER,
                can_read=True,
                can_write=True,
                can_delete=True,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
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

        async def authorize_purge() -> AppError | None:
            nonlocal authorization_pid
            try:
                async with sessions.begin() as session:
                    authorization_pid = await session.scalar(select(func.pg_backend_pid()))
                    authorization_started.set()
                    await require_trash_action(
                        session, seed.user.id, seed.workspace_id, TrashAction.PURGE
                    )
            except AppError as error:
                return error
            return None

        holder = asyncio.create_task(hold_workspace_lock_and_expire())
        authorizer = asyncio.create_task(authorize_purge())
        try:
            await asyncio.wait_for(lock_acquired.wait(), 15)
            await asyncio.wait_for(authorization_started.wait(), 15)
            assert blocker_pid is not None and authorization_pid is not None
            async with sessions() as observer:
                await _wait_for_database_blocker(observer, authorization_pid, blocker_pid)
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
