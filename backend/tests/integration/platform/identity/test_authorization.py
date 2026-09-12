from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID, uuid4

import psycopg
import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_workshop.platform.identity.authorization import (
    Capability,
    TechnologyDefinition,
    TechnologyRegistry,
)
from ai_workshop.platform.identity.authorization_repository import (
    SqlAlchemyAuthorizationRepository,
)
from ai_workshop.platform.identity.authorization_service import AuthorizationService
from ai_workshop.platform.identity.domain import User, UserRole
from ai_workshop.platform.identity.repository import SqlAlchemyUserRepository
from ai_workshop.shared.errors import AppError
from alembic import command
from tests.integration.publishing_support import (
    IsolatedPublishingDatabase,
    isolated_publishing_database,
)

pytestmark = pytest.mark.integration


def sync_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def seed_user(
    database: IsolatedPublishingDatabase,
    *,
    role: str,
    is_active: bool = True,
) -> UUID:
    user_id = uuid4()
    email = f"{user_id.hex}@example.test"
    with psycopg.connect(sync_url(database.database_url)) as connection:
        connection.execute(
            """
            INSERT INTO users (
                id, display_name, email, normalized_email, password_hash, role, is_active
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (user_id, "Synthetic User", email, email, "synthetic-hash", role, is_active),
        )
        connection.commit()
    return user_id


@contextmanager
def migrated_database(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[IsolatedPublishingDatabase]:
    with isolated_publishing_database(monkeypatch) as database:
        command.upgrade(database.config, "0029_codex_verification")
        command.upgrade(database.config, "0030_technology_permissions")
        yield database


def test_empty_migration_seeds_closed_uninitialized_state_and_named_constraints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with (
        migrated_database(monkeypatch) as database,
        psycopg.connect(sync_url(database.database_url)) as connection,
    ):
        assert connection.execute("SELECT id, initialized FROM authorization_state").fetchall() == [
            (1, False)
        ]
        assert connection.execute("SELECT COUNT(*) FROM user_authorization_states").fetchone() == (
            0,
        )
        constraints = {
            row[0]
            for row in connection.execute(
                """
                    SELECT c.conname
                    FROM pg_constraint c
                    JOIN pg_class t ON t.oid = c.conrelid
                    WHERE t.relname IN (
                        'authorization_state',
                        'user_authorization_states',
                        'technology_grants',
                        'authority_audit'
                    )
                    """
            ).fetchall()
        }
        assert {
            "ck_authorization_state_singleton",
            "ck_user_authorization_revision_nonnegative",
            "ck_technology_grant_view_prerequisite",
            "ck_technology_grant_nonempty",
            "pk_user_authorization_states",
            "pk_technology_grants",
        } <= constraints


def test_legacy_migration_backfills_revision_zero_without_grants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with isolated_publishing_database(monkeypatch) as database:
        command.upgrade(database.config, "0029_codex_verification")
        owner_id = seed_user(database, role="owner")
        member_id = seed_user(database, role="member")

        command.upgrade(database.config, "0030_technology_permissions")

        with psycopg.connect(sync_url(database.database_url)) as connection:
            assert connection.execute(
                "SELECT initialized FROM authorization_state WHERE id = 1"
            ).fetchone() == (True,)
            assert set(
                connection.execute(
                    "SELECT user_id, revision FROM user_authorization_states"
                ).fetchall()
            ) == {(owner_id, 0), (member_id, 0)}
            assert connection.execute("SELECT COUNT(*) FROM technology_grants").fetchone() == (0,)


@pytest.mark.parametrize(
    ("role", "is_active", "error"),
    [
        ("unexpected", True, "invalid_user_role_state"),
        ("owner", False, "active_owner_required"),
        ("member", True, "active_owner_required"),
    ],
)
def test_legacy_migration_fails_without_repairing_invalid_authority_state(
    monkeypatch: pytest.MonkeyPatch,
    role: str,
    is_active: bool,
    error: str,
) -> None:
    with isolated_publishing_database(monkeypatch) as database:
        command.upgrade(database.config, "0029_codex_verification")
        seed_user(database, role=role, is_active=is_active)

        with pytest.raises(RuntimeError, match=error):
            command.upgrade(database.config, "0030_technology_permissions")


def test_database_constraints_reject_capability_without_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with (
        migrated_database(monkeypatch) as database,
        psycopg.connect(sync_url(database.database_url)) as connection,
    ):
        connection.execute("UPDATE authorization_state SET initialized = TRUE WHERE id = 1")
        member_id = seed_user(database, role="member")
        connection.execute(
            "INSERT INTO user_authorization_states (user_id, revision) VALUES (%s, 0)",
            (member_id,),
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                """
                    INSERT INTO technology_grants (
                        user_id, technology_key, can_view, can_configure, can_execute
                    ) VALUES (%s, 'rag', FALSE, TRUE, FALSE)
                    """,
                (member_id,),
            )


def test_empty_migration_can_downgrade_but_changed_authority_state_blocks_data_loss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with migrated_database(monkeypatch) as database:
        command.downgrade(database.config, "0029_codex_verification")
        with psycopg.connect(sync_url(database.database_url)) as connection:
            assert connection.execute(
                "SELECT to_regclass('public.authorization_state')"
            ).fetchone() == (None,)

    with migrated_database(monkeypatch) as database:
        with psycopg.connect(sync_url(database.database_url)) as connection:
            connection.execute("UPDATE authorization_state SET initialized = TRUE WHERE id = 1")
            connection.execute(
                """
                INSERT INTO users (
                    id, display_name, email, normalized_email, password_hash, role, is_active
                ) VALUES (%s, 'Synthetic', 'owner@example.test', 'owner@example.test',
                          'synthetic-hash', 'owner', TRUE)
                """,
                (uuid4(),),
            )
            user_id = connection.execute(
                "SELECT id FROM users WHERE normalized_email = 'owner@example.test'"
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO user_authorization_states (user_id, revision) VALUES (%s, 1)",
                (user_id,),
            )
            connection.commit()

        with pytest.raises(RuntimeError, match="technology_authorization_records_exist"):
            command.downgrade(database.config, "0029_codex_verification")


def registry() -> TechnologyRegistry:
    return TechnologyRegistry((TechnologyDefinition(key="rag", label="RAG"),))


async def insert_authority_users(
    database_url: str,
    users: list[tuple[UUID, UserRole, bool]],
) -> None:
    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions.begin() as session:
        for user_id, role, is_active in users:
            email = f"{user_id.hex}@example.test"
            await session.execute(
                text(
                    """
                    INSERT INTO users (
                        id, display_name, email, normalized_email, password_hash, role, is_active
                    ) VALUES (:id, :name, :email, :email, 'synthetic-hash', :role, :active)
                    """
                ),
                {
                    "id": user_id,
                    "name": f"Synthetic {user_id.hex[:6]}",
                    "email": email,
                    "role": role.value,
                    "active": is_active,
                },
            )
            await session.execute(
                text("INSERT INTO user_authorization_states (user_id, revision) VALUES (:id, 0)"),
                {"id": user_id},
            )
        await session.execute(
            text("UPDATE authorization_state SET initialized = TRUE WHERE id = 1")
        )
    await engine.dispose()


def test_two_masters_racing_to_demote_each_other_leave_one_active_master(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with migrated_database(monkeypatch) as database:

        async def run_case() -> None:
            first, second = uuid4(), uuid4()
            await insert_authority_users(
                database.database_url,
                [(first, UserRole.OWNER, True), (second, UserRole.OWNER, True)],
            )
            engine = create_async_engine(database.database_url)
            sessions = async_sessionmaker(engine, expire_on_commit=False)

            async def demote(actor_id: UUID, target_id: UUID) -> object:
                try:
                    async with sessions.begin() as session:
                        service = AuthorizationService(
                            SqlAlchemyAuthorizationRepository(session), registry()
                        )
                        return await service.set_role(
                            actor_id,
                            target_id,
                            UserRole.MEMBER,
                            expected_revision=0,
                        )
                except Exception as exc:  # result is asserted below
                    return exc

            results = await asyncio.gather(demote(first, second), demote(second, first))

            assert sum(not isinstance(result, Exception) for result in results) == 1
            async with sessions() as session:
                assert await SqlAlchemyAuthorizationRepository(session).count_active_masters() == 1
            await engine.dispose()

        asyncio.run(run_case())


def test_rollback_discards_grant_revision_and_audit_atomically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with migrated_database(monkeypatch) as database:

        async def run_case() -> None:
            owner, member = uuid4(), uuid4()
            await insert_authority_users(
                database.database_url,
                [(owner, UserRole.OWNER, True), (member, UserRole.MEMBER, True)],
            )
            engine = create_async_engine(database.database_url)
            sessions = async_sessionmaker(engine, expire_on_commit=False)

            with pytest.raises(RuntimeError, match="force rollback"):
                async with sessions.begin() as session:
                    service = AuthorizationService(
                        SqlAlchemyAuthorizationRepository(session), registry()
                    )
                    await service.set_grant(
                        owner,
                        member,
                        "rag",
                        frozenset({Capability.VIEW}),
                        expected_revision=0,
                    )
                    raise RuntimeError("force rollback")

            async with sessions() as session:
                repository = SqlAlchemyAuthorizationRepository(session)
                stored = await repository.get_authority(member)
                assert stored is not None
                assert stored.revision == 0
                assert stored.grants == {}
                assert await repository.list_audit(member, None, 10) == []
            await engine.dispose()

        asyncio.run(run_case())


def test_grant_waiting_behind_actor_demotion_uses_fresh_post_lock_actor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with migrated_database(monkeypatch) as database:

        async def run_case() -> None:
            actor, other_master, member = uuid4(), uuid4(), uuid4()
            await insert_authority_users(
                database.database_url,
                [
                    (actor, UserRole.OWNER, True),
                    (other_master, UserRole.OWNER, True),
                    (member, UserRole.MEMBER, True),
                ],
            )
            engine = create_async_engine(database.database_url)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            attempted = asyncio.Event()

            class SignalingRepository(SqlAlchemyAuthorizationRepository):
                async def lock_authorization_state(self) -> None:
                    attempted.set()
                    await super().lock_authorization_state()

            async def grant_after_lock() -> object:
                try:
                    async with sessions.begin() as session:
                        return await AuthorizationService(
                            SignalingRepository(session), registry()
                        ).set_grant(
                            actor,
                            member,
                            "rag",
                            frozenset({Capability.VIEW}),
                            expected_revision=0,
                        )
                except Exception as exc:  # asserted below
                    return exc

            async with sessions.begin() as demotion_session:
                demotion_repository = SqlAlchemyAuthorizationRepository(demotion_session)
                await demotion_repository.lock_authorization_state()
                grant_task = asyncio.create_task(grant_after_lock())
                await attempted.wait()
                await AuthorizationService(demotion_repository, registry()).set_role(
                    other_master,
                    actor,
                    UserRole.MEMBER,
                    expected_revision=0,
                )

            result = await grant_task
            assert isinstance(result, AppError)
            assert result.status_code == 403
            async with sessions() as session:
                stored = await SqlAlchemyAuthorizationRepository(session).get_authority(member)
                assert stored is not None
                assert stored.grants == {}
                assert stored.revision == 0
            await engine.dispose()

        asyncio.run(run_case())


def test_sql_stale_revision_promotion_clear_and_bounded_pagination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with migrated_database(monkeypatch) as database:

        async def run_case() -> None:
            owner, member, later_member = uuid4(), uuid4(), uuid4()
            await insert_authority_users(
                database.database_url,
                [
                    (owner, UserRole.OWNER, True),
                    (member, UserRole.MEMBER, True),
                    (later_member, UserRole.MEMBER, True),
                ],
            )
            engine = create_async_engine(database.database_url)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            async with sessions.begin() as session:
                service = AuthorizationService(
                    SqlAlchemyAuthorizationRepository(session), registry()
                )
                granted = await service.set_grant(
                    owner,
                    member,
                    "rag",
                    frozenset({Capability.VIEW}),
                    expected_revision=0,
                )
                assert granted.revision == 1
                unchanged = await service.set_grant(
                    owner,
                    member,
                    "rag",
                    frozenset({Capability.VIEW}),
                    expected_revision=1,
                )
                assert unchanged.revision == 1
                with pytest.raises(AppError) as stale:
                    await service.set_status(owner, member, False, expected_revision=0)
                assert stale.value.status_code == 409
                promoted = await service.set_role(
                    owner,
                    member,
                    UserRole.OWNER,
                    expected_revision=1,
                )
                assert promoted.revision == 2
                assert promoted.technologies[0].capabilities == tuple(Capability)

            async with sessions() as session:
                repository = SqlAlchemyAuthorizationRepository(session)
                stored = await repository.get_authority(member)
                assert stored is not None
                assert stored.grants == {}
                audits = await repository.list_audit(member, None, 10)
                assert [item.event_type for item in audits] == [
                    "user_role_changed",
                    "technology_grant_changed",
                ]
                page = await AuthorizationService(repository, registry()).list_users(
                    owner, cursor=None, limit=2
                )
                assert len(page.items) == 2
                assert page.next_cursor == page.items[-1].id
                next_page = await AuthorizationService(repository, registry()).list_users(
                    owner, cursor=page.next_cursor, limit=2
                )
                assert len(next_page.items) == 1
                assert next_page.next_cursor is None
                with pytest.raises(AppError) as unknown:
                    await AuthorizationService(repository, registry()).require_capability(
                        owner, "unknown", Capability.VIEW
                    )
                assert unknown.value.status_code == 403
            await engine.dispose()

        asyncio.run(run_case())


def test_setup_bootstrap_marks_initialized_audits_and_never_reopens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with migrated_database(monkeypatch) as database:

        async def run_case() -> None:
            engine = create_async_engine(database.database_url)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            owner = User.create_owner(
                display_name="Synthetic Owner",
                email="owner@example.test",
                password_hash="synthetic-hash",
            )
            async with sessions.begin() as session:
                repository = SqlAlchemyUserRepository(session)
                assert await repository.owner_setup_required() is True
                await repository.lock_owner_setup()
                await repository.add(owner)
                await repository.complete_owner_setup(owner.id)

            async with sessions.begin() as session:
                await session.execute(
                    text("UPDATE users SET is_active = FALSE WHERE id = :id"),
                    {"id": owner.id},
                )
            async with sessions() as session:
                repository = SqlAlchemyUserRepository(session)
                assert await repository.owner_setup_required() is False
                with pytest.raises(AppError) as closed:
                    await repository.lock_owner_setup()
                assert closed.value.code == "setup_already_completed"
                audits = await SqlAlchemyAuthorizationRepository(session).list_audit(
                    owner.id, None, 10
                )
                assert len(audits) == 1
                assert audits[0].event_type == "authorization_bootstrap"
                assert audits[0].actor_id is None

            with pytest.raises(DBAPIError, match="authority_audit_append_only"):
                async with sessions.begin() as session:
                    await session.execute(
                        text("UPDATE authority_audit SET event_type = 'tampered'")
                    )

            async with sessions.begin() as session:
                await session.execute(text("DELETE FROM authorization_state WHERE id = 1"))
            async with sessions() as session:
                repository = SqlAlchemyUserRepository(session)
                assert await repository.owner_setup_required() is False
                with pytest.raises(AppError) as missing:
                    await repository.lock_owner_setup()
                assert missing.value.code == "authorization_migration_required"
                with pytest.raises(AppError) as authorization_read:
                    await SqlAlchemyAuthorizationRepository(session).get_authority(owner.id)
                assert authorization_read.value.code == "authorization_migration_required"
            await engine.dispose()

        asyncio.run(run_case())


def test_authority_detail_and_directory_never_mix_read_committed_snapshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with migrated_database(monkeypatch) as database:

        async def run_case() -> None:
            owner, member = uuid4(), uuid4()
            await insert_authority_users(
                database.database_url,
                [(owner, UserRole.OWNER, True), (member, UserRole.MEMBER, True)],
            )
            engine = create_async_engine(database.database_url)
            sessions = async_sessionmaker(engine, expire_on_commit=False)

            old_snapshot = (UserRole.MEMBER, True, 0, {})
            new_snapshot = (
                UserRole.MEMBER,
                False,
                1,
                {"rag": frozenset({Capability.VIEW})},
            )

            def commit_competing_change() -> None:
                with psycopg.connect(sync_url(database.database_url)) as connection:
                    connection.execute(
                        "UPDATE users SET is_active = FALSE WHERE id = %s",
                        (member,),
                    )
                    connection.execute(
                        "UPDATE user_authorization_states SET revision = 1 WHERE user_id = %s",
                        (member,),
                    )
                    connection.execute(
                        """
                        INSERT INTO technology_grants (
                            user_id, technology_key, can_view, can_configure, can_execute
                        ) VALUES (%s, 'rag', TRUE, FALSE, FALSE)
                        """,
                        (member,),
                    )
                    connection.commit()

            detail_interleaved = False

            def interleave_detail(
                _connection: object,
                _cursor: object,
                statement: str,
                _parameters: object,
                _context: object,
                _executemany: bool,
            ) -> None:
                nonlocal detail_interleaved
                if detail_interleaved or "FROM users" not in statement:
                    return
                detail_interleaved = True
                commit_competing_change()

            event.listen(engine.sync_engine, "after_cursor_execute", interleave_detail)
            try:
                async with sessions() as session:
                    detail = await SqlAlchemyAuthorizationRepository(session).get_authority(member)
            finally:
                event.remove(engine.sync_engine, "after_cursor_execute", interleave_detail)

            assert detail_interleaved is True
            assert detail is not None
            assert (detail.role, detail.is_active, detail.revision, detail.grants) in (
                old_snapshot,
                new_snapshot,
            )

            with psycopg.connect(sync_url(database.database_url)) as connection:
                connection.execute(
                    "UPDATE users SET is_active = TRUE WHERE id = %s",
                    (member,),
                )
                connection.execute(
                    "UPDATE user_authorization_states SET revision = 0 WHERE user_id = %s",
                    (member,),
                )
                connection.execute(
                    "DELETE FROM technology_grants WHERE user_id = %s",
                    (member,),
                )
                connection.commit()

            directory_interleaved = False

            def interleave_directory(
                _connection: object,
                _cursor: object,
                statement: str,
                _parameters: object,
                _context: object,
                _executemany: bool,
            ) -> None:
                nonlocal directory_interleaved
                if (
                    directory_interleaved
                    or "user_authorization_states" not in statement
                ):
                    return
                directory_interleaved = True
                commit_competing_change()

            event.listen(engine.sync_engine, "after_cursor_execute", interleave_directory)
            try:
                async with sessions() as session:
                    directory = await SqlAlchemyAuthorizationRepository(
                        session
                    ).list_authorities(None, 10)
            finally:
                event.remove(
                    engine.sync_engine,
                    "after_cursor_execute",
                    interleave_directory,
                )

            assert directory_interleaved is True
            listed_member = next(item for item in directory if item.id == member)
            assert (
                listed_member.role,
                listed_member.is_active,
                listed_member.revision,
                listed_member.grants,
            ) in (old_snapshot, new_snapshot)
            await engine.dispose()

        asyncio.run(run_case())
