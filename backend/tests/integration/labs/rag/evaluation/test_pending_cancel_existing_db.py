"""Real repository/locks in task-owned tables in the existing PostgreSQL database.

No application rows are written. The explicitly named schema is retained for review;
it is outside the application's search_path and cannot enter its dispatcher queue.
"""

import asyncio
import hashlib
import importlib.util
import os
import re
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import ai_workshop.main  # noqa: F401
from ai_workshop.config import get_settings
from ai_workshop.labs.rag.evaluation.generative_models import (
    GenerativeAttemptRecord,
    GenerativeRunRecord,
)
from ai_workshop.labs.rag.evaluation.generative_repository import GenerativeRepository, canonical
from ai_workshop.shared.errors import AppError

MIGRATION = (
    Path(__file__).resolve().parents[5] / "alembic/versions/0066_generative_pending_cancel.py"
)


def migration():
    spec = importlib.util.spec_from_file_location("pending_cancel_migration", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_exists_and_is_additive():
    module = migration()
    assert module.down_revision == "0065_local_transformers"
    assert module.revision == "0066_generative_pending_cancel"


@pytest.fixture(scope="module")
def database_schema():
    if os.environ.get("AI_WORKSHOP_CANCEL_PG_TEST") != "1":
        pytest.skip("Set AI_WORKSHOP_CANCEL_PG_TEST=1 for approved existing-DB schema tests")
    schema = "cancel_test_" + uuid4().hex
    tables = (
        "rag_generative_policies",
        "rag_generative_runs",
        "rag_generative_attempts",
        "rag_executions",
        "rag_generation_execution_audits",
    )
    engine = sa.create_engine(get_settings().database_url)
    reuse = os.environ.get("AI_WORKSHOP_CANCEL_PG_SCHEMA")
    if reuse:
        assert re.fullmatch(r"cancel_test_[0-9a-f]{32}", reuse), "Unexpected test schema name"
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    sa.text(
                        "SELECT nspowner=current_user::regrole FROM pg_namespace "
                        "WHERE nspname=:schema"
                    ),
                    {"schema": reuse},
                )
                is True
            )
            assert set(
                connection.scalars(
                    sa.text("SELECT tablename FROM pg_tables WHERE schemaname=:schema"),
                    {"schema": reuse},
                )
            ) == set(tables)
            assert (
                connection.scalar(
                    sa.text(
                        "SELECT count(*) FROM information_schema.columns "
                        "WHERE table_schema=:schema "
                        "AND table_name='rag_generative_runs' AND column_name='cancelled_at'"
                    ),
                    {"schema": reuse},
                )
                == 1
            )
        engine.dispose()
        print(f"Reusing retained task-only PostgreSQL schema: {reuse}")
        return reuse
    with engine.begin() as connection:
        connection.exec_driver_sql("SET LOCAL search_path=public")
        connection.exec_driver_sql("SET LOCAL lock_timeout='3s'")
        connection.exec_driver_sql("SET LOCAL statement_timeout='15s'")
        definitions = {}
        for name in (
            "rag_generative_immutable",
            "rag_generative_run_guard",
            "rag_generative_attempt_guard",
            "rag_sync_generative_execution",
            "rag_generative_cancel_complete",
            "rag_verify_generative_candidate",
        ):
            definition = connection.scalar(
                sa.text(
                    "SELECT pg_get_functiondef(p.oid) FROM pg_proc p JOIN pg_namespace n "
                    "ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.proname=:name"
                ),
                {"name": name},
            )
            if definition:
                assert not re.search(
                    r"\bpublic\.(rag_generative_(runs|attempts|policies)|"
                    r"rag_executions|rag_generation_execution_audits)\b",
                    definition,
                ), "Guard body must not bind task writes to application tables"
                definitions[name] = definition
        triggers = list(
            connection.execute(
                sa.text(
                    "SELECT pg_get_triggerdef(t.oid) FROM pg_trigger t "
                    "JOIN pg_class c ON c.oid=t.tgrelid "
                    "JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='public' AND NOT t.tgisinternal AND c.relname IN "
                    "('rag_generative_runs','rag_generative_attempts','rag_generative_policies')"
                )
            ).scalars()
        )
        foreign_keys = list(
            connection.execute(
                sa.text(
                    "SELECT c.relname, x.conname, pg_get_constraintdef(x.oid) FROM pg_constraint x "
                    "JOIN pg_class c ON c.oid=x.conrelid "
                    "JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='public' AND x.contype='f' AND c.relname=ANY(:tables)"
                ),
                {"tables": list(tables)},
            )
        )
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        connection.exec_driver_sql(f'SET LOCAL search_path="{schema}",public')
        for table in tables:
            connection.exec_driver_sql(
                f'CREATE TABLE "{schema}".{table} (LIKE public.{table} INCLUDING ALL)'
            )
        for table, name, definition in foreign_keys:
            for owned in tables:
                definition = definition.replace(f"public.{owned}", f'"{schema}".{owned}')
            connection.exec_driver_sql(f'ALTER TABLE {table} ADD CONSTRAINT "{name}" {definition}')
        assert not connection.scalar(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM pg_constraint x "
                "JOIN pg_class c ON c.oid=x.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace "
                "JOIN pg_class ref ON ref.oid=x.confrelid "
                "JOIN pg_namespace rn ON rn.oid=ref.relnamespace "
                "WHERE n.nspname=:schema AND x.contype='f' AND ref.relname=ANY(:tables) "
                "AND rn.nspname<>:schema)"
            ),
            {"schema": schema, "tables": list(tables)},
        )
        for definition in definitions.values():
            connection.exec_driver_sql(
                definition.replace("FUNCTION public.", f'FUNCTION "{schema}".')
            )
        for definition in triggers:
            connection.exec_driver_sql(
                definition.replace("ON public.", f'ON "{schema}".').replace(
                    "FUNCTION public.", f'FUNCTION "{schema}".'
                )
            )
        if "rag_generative_cancel_complete" not in definitions:
            module = migration()
            with Operations.context(MigrationContext.configure(connection)):
                # A failed or rolled-back trial must not mutate the original guard.
                with connection.begin_nested() as trial:
                    module.upgrade()
                    module.downgrade()
                    trial.rollback()
                module.upgrade()
        assert connection.scalar(sa.text("SELECT count(*) FROM rag_generative_runs")) == 0
        for name, original in definitions.items():
            assert (
                connection.scalar(
                    sa.text(
                        "SELECT pg_get_functiondef(p.oid) FROM pg_proc p JOIN pg_namespace n "
                        "ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.proname=:name"
                    ),
                    {"name": name},
                )
                == original
            )
    engine.dispose()
    print(f"Retained task-only PostgreSQL schema: {schema}")
    return schema


@pytest.fixture
async def repository(database_schema):
    engine = create_async_engine(
        get_settings().database_url,
        connect_args={
            "options": f"-c search_path={database_schema},public -c statement_timeout=10000"
        },
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield GenerativeRepository(sessions)
    finally:
        await engine.dispose()


async def seed(repository):
    """Existing IDs and profile configuration only; no document, question or answer bodies."""
    async with repository.sessions.begin() as session:
        row = (
            await session.execute(
                sa.text(
                    "SELECT d.id, d.owner_id, c.id AS case_id "
                    "FROM public.rag_evaluation_datasets d "
                    "JOIN public.rag_evaluation_dataset_cases c ON c.dataset_snapshot_id=d.id "
                    "JOIN public.users u ON u.id=d.owner_id WHERE u.role='owner' LIMIT 1"
                )
            )
        ).one()
        candidate = (
            await session.execute(
                sa.text(
                    "SELECT v.id,p.id AS profile_id,p.config "
                    "FROM public.rag_configuration_versions v "
                    "JOIN public.rag_profiles p ON p.id=v.generation_profile_id "
                    "WHERE coalesce("
                    "(p.config::jsonb#>>'{generation,response_schema_version}')::int,1) "
                    "IN (1,2) LIMIT 1"
                )
            )
        ).one()
        version = candidate.id
        policy_id, run_id, attempt_id = uuid4(), uuid4(), uuid4()
        await session.execute(
            sa.text(
                "INSERT INTO rag_generative_policies(id,owner_id,name,version,definition,digest) "
                "VALUES(:id,:owner,:name,1,'{}',:digest)"
            ),
            {
                "id": policy_id,
                "owner": row.owner_id,
                "name": f"synthetic-cancel-{policy_id}",
                "digest": hashlib.sha256(b"{}").hexdigest(),
            },
        )
        snapshot = {
            "candidates": [
                {
                    "configuration_version_id": str(version),
                    "component_snapshot": {
                        "profiles": [
                            {
                                "id": str(candidate.profile_id),
                                "kind": "generation",
                                "config": candidate.config,
                            }
                        ]
                    },
                }
            ]
        }
        raw = canonical(snapshot)
        run = GenerativeRunRecord(
            id=run_id,
            owner_id=row.owner_id,
            request_id=uuid4(),
            dataset_snapshot_id=row.id,
            policy_id=policy_id,
            snapshot=snapshot,
            snapshot_bytes=raw,
            snapshot_digest=hashlib.sha256(raw).hexdigest(),
            expected_rules={},
            rules_digest=hashlib.sha256(b"{}").hexdigest(),
            repetition_count=2,
        )
        session.add(run)
        await session.flush()
        session.add(
            GenerativeAttemptRecord(
                id=attempt_id,
                run_id=run_id,
                configuration_version_id=version,
                case_id=row.case_id,
                repetition=0,
                attempt_number=1,
                execution_id=uuid4(),
            )
        )
    return row.owner_id, run_id, attempt_id, raw


async def cancel(repository, actor, run_id):
    async with repository.sessions.begin() as session:
        await repository.cancel_pending(session, actor, run_id)


async def wait_for_blocked(repository, pid):
    """Observe PostgreSQL lock wait instead of guessing from elapsed time."""
    for _ in range(100):
        async with repository.sessions() as session:
            waiting = await session.scalar(
                sa.text("SELECT wait_event_type='Lock' FROM pg_stat_activity WHERE pid=:pid"),
                {"pid": pid},
            )
        if waiting:
            return
        await asyncio.sleep(0.02)
    pytest.fail("Competing connection never entered a PostgreSQL lock wait")


@pytest.mark.asyncio
async def test_cancel_first_fences_late_claim_and_preserves_inputs(repository):
    owner, run_id, attempt_id, raw = await seed(repository)
    async with repository.sessions.begin() as first:
        await repository.cancel_pending(first, owner, run_id)
        async with repository.sessions() as contender:
            pid = await contender.scalar(sa.text("SELECT pg_backend_pid()"))
            await contender.rollback()
        # Reserve a connection so the observed PID is the actual competing worker.
        async with repository.sessions.kw["bind"].connect() as connection:
            pid = await connection.scalar(sa.text("SELECT pg_backend_pid()"))
            await connection.rollback()
            worker = GenerativeRepository(async_sessionmaker(connection, expire_on_commit=False))
            task = asyncio.create_task(worker.claim_run(run_id, {"fixture": "late delivery"}))
            await wait_for_blocked(repository, pid)
            await first.commit()
            assert await asyncio.wait_for(task, 5) is None
    await cancel(repository, owner, run_id)  # idempotent, same audit metadata
    async with repository.sessions() as session:
        run = await session.get(GenerativeRunRecord, run_id)
        attempt = await session.get(GenerativeAttemptRecord, attempt_id)
        assert run.status == attempt.status == "cancelled"
        assert run.cancelled_by == owner and run.cancellation_reason == "user_requested"
        assert run.finished_at == run.cancelled_at == attempt.finished_at
        assert run.snapshot_bytes == raw and run.snapshot_digest == hashlib.sha256(raw).hexdigest()
        assert run.expected_rules == {} and run.rules_digest == hashlib.sha256(b"{}").hexdigest()
        assert run.claim_token is run.claimed_at is attempt.claim_token is attempt.result is None
    async with repository.sessions.begin() as session:
        with pytest.raises(AppError):
            await repository.retry_failed(session, owner, run_id)


@pytest.mark.asyncio
async def test_claim_first_rejects_waiting_cancel(repository):
    owner, run_id, _, _ = await seed(repository)
    engine = repository.sessions.kw["bind"]
    async with engine.connect() as first_connection:
        outer = await first_connection.begin()
        worker = GenerativeRepository(
            async_sessionmaker(
                first_connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            )
        )
        token = await worker.claim_run(run_id, {"fixture": "claim winner"})
        assert token is not None
        async with engine.connect() as other_connection:
            pid = await other_connection.scalar(sa.text("SELECT pg_backend_pid()"))
            await other_connection.rollback()
            other = GenerativeRepository(
                async_sessionmaker(other_connection, expire_on_commit=False)
            )
            task = asyncio.create_task(cancel(other, owner, run_id))
            await wait_for_blocked(repository, pid)
            await outer.commit()
            with pytest.raises(AppError) as error:
                await asyncio.wait_for(task, 5)
            assert error.value.status_code == 409
    async with repository.sessions() as session:
        run = await session.get(GenerativeRunRecord, run_id)
        assert run.status == "running" and run.cancelled_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    [
        "expected_rules=jsonb_build_object('changed',true)",
        "cancellation_reason='other'",
        "status='pending',finished_at=NULL",
    ],
)
async def test_cancelled_run_is_immutable(repository, mutation):
    owner, run_id, _, _ = await seed(repository)
    await cancel(repository, owner, run_id)
    with pytest.raises(sa.exc.DBAPIError):
        async with repository.sessions.begin() as session:
            await session.execute(
                sa.text(f"UPDATE rag_generative_runs SET {mutation} WHERE id=:id"), {"id": run_id}
            )


@pytest.mark.asyncio
async def test_parent_only_cancel_cannot_commit(repository):
    owner, run_id, _, _ = await seed(repository)
    with pytest.raises(sa.exc.DBAPIError, match="cancel"):
        async with repository.sessions.begin() as session:
            await session.execute(
                sa.text(
                    "UPDATE rag_generative_runs SET status='cancelled',cancelled_by=:owner,"
                    "cancelled_at=now(),finished_at=now(),cancellation_reason='user_requested' "
                    "WHERE id=:id"
                ),
                {"owner": owner, "id": run_id},
            )


@pytest.mark.asyncio
async def test_cancel_transition_cannot_rewrite_frozen_rules(repository):
    owner, run_id, _, _ = await seed(repository)
    with pytest.raises(sa.exc.DBAPIError, match="input is immutable"):
        async with repository.sessions.begin() as session:
            await session.execute(
                sa.text(
                    "UPDATE rag_generative_runs SET status='cancelled',cancelled_by=:owner,"
                    "cancelled_at=now(),finished_at=now(),cancellation_reason='user_requested',"
                    "expected_rules=jsonb_build_object('modified',true) WHERE id=:id"
                ),
                {"owner": owner, "id": run_id},
            )


@pytest.mark.asyncio
async def test_cancelled_parent_rejects_new_attempt_and_terminal_edit(repository):
    owner, run_id, attempt_id, _ = await seed(repository)
    await cancel(repository, owner, run_id)
    with pytest.raises(sa.exc.DBAPIError, match="cancelled"):
        async with repository.sessions.begin() as session:
            old = await session.get(GenerativeAttemptRecord, attempt_id)
            session.add(
                GenerativeAttemptRecord(
                    id=uuid4(),
                    run_id=run_id,
                    configuration_version_id=old.configuration_version_id,
                    case_id=old.case_id,
                    repetition=0,
                    attempt_number=2,
                    execution_id=uuid4(),
                )
            )
    with pytest.raises(sa.exc.DBAPIError, match="immutable"):
        async with repository.sessions.begin() as session:
            await session.execute(
                sa.text("UPDATE rag_generative_attempts SET finished_at=now() WHERE id=:id"),
                {"id": attempt_id},
            )


@pytest.mark.asyncio
async def test_cancel_checks_owner_before_idempotency(repository):
    owner, run_id, _, _ = await seed(repository)
    await cancel(repository, owner, run_id)
    with pytest.raises(AppError) as error:
        await cancel(repository, uuid4(), run_id)
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_cancelled_candidate_cannot_pass_database_acceptance(repository):
    owner, run_id, attempt_id, _ = await seed(repository)
    await cancel(repository, owner, run_id)
    with pytest.raises(sa.exc.DBAPIError, match="complete exact run"):
        async with repository.sessions.begin() as session:
            attempt = await session.get(GenerativeAttemptRecord, attempt_id)
            await session.execute(
                sa.text("SELECT rag_verify_generative_candidate(:run,:version)"),
                {
                    "run": run_id,
                    "version": attempt.configuration_version_id,
                },
            )


@pytest.mark.asyncio
async def test_pending_with_execution_cannot_cancel(repository):
    owner, run_id, attempt_id, _ = await seed(repository)
    async with repository.sessions.begin() as session:
        attempt = await session.get(GenerativeAttemptRecord, attempt_id)
        await session.execute(
            sa.text(
                "INSERT INTO rag_executions"
                "(id,actor_id,evaluation_attempt_id,status,complete,stages) "
                "VALUES(:id,:actor,:attempt,'running',false,'[]')"
            ),
            {"id": attempt.execution_id, "actor": owner, "attempt": attempt_id},
        )
    with pytest.raises(AppError) as error:
        await cancel(repository, owner, run_id)
    assert error.value.status_code == 409
    async with repository.sessions() as session:
        run = await session.get(GenerativeRunRecord, run_id)
        assert run.status == "pending" and run.cancelled_at is None
