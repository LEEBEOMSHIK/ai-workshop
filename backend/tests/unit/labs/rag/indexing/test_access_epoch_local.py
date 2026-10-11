"""Actual controller/repository never re-dispatch an uncertain external action."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.indexing.access_epoch_local import (
    ControlOwnership,
    LocalAccessEpochController,
)
from ai_workshop.labs.rag.indexing.access_epoch_types import ControlSettlement, CutoverActionKind
from ai_workshop.labs.rag.indexing.alias_recovery_types import AliasRecoveryError
from tests.unit.labs.rag.indexing.test_access_epoch_repository import settle_key_group, setup


class Control:
    def __init__(self):
        self.commands = []
        self.unknown = CutoverActionKind.STOP_OLD
        self.unsettled_previous = False
        self.control_port_id = uuid4()

    async def acquire(self, execution_id, executor_generation):
        if self.unsettled_previous:
            raise AliasRecoveryError("rag_alias_proof_invalid")
        return ControlOwnership(execution_id, executor_generation, self.control_port_id)

    async def assert_owned(self, ownership):
        if ownership.control_port_id != self.control_port_id:
            raise AliasRecoveryError("rag_alias_proof_invalid")

    async def expected(self, epoch, kind, sequence, ownership):
        from ai_workshop.labs.rag.indexing.access_epoch_types import ControlExpectedIdentity

        return ControlExpectedIdentity("{}", sequence)

    async def execute(self, action, ownership):
        self.commands.append(action.kind)
        return ControlSettlement(
            action.action_id,
            action.execution_id,
            action.executor_generation,
            "unknown" if action.kind == self.unknown else "settled",
            "{}",
            datetime.now(UTC),
        )

    async def reconcile(self, action, ownership):
        # Missing container/process listings alone cannot settle the durable job.
        return None


async def test_lost_stop_ack_missing_old_id_is_not_retirement_permission():
    db, repo, claim, original = await setup()

    class Backend:
        async def preflight(self, _snapshot):
            return original

    control = Control()
    controller = LocalAccessEpochController(repo, Backend(), control)
    await controller.advance(claim)
    await controller.advance(claim)
    assert control.commands == [CutoverActionKind.STOP_REGISTERED_APPS, CutoverActionKind.STOP_OLD]
    state = await repo.readback(claim)
    assert state.operation_state == "open" and state.gate_state == "frozen"
    assert state.old_server_stopped_at is None


async def test_unsettled_prior_compose_executor_blocks_all_external_mutations():
    db, repo, claim, original = await setup()

    class Backend:
        async def preflight(self, _snapshot):
            return original

    control = Control()
    control.unsettled_previous = True
    controller = LocalAccessEpochController(repo, Backend(), control)
    with pytest.raises(AliasRecoveryError, match="rag_alias_proof_invalid"):
        await controller.advance(claim)
    assert control.commands == [] and db.operation.state == "open"


@pytest.mark.parametrize(
    "fault", ["missing_generation", "wrong_generation", "wrong_port", "wrong_execution", "untyped"]
)
async def test_unbound_ownership_cannot_submit_or_reserve_actions(fault):
    db, repo, claim, original = await setup()

    class Backend:
        async def preflight(self, _snapshot):
            return original

    class UnboundControl(Control):
        control_port_id = uuid4()

        async def acquire(self, execution_id, executor_generation=None):
            values = dict(
                execution_id=execution_id,
                executor_generation=executor_generation,
                control_port_id=self.control_port_id,
            )
            if fault == "missing_generation":
                values.pop("executor_generation")
            elif fault == "wrong_generation":
                values["executor_generation"] = str(uuid4())
            elif fault == "wrong_port":
                values["control_port_id"] = uuid4()
            elif fault == "wrong_execution":
                values["execution_id"] = uuid4()
            if fault in {"missing_generation", "untyped"}:
                return SimpleNamespace(**values)
            return ControlOwnership(**values)

    control = UnboundControl()
    with pytest.raises(AliasRecoveryError, match="rag_alias_proof_invalid"):
        await LocalAccessEpochController(repo, Backend(), control).advance(claim)
    state = await repo.readback(claim)
    assert state.actions == ()
    assert control.commands == []
    assert state.operation_state == "open" and state.gate_state == "frozen"


async def test_lost_ownership_blocks_before_first_action_reservation():
    db, repo, claim, original = await setup()

    class Backend:
        async def preflight(self, _snapshot):
            return original

    class LostControl(Control):
        async def assert_owned(self, _ownership):
            raise RuntimeError("synthetic-private-controller-detail")

    control = LostControl()
    with pytest.raises(AliasRecoveryError, match="rag_alias_proof_invalid") as error:
        await LocalAccessEpochController(repo, Backend(), control).advance(claim)
    assert "synthetic-private" not in str(error.value)
    assert (await repo.readback(claim)).actions == ()
    assert control.commands == []


async def test_readback_exposes_existing_durable_executor_generation():
    from ai_workshop.labs.rag.indexing.access_epoch_models import AccessEpochExecutionRecord

    db, repo, claim, original = await setup()
    assert (await repo.readback(claim)).executor_generation is None
    epoch = await repo.acquire(claim, original)
    # Read the actual persisted record rather than recreating repository behavior.
    record = next(row for (model, _), row in db.rows.items() if model is AccessEpochExecutionRecord)
    assert (await repo.readback(claim)).executor_generation == record.executor_generation
    assert (await repo.readback(claim)).prepared == epoch


@pytest.mark.parametrize("stage", ["acquire", "assert"])
async def test_control_port_change_during_await_cannot_obtain_ownership(stage):
    db, repo, claim, original = await setup()

    class Backend:
        async def preflight(self, _snapshot):
            return original

    class SwitchingControl(Control):
        def __init__(self):
            super().__init__()
            self.expected_calls = 0

        async def acquire(self, execution_id, executor_generation):
            if stage == "acquire":
                self.control_port_id = uuid4()
            return await super().acquire(execution_id, executor_generation)

        async def assert_owned(self, ownership):
            if stage == "assert":
                self.control_port_id = uuid4()

        async def expected(self, epoch, kind, sequence, ownership):
            self.expected_calls += 1
            return await super().expected(epoch, kind, sequence, ownership)

    control = SwitchingControl()
    with pytest.raises(AliasRecoveryError, match="rag_alias_proof_invalid"):
        await LocalAccessEpochController(repo, Backend(), control).advance(claim)
    assert control.expected_calls == 0
    assert control.commands == []
    assert (await repo.readback(claim)).actions == ()


async def test_control_port_change_during_post_reservation_assert_keeps_pending():
    db, repo, claim, original = await setup()

    class Backend:
        async def preflight(self, _snapshot):
            return original

    class SwitchingControl(Control):
        switch_next = False

        async def assert_owned(self, ownership):
            if self.switch_next:
                self.switch_next = False
                self.control_port_id = uuid4()
            else:
                await super().assert_owned(ownership)

    control = SwitchingControl()
    reserve = repo.reserve_action

    async def reserve_then_switch(*args):
        action = await reserve(*args)
        control.switch_next = True
        return action

    repo.reserve_action = reserve_then_switch
    with pytest.raises(AliasRecoveryError, match="rag_alias_proof_invalid"):
        await LocalAccessEpochController(repo, Backend(), control).advance(claim)
    state = await repo.readback(claim)
    assert len(state.actions) == 1 and state.actions[0].outcome == "pending"
    assert control.commands == []


@pytest.mark.parametrize("stage", ["expected", "reserve", "execute"])
async def test_ownership_loss_after_action_boundary_stops_progress(stage):
    db, repo, claim, original = await setup()

    class Backend:
        async def preflight(self, _snapshot):
            return original

    class LosingControl(Control):
        owned = True

        async def assert_owned(self, ownership):
            await super().assert_owned(ownership)
            if not self.owned:
                raise RuntimeError("synthetic-private-controller-detail")

        async def expected(self, *args):
            result = await super().expected(*args)
            if stage == "expected":
                self.owned = False
            return result

        async def execute(self, *args):
            result = await super().execute(*args)
            if stage == "execute":
                self.owned = False
            return result

    control = LosingControl()
    reserve = repo.reserve_action

    async def reserve_then_lose(*args):
        result = await reserve(*args)
        if stage == "reserve":
            control.owned = False
        return result

    repo.reserve_action = reserve_then_lose
    with pytest.raises(AliasRecoveryError, match="rag_alias_proof_invalid") as error:
        await LocalAccessEpochController(repo, Backend(), control).advance(claim)
    assert "synthetic-private" not in str(error.value)
    state = await repo.readback(claim)
    if stage == "expected":
        assert state.actions == ()
    else:
        assert len(state.actions) == 1 and state.actions[0].outcome == "pending"
    assert len(control.commands) == (1 if stage == "execute" else 0)
    assert state.operation_state == "open" and state.gate_state == "frozen"


async def test_ownership_loss_during_reconcile_cannot_settle_or_replay():
    db, repo, claim, original = await setup()

    class Backend:
        async def preflight(self, _snapshot):
            return original

    class LosingControl(Control):
        owned = True

        async def assert_owned(self, ownership):
            await super().assert_owned(ownership)
            if not self.owned:
                raise AliasRecoveryError("rag_alias_proof_invalid")

        async def reconcile(self, action, ownership):
            self.owned = False
            return ControlSettlement(
                action.action_id,
                action.execution_id,
                action.executor_generation,
                "settled",
                json.dumps({"finished_at": datetime.now(UTC).isoformat()}),
                datetime.now(UTC),
            )

    control = LosingControl()
    controller = LocalAccessEpochController(repo, Backend(), control)
    await controller.advance(claim)
    before = await repo.readback(claim)
    with pytest.raises(AliasRecoveryError, match="rag_alias_proof_invalid"):
        await controller.advance(claim)
    assert (await repo.readback(claim)) == before
    assert control.commands == [CutoverActionKind.STOP_REGISTERED_APPS, CutoverActionKind.STOP_OLD]


@pytest.mark.parametrize("stage", ["observe", "anchor"])
async def test_final_ownership_loss_cannot_verify_epoch(stage):
    db, repo, claim, original = await setup()

    class SettlingControl(Control):
        owned = True

        async def assert_owned(self, ownership):
            await super().assert_owned(ownership)
            if not self.owned:
                raise AliasRecoveryError("rag_alias_proof_invalid")

        async def execute(self, *args):
            result = await super().execute(*args)
            manifest = {"finished_at": result.observed_at.isoformat()}
            if args[0].kind == CutoverActionKind.ISSUE_ROLE_KEY:
                epoch = (await repo.readback(claim)).prepared
                manifest = await settle_key_group(repo, epoch, args[0], result.observed_at)
            return replace(
                result,
                outcome="settled",
                manifest_json=json.dumps(manifest, sort_keys=True, separators=(",", ":")),
            )

    control = SettlingControl()

    class Backend:
        anchor_calls = 0

        async def preflight(self, _snapshot):
            return original

        async def observe_secured(self, _epoch):
            if stage == "observe":
                control.owned = False
            return object()

        async def commit_anchor(self, _evidence):
            self.anchor_calls += 1
            control.owned = False
            return object()

    backend = Backend()
    with pytest.raises(AliasRecoveryError, match="rag_alias_proof_invalid"):
        await LocalAccessEpochController(repo, backend, control).advance(claim)
    state = await repo.readback(claim)
    assert state.phase == "secured_started"
    assert all(item.outcome == "settled" for item in state.actions)
    assert state.operation_state == "open" and state.gate_state == "frozen"
    assert state.receipt is None
    assert backend.anchor_calls == (1 if stage == "anchor" else 0)


@pytest.mark.parametrize("phase", ["verified", "receipted"])
@pytest.mark.parametrize("settled_actions", [False, True])
async def test_concurrent_completion_during_acquire_does_not_repeat_controls(
    phase, settled_actions
):
    from ai_workshop.labs.rag.indexing.access_epoch_local import CUTOVER_ORDER
    from ai_workshop.labs.rag.indexing.access_epoch_models import AccessEpochRecord
    from ai_workshop.labs.rag.indexing.access_epoch_types import ControlExpectedIdentity

    db, repo, claim, original = await setup()

    class Backend:
        async def preflight(self, _snapshot):
            return original

        async def observe_secured(self, _epoch):
            pytest.fail("completed epoch must not repeat observation")

    class CompletingControl(Control):
        async def acquire(self, *args):
            ownership = await super().acquire(*args)
            if settled_actions:
                # Simulate the other controller's durable results through the
                # real repository over its fake SQL transport, not a fake SUT.
                for kind in CUTOVER_ORDER:
                    state = await repo.readback(claim)
                    sequence = state.actions[-1].event_sequence if state.actions else 0
                    action = await repo.reserve_action(
                        state.prepared, kind, ControlExpectedIdentity("{}", sequence)
                    )
                    observed = datetime.now(UTC)
                    manifest = {"finished_at": observed.isoformat()}
                    if kind == CutoverActionKind.ISSUE_ROLE_KEY:
                        manifest = await settle_key_group(repo, state.prepared, action, observed)
                    await repo.settle_action(
                        action,
                        ControlSettlement(
                            action.action_id,
                            action.execution_id,
                            action.executor_generation,
                            "settled",
                            json.dumps(manifest, sort_keys=True, separators=(",", ":")),
                            observed,
                        ),
                    )
            for (model, _), record in db.rows.items():
                if model is AccessEpochRecord:
                    record.phase = phase
            return ownership

    control = CompletingControl()
    state = await LocalAccessEpochController(repo, Backend(), control).advance(claim)
    assert state.phase == phase
    assert control.commands == []
    if settled_actions:
        assert len(state.actions) == 12 and all(item.outcome == "settled" for item in state.actions)
    else:
        assert state.actions == ()


@pytest.mark.parametrize("field", ["execution_id", "executor_generation"])
async def test_foreign_reserved_action_cannot_be_executed(field):
    db, repo, claim, original = await setup()

    class Backend:
        async def preflight(self, _snapshot):
            return original

    control = Control()
    reserve = repo.reserve_action

    async def reserve_foreign(*args):
        action = await reserve(*args)
        value = uuid4() if field == "execution_id" else str(uuid4())
        return replace(action, **{field: value})

    repo.reserve_action = reserve_foreign
    with pytest.raises(AliasRecoveryError, match="rag_alias_proof_invalid"):
        await LocalAccessEpochController(repo, Backend(), control).advance(claim)
    state = await repo.readback(claim)
    assert len(state.actions) == 1 and state.actions[0].outcome == "pending"
    assert control.commands == []


@pytest.mark.parametrize("generation", [None, "", "not-a-generation", True])
async def test_invalid_durable_generation_blocks_before_control_acquire(generation):
    from ai_workshop.labs.rag.indexing.access_epoch_models import AccessEpochExecutionRecord

    db, repo, claim, original = await setup()
    await repo.acquire(claim, original)
    for (model, _), record in db.rows.items():
        if model is AccessEpochExecutionRecord:
            record.executor_generation = generation

    class ControlMustNotAcquire(Control):
        async def acquire(self, *args):
            pytest.fail("invalid durable generation cannot acquire control")

    control = ControlMustNotAcquire()
    with pytest.raises(AliasRecoveryError, match="rag_alias_proof_invalid"):
        await LocalAccessEpochController(repo, object(), control).advance(claim)
    assert (await repo.readback(claim)).actions == ()
    assert control.commands == []


@pytest.mark.parametrize(
    "stage", ["mark_verified", "final_readback", "generation", "binding", "completed_readback"]
)
@pytest.mark.parametrize("collect_proof", [False, True])
async def test_lost_finalization_owner_cannot_publish_success(stage, collect_proof):
    from ai_workshop.labs.rag.indexing.access_epoch_local import LocalAccessEpochCollector
    from tests.unit.labs.rag.indexing.test_access_epoch_repository import closure_case

    db, repo, claim, epoch, verified, proof = await closure_case()

    class LosingControl(Control):
        owned = True

        async def acquire(self, *args):
            result = await super().acquire(*args)
            if stage == "completed_readback":
                await repo.mark_verified(epoch, verified, anchor=repo.floor_from_verified(verified))
            return result

        async def assert_owned(self, ownership):
            await super().assert_owned(ownership)
            if not self.owned:
                raise RuntimeError("synthetic-private-finalization-detail")

    control = LosingControl()

    class Backend:
        revalidated = False

        async def observe_secured(self, _epoch):
            return verified

        async def commit_anchor(self, evidence):
            return repo.floor_from_verified(evidence)

        async def revalidate(self, _claim, _evidence):
            self.revalidated = True

    mark = repo.mark_verified
    read = repo.readback
    marked = False

    async def mark_then_lose(*args, **kwargs):
        nonlocal marked
        result = await mark(*args, **kwargs)
        marked = True
        if stage == "mark_verified":
            control.owned = False
        return result

    async def read_then_lose(*args):
        result = await read(*args)
        if marked and stage in {"final_readback", "completed_readback"}:
            control.owned = False
        if marked and stage == "generation":
            return replace(result, executor_generation=str(uuid4()))
        if marked and stage == "binding":
            return replace(
                result,
                prepared=replace(epoch, binding=replace(epoch.binding, execution_id=str(uuid4()))),
            )
        return result

    repo.mark_verified = mark_then_lose
    repo.readback = read_then_lose
    backend = Backend()
    controller = LocalAccessEpochController(repo, backend, control)
    collector = LocalAccessEpochCollector(controller)
    with pytest.raises(AliasRecoveryError, match="rag_alias_proof_invalid") as error:
        if collect_proof:
            await collector.collect_verified_end(claim)
        else:
            await controller.advance(claim)
    assert "synthetic-private" not in str(error.value)
    state = await read(claim)
    assert marked and state.phase == "verified"
    assert state.operation_state == "open" and state.gate_state == "frozen"
    assert state.receipt is None
    assert control.commands == []
    assert backend.revalidated is False
    # The collector cannot authorize that proof through its public revalidate boundary.
    with pytest.raises(AliasRecoveryError, match="rag_alias_proof_invalid"):
        await collector.revalidate(claim, proof)


@pytest.mark.parametrize("already_verified", [False, True])
async def test_exact_owner_can_collect_and_revalidate_legitimate_verified_proof(already_verified):
    from ai_workshop.labs.rag.indexing.access_epoch_local import LocalAccessEpochCollector
    from tests.unit.labs.rag.indexing.test_access_epoch_repository import closure_case

    db, repo, claim, epoch, verified, proof = await closure_case()

    class Backend:
        async def observe_secured(self, _epoch):
            if already_verified:
                pytest.fail("read-only completed replay cannot repeat observation")
            return verified

        async def commit_anchor(self, evidence):
            return repo.floor_from_verified(evidence)

        async def revalidate(self, _claim, _evidence):
            return None

    class ExactControl(Control):
        async def acquire(self, *args):
            if already_verified:
                pytest.fail("read-only completed replay cannot acquire control")
            return await super().acquire(*args)

    if already_verified:
        await repo.mark_verified(epoch, verified, anchor=repo.floor_from_verified(verified))
    control = ExactControl()
    collector = LocalAccessEpochCollector(LocalAccessEpochController(repo, Backend(), control))
    result = await collector.collect_verified_end(claim)
    assert result == proof
    await collector.revalidate(claim, result)
    state = await repo.readback(claim)
    assert state.phase == "verified"
    assert state.operation_state == "open" and state.gate_state == "frozen"
    assert state.receipt is None and control.commands == []
