"""Composite semantics and SQL shape; no real maker/DBAPI authority is claimed."""

import importlib
from asyncio import CancelledError, Event, create_task, sleep
from collections.abc import Iterator
from contextlib import contextmanager
from copy import copy, deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Select

from ai_workshop.labs.rag.indexing.access_epoch_models import (
    AccessEpochEventRecord,
    AccessEpochFloorRecord,
    AccessEpochKeyEventRecord,
    AccessEpochRecord,
)
from ai_workshop.labs.rag.indexing.alias_models import (
    AliasClusterGateRecord,
    AliasRecoveryReceiptRecord,
)
from ai_workshop.platform.identity.models import UserRecord
from tests.unit.labs.rag.indexing.test_access_epoch_secured_read import case
from tests.unit.labs.rag.indexing.test_access_epoch_secured_read_assembly import factory as factory


class ReadSession:
    """External semantic SQL transport, not an AsyncSession substitute proof."""

    def __init__(self, c: Any) -> None:
        self.c = c
        self.autoflush_disabled = False
        self.statements: list[Any] = []
        self.rollbacks = 0
        self.begins = 0
        self.after: Any = None
        self.rollback_error: BaseException | None = None
        self.exit_error: BaseException | None = None
        self.closes = 0
        self.close_started = Event()
        self.close_release: Event | None = None

    async def __aenter__(self) -> "ReadSession":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    async def close(self) -> None:
        self.closes += 1
        self.close_started.set()
        if self.close_release:
            await self.close_release.wait()
        if self.exit_error:
            raise self.exit_error

    async def begin(self) -> None:
        self.begins += 1

    @property
    @contextmanager
    def no_autoflush(self) -> Iterator[None]:
        self.autoflush_disabled = True
        try:
            yield
        finally:
            self.autoflush_disabled = False

    async def rollback(self) -> None:
        self.rollbacks += 1
        if self.rollback_error:
            raise self.rollback_error

    async def execute(self, statement: Any) -> None:
        assert not self.statements
        assert str(statement) == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
        self.statements.append(statement)

    async def scalars(self, statement: Any) -> Any:
        assert self.autoflush_disabled
        assert isinstance(statement, Select)
        assert statement._for_update_arg is None
        self.statements.append(statement)
        result = await self.c.db.scalars(statement)
        if self.after:
            self.after(len(self.statements))
        return result


def module() -> Any:
    name = "ai_workshop.labs.rag.indexing.access_epoch_committed_snapshot"
    assert importlib.util.find_spec(name) is not None, "committed snapshot missing"
    return importlib.import_module(name)


def install(c: Any) -> ReadSession:
    session = ReadSession(c)

    def factory() -> ReadSession:
        return session

    c.repository.sessions = factory
    c.repository.recovery.sessions = factory
    return session


async def read(c: Any) -> Any:
    return await module().read_committed_snapshot(c.repository, c.keys, c.claim)


def rows(c: Any) -> object:
    return {
        key: {k: v for k, v in vars(row).items() if k != "_sa_instance_state"}
        for key, row in c.db.rows.items()
    }


async def test_verified_composite_setup_selects_rollback_and_no_writes() -> None:
    c = await case()
    before = deepcopy(rows(c))
    s = install(c)
    value = await read(c)
    assert value.evidence == c.evidence
    assert value.state.phase == "verified"
    assert len(value.state.actions) == 12 and len(value.completed_keys) == 3
    assert value.floor == c.repository.floor_from_verified(c.evidence)
    assert s.begins == s.rollbacks == 1
    assert len(s.statements) > 10
    assert rows(c) == before
    assert repr(value) == "CommittedEpochSnapshot()"


async def test_same_receipted_composite_allows_retired_profiles() -> None:
    c = await case()
    await c.repository.close_access_epoch(c.claim, c.proof)
    receipt = next(row for key, row in c.db.rows.items() if key[0] is AliasRecoveryReceiptRecord)
    # External semantic transport models the existing schema trigger linkage.
    receipt.access_epoch_id = UUID(c.epoch.binding.access_epoch_id)
    receipt.execution_id = UUID(c.epoch.binding.execution_id)
    from ai_workshop.labs.rag.models.models import ProfileRecord

    c.db.rows = {key: row for key, row in c.db.rows.items() if key[0] is not ProfileRecord}
    s = install(c)
    value = await read(c)
    assert value.state.phase == "receipted" and value.state.receipt.proof == c.proof
    assert s.rollbacks == 1


class TextSubclass(str):
    pass


@pytest.mark.parametrize("change", ["kind_subclass", "gate_subclass", "original", "key_bool"])
async def test_initial_exact_types_and_original_identity(change: str) -> None:
    c = await case()
    if change == "kind_subclass":
        next(
            r for key, r in c.db.rows.items() if key[0] is AccessEpochEventRecord
        ).kind = TextSubclass("stop_registered_apps")
    elif change == "gate_subclass":
        next(
            r for key, r in c.db.rows.items() if key[0] is AliasClusterGateRecord
        ).state = TextSubclass("frozen")
    elif change == "original":
        next(r for key, r in c.db.rows.items() if key[0] is AccessEpochRecord).original[
            "container_id"
        ] = "f" * 64
    else:
        next(
            r for key, r in c.db.rows.items() if key[0] is AccessEpochKeyEventRecord
        ).action_sequence = True
    s = install(c)
    with pytest.raises(ValueError, match="committed_snapshot_denied"):
        await read(c)
    assert s.rollbacks == 1


@pytest.mark.parametrize(
    "change",
    [
        "owner",
        "gate",
        "claim_bool",
        "epoch_bool",
        "generation",
        "floor",
        "pending",
        "action_time",
        "action_expected",
        "key_role",
        "key_result",
        "key_parent",
        "missing",
    ],
)
async def test_corrupt_composite_denies_without_mutation(change: str) -> None:
    c = await case()

    def model(kind: type[object]) -> Any:
        return next(row for key, row in c.db.rows.items() if key[0] is kind)

    if change == "owner":
        model(UserRecord).is_active = False
    elif change == "gate":
        model(AliasClusterGateRecord).revision += 1
    elif change == "claim_bool":
        object.__setattr__(c.claim, "revision", True)
    elif change == "epoch_bool":
        model(AccessEpochRecord).ordinal = True
    elif change == "generation":
        model(AccessEpochEventRecord).executor_generation = "foreign"
    elif change == "floor":
        model(AccessEpochFloorRecord).ordinal += 1
    elif change == "pending":
        model(AccessEpochRecord).phase = "secured_started"
    elif change == "action_time":
        model(AccessEpochEventRecord).observed_at = datetime.now(UTC) + timedelta(days=1)
    elif change == "action_expected":
        model(AccessEpochEventRecord).expected_json = '{"synthetic":"foreign"}'
    elif change == "key_role":
        model(AccessEpochKeyEventRecord).role = "admin"
    elif change == "key_result":
        settled = next(
            r
            for key, r in c.db.rows.items()
            if key[0] is AccessEpochKeyEventRecord and r.outcome == "settled"
        )
        settled.manifest_json = "{}"
    elif change == "key_parent":
        model(AccessEpochKeyEventRecord).executor_generation = "foreign"
    elif change == "missing":
        c.db.rows = {
            key: row for key, row in c.db.rows.items() if key[0] is not AccessEpochFloorRecord
        }
    before = deepcopy(rows(c))
    s = install(c)
    with pytest.raises(ValueError, match="committed_snapshot_denied"):
        await read(c)
    assert s.rollbacks == (0 if change == "claim_bool" else 1) and rows(c) == before


async def test_late_claim_drift_at_real_query_boundary_denies() -> None:
    c = await case()
    s = install(c)
    s.after = lambda count: object.__setattr__(c.claim, "revision", 99) if count == 3 else None
    with pytest.raises(ValueError, match="committed_snapshot_denied"):
        await read(c)
    assert s.rollbacks == 1


async def test_primary_cancel_survives_rollback_failure() -> None:
    c = await case()
    s = install(c)
    s.rollback_error = RuntimeError("synthetic teardown")

    def cancel(_: int) -> None:
        raise CancelledError()

    s.after = cancel
    with pytest.raises(CancelledError):
        await read(c)
    assert s.rollbacks == 1


async def test_primary_cancel_survives_session_teardown_failure() -> None:
    c = await case()
    s = install(c)
    s.exit_error = RuntimeError("synthetic close")

    def cancel(_: int) -> None:
        raise CancelledError()

    s.after = cancel
    with pytest.raises(CancelledError):
        await read(c)
    assert s.rollbacks == s.closes == 1


async def test_repeated_cancel_waits_for_owned_session_close() -> None:
    c = await case()
    s = install(c)
    s.close_release = Event()
    task = create_task(read(c))
    await s.close_started.wait()
    task.cancel()
    await sleep(0)
    task.cancel()
    await sleep(0)
    assert not task.done()
    s.close_release.set()
    with pytest.raises(CancelledError):
        await task
    assert s.rollbacks == s.closes == 1


async def test_plain_rollback_failure_cannot_publish_result() -> None:
    c = await case()
    s = install(c)
    s.rollback_error = RuntimeError("synthetic teardown")
    with pytest.raises(ValueError, match="committed_snapshot_denied"):
        await read(c)


async def test_foreign_key_repository_rejected_before_session() -> None:
    c = await case()
    c.keys.parent = cast(Any, object())
    s = install(c)
    with pytest.raises(ValueError, match="committed_snapshot_denied"):
        await read(c)
    assert not s.statements and s.begins == 0


@pytest.mark.parametrize(
    "change", ["stopped_sequence", "actor_subclass", "duplicate_event", "key_time"]
)
async def test_closed_history_consistency(change: str) -> None:
    c = await case()
    if change == "stopped_sequence":
        next(r for key, r in c.db.rows.items() if key[0] is AccessEpochRecord).stopped_sequence = 3
    elif change == "actor_subclass":
        next(r for key, r in c.db.rows.items() if key[0] is UserRecord).role = TextSubclass("owner")
    elif change == "duplicate_event":
        row = deepcopy(next(r for key, r in c.db.rows.items() if key[0] is AccessEpochEventRecord))
        row.id = uuid4()
        c.db.add(row)
    else:
        next(
            r for key, r in c.db.rows.items() if key[0] is AccessEpochKeyEventRecord
        ).observed_at = datetime.now(UTC)
    s = install(c)
    with pytest.raises(ValueError, match="committed_snapshot_denied"):
        await read(c)
    assert s.rollbacks == 1


async def test_receipt_deferred_linkage_is_explicitly_loaded_and_checked() -> None:
    c = await case()
    await c.repository.close_access_epoch(c.claim, c.proof)
    receipt = next(r for key, r in c.db.rows.items() if key[0] is AliasRecoveryReceiptRecord)
    receipt.access_epoch_id = uuid4()
    receipt.execution_id = UUID(c.epoch.binding.execution_id)
    s = install(c)
    with pytest.raises(ValueError, match="committed_snapshot_denied"):
        await read(c)
    assert s.rollbacks == 1


@pytest.mark.parametrize("change", ["copied", "foreign", "expired", "phase", "ordinary"])
async def test_private_query_path_rejects_unissued_dependencies(factory: Any, change: str) -> None:
    c = await case()
    assembly = await factory()
    dependencies = assembly.bind_committed()
    if change == "copied":
        dependencies = copy(dependencies)
    elif change == "foreign":
        assembly = await factory()
    elif change == "expired":
        await assembly.close()
    elif change == "phase":
        object.__setattr__(dependencies, "phase", "context")
    elif change == "ordinary":
        assembly, dependencies = c.repository, c.keys
    with pytest.raises(ValueError, match="committed_snapshot_denied"):
        await module()._read_committed_from_dependencies(assembly, dependencies, c.claim)


async def test_actual_private_read_association_and_session_binding(factory: Any) -> None:
    c = await case()
    assembly = await factory()
    dependencies = assembly.bind_committed()
    claim = replace(
        c.claim,
        snapshot=replace(
            c.claim.snapshot,
            store_id=dependencies.repository.binding.store_id,
            cluster_uuid=dependencies.repository.binding.cluster_uuid,
        ),
    )
    reader = module()._Read.from_dependencies(assembly, dependencies, claim)
    session = dependencies.repository.sessions()
    try:
        reader.check_session(session)
        reader.guard()
        object.__setattr__(dependencies, "phase", "context")
        with pytest.raises(ValueError, match="committed_snapshot_denied"):
            reader.guard()
    finally:
        await session.close()
