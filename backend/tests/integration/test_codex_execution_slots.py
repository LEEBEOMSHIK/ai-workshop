"""Real PostgreSQL capacity proofs; only guarded disposable synthetic databases."""

import asyncio
from collections.abc import Iterator
from dataclasses import replace
from importlib import import_module
from importlib.util import find_spec
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from tests.integration.publishing_support import (
    IsolatedPublishingDatabase,
    isolated_publishing_database,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def database(monkeypatch: pytest.MonkeyPatch) -> Iterator[IsolatedPublishingDatabase]:
    with isolated_publishing_database(monkeypatch) as isolated:
        command.upgrade(isolated.config, "0027_codex_call_approvals")
        yield isolated


def _repository_type():
    name = "ai_workshop.labs.rag.generation.codex_slot_repository"
    assert find_spec(name) is not None, "durable execution-slot adapter is missing"
    return import_module(name).SqlAlchemyCodexExecutionSlots


async def test_distinct_instances_serialize_capacity_and_retain_unknown_cleanup(database):
    repository = _repository_type()
    await asyncio.to_thread(command.upgrade, database.config, "0028_codex_execution_slots")
    engines = [create_async_engine(database.database_url) for _ in range(2)]
    request = dict(
        runner_ref="codex-synthetic-runner",
        configuration_sha256="a" * 64,
        max_concurrent=1,
        request_id=uuid4(),
    )
    try:
        first, second = await asyncio.gather(
            repository(engines[0]).acquire(**request),
            repository(engines[1]).acquire(**request),
        )
        assert (first is None) != (second is None)
        lease = first if first is not None else second
        assert lease is not None
        await repository(engines[0]).complete(lease, process_termination_verified=False)
        assert await repository(engines[1]).acquire(**request) is None
        await repository(engines[1]).complete(lease, process_termination_verified=True)
        replacement = await repository(engines[0]).acquire(**request)
        assert replacement is not None and replacement.id != lease.id
        await repository(engines[0]).complete(replacement, process_termination_verified=True)
    finally:
        for engine in engines:
            await engine.dispose()


@pytest.mark.parametrize(
    "changes",
    [
        {"configuration_sha256": "b" * 64},
        {"max_concurrent": 2},
    ],
)
async def test_unresolved_slots_reject_settings_drift(database, changes):
    repository = _repository_type()
    await asyncio.to_thread(command.upgrade, database.config, "0028_codex_execution_slots")
    engine = create_async_engine(database.database_url)
    request = dict(
        runner_ref="codex-synthetic-runner",
        configuration_sha256="a" * 64,
        max_concurrent=1,
        request_id=uuid4(),
    )
    try:
        lease = await repository(engine).acquire(**request)
        assert lease is not None
        with pytest.raises(RuntimeError, match="^codex_slot_settings_mismatch$"):
            await repository(engine).acquire(**(request | changes))
        await repository(engine).complete(lease, process_termination_verified=True)
        assert await repository(engine).acquire(**(request | changes)) is not None
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    "field,value",
    [
        ("request_id", uuid4()),
        ("runner_ref", "codex-other-runner"),
        ("configuration_sha256", "b" * 64),
        ("id", uuid4()),
    ],
)
async def test_completion_requires_exact_owned_lease(database, field, value):
    repository = _repository_type()
    await asyncio.to_thread(command.upgrade, database.config, "0028_codex_execution_slots")
    engine = create_async_engine(database.database_url)
    request = dict(
        runner_ref="codex-synthetic-runner",
        configuration_sha256="a" * 64,
        max_concurrent=1,
        request_id=uuid4(),
    )
    try:
        slots = repository(engine)
        lease = await slots.acquire(**request)
        with pytest.raises(RuntimeError, match="^codex_slot_lease_mismatch$"):
            await slots.complete(
                replace(lease, **{field: value}), process_termination_verified=True
            )
        assert await slots.acquire(**request) is None
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    "changes",
    [
        {"max_concurrent": True},
        {"max_concurrent": 0},
        {"max_concurrent": 65},
        {"max_concurrent": 1.0},
        {"configuration_sha256": "A" * 64},
        {"configuration_sha256": "a" * 65},
        {"runner_ref": "../unsafe"},
        {"runner_ref": "codex-" + "x" * 120},
        {"request_id": "untrusted"},
    ],
)
async def test_malformed_acquisition_rejected_before_database(changes):
    repository = _repository_type()
    engine = create_async_engine("postgresql+psycopg://unused:unused@127.0.0.1:1/unused")
    request = dict(
        runner_ref="codex-synthetic-runner",
        configuration_sha256="a" * 64,
        max_concurrent=1,
        request_id=uuid4(),
    )
    try:
        with pytest.raises(RuntimeError, match="^codex_slot_invalid_input$") as error:
            await repository(engine).acquire(**(request | changes))
        assert error.value.__context__ is None and error.value.__cause__ is None
    finally:
        await engine.dispose()


async def test_integer_termination_evidence_cannot_release(database):
    repository = _repository_type()
    await asyncio.to_thread(command.upgrade, database.config, "0028_codex_execution_slots")
    engine = create_async_engine(database.database_url)
    request = dict(
        runner_ref="codex-synthetic-runner",
        configuration_sha256="a" * 64,
        max_concurrent=1,
        request_id=uuid4(),
    )
    try:
        slots = repository(engine)
        lease = await slots.acquire(**request)
        with pytest.raises(RuntimeError, match="^codex_slot_invalid_input$"):
            await slots.complete(lease, process_termination_verified=1)
        assert await slots.acquire(**request) is None
    finally:
        await engine.dispose()


async def test_migration_preserves_profiles_and_refuses_unresolved_downgrade(database):
    repository = _repository_type()
    engine = create_async_engine(database.database_url)
    try:
        async with engine.connect() as connection:
            before = list(
                (
                    await connection.execute(text("SELECT id FROM rag_profiles ORDER BY id"))
                ).scalars()
            )
        await asyncio.to_thread(command.upgrade, database.config, "0028_codex_execution_slots")
        slots = repository(engine)
        lease = await slots.acquire(
            runner_ref="codex-synthetic-runner",
            configuration_sha256="a" * 64,
            max_concurrent=1,
            request_id=uuid4(),
        )
        with pytest.raises(RuntimeError, match="^codex_slots_unresolved$"):
            await asyncio.to_thread(command.downgrade, database.config, "0027_codex_call_approvals")
        await slots.complete(lease, process_termination_verified=True)
        await asyncio.to_thread(command.downgrade, database.config, "0027_codex_call_approvals")
        async with engine.connect() as connection:
            assert (
                await connection.scalar(text("SELECT to_regclass('rag_codex_execution_slots')"))
                is None
            )
            assert (
                list(
                    (
                        await connection.execute(text("SELECT id FROM rag_profiles ORDER BY id"))
                    ).scalars()
                )
                == before
            )
            assert (
                await connection.scalar(text("SELECT to_regclass('rag_codex_call_approvals')"))
                is not None
            )
    finally:
        await engine.dispose()


@pytest.mark.parametrize("operation", ["acquire", "complete"])
async def test_driver_error_has_no_raw_message_or_exception_chain(database, operation):
    repository = _repository_type()
    await asyncio.to_thread(command.upgrade, database.config, "0028_codex_execution_slots")
    engine = create_async_engine(database.database_url)
    request = dict(
        runner_ref="codex-synthetic-runner",
        configuration_sha256="a" * 64,
        max_concurrent=1,
        request_id=uuid4(),
    )

    def fail(*args):
        raise RuntimeError("synthetic secret SQL canary")

    try:
        slots = repository(engine)
        lease = await slots.acquire(**request)
        event.listen(engine.sync_engine, "before_cursor_execute", fail)
        try:
            with pytest.raises(RuntimeError, match="^codex_slot_source_unavailable$") as error:
                if operation == "acquire":
                    await slots.acquire(**request)
                else:
                    await slots.complete(lease, process_termination_verified=True)
            assert error.value.__context__ is None and error.value.__cause__ is None
            assert "canary" not in repr(error.value)
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", fail)
        assert await slots.acquire(**request) is None
    finally:
        await engine.dispose()


async def test_distinct_runner_references_have_independent_capacity(database):
    repository = _repository_type()
    await asyncio.to_thread(command.upgrade, database.config, "0028_codex_execution_slots")
    engine = create_async_engine(database.database_url)
    try:
        slots = repository(engine)
        first = await slots.acquire(
            runner_ref="codex-first-runner",
            configuration_sha256="a" * 64,
            max_concurrent=1,
            request_id=uuid4(),
        )
        second = await slots.acquire(
            runner_ref="codex-second-runner",
            configuration_sha256="b" * 64,
            max_concurrent=2,
            request_id=uuid4(),
        )
        assert first is not None and second is not None
    finally:
        await engine.dispose()
