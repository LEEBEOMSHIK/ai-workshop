"""Concrete control assembly; source issuers and DB policy are actual objects."""

import importlib
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tests.unit.labs.rag.indexing.test_access_epoch_admin_process import admin_case as _admin_case
from tests.unit.labs.rag.indexing.test_access_epoch_app_retirement import app_case as _app_case
from tests.unit.labs.rag.indexing.test_access_epoch_namespace_source import case as _source_case
from tests.unit.labs.rag.indexing.test_access_epoch_settlement import (
    settlement_case as _settlement_case,
)

source_case = _source_case
app_case = _app_case
admin_case = _admin_case
settlement_case = _settlement_case


def module():
    return importlib.import_module("ai_workshop.labs.rag.indexing.access_epoch_control_native")


def test_concrete_module_exists():
    assert (
        importlib.util.find_spec("ai_workshop.labs.rag.indexing.access_epoch_control_native")
        is not None
    )


@pytest.fixture
async def assembly(source_case):
    from ai_workshop.labs.rag.indexing.access_epoch_original_security import (
        OriginalSecurityAbsenceReader,
    )
    from ai_workshop.labs.rag.indexing.access_epoch_repository import (
        SqlAlchemyAccessEpochRepository,
    )
    from ai_workshop.labs.rag.indexing.alias_recovery_types import FrozenAliasClaim
    from ai_workshop.labs.rag.indexing.tracking_contracts import IndexBinding
    from tests.unit.labs.rag.indexing.test_access_epoch_repository import EpochDatabase

    c = source_case
    namespace = await c.issuer.observe(c.snapshot)

    class SecurityWire:
        async def read(self, path):
            assert path.startswith("/_cat/indices/.security")
            return []

    security = OriginalSecurityAbsenceReader(c.original, SecurityWire())
    absence = await security.observe(c.snapshot)
    db = EpochDatabase()
    repo = SqlAlchemyAccessEpochRepository(
        db, IndexBinding(c.snapshot.store_id, c.snapshot.cluster_uuid), "rag"
    )
    claim = FrozenAliasClaim(c.snapshot, uuid4(), db.actor, 1)
    args = dict(
        settings=c.settings,
        repository=repo,
        claim=claim,
        original=c.original,
        observation=c.observed,
        namespace_source=c.issuer,
        namespace=namespace,
        security_source=security,
        absence=absence,
    )
    return SimpleNamespace(source=c, args=args, db=db, repo=repo)


async def test_context_retains_actual_source_caps_and_exposes_no_setters(assembly):
    ctx = module().NativeControlContext(**assembly.args)
    assert ctx.repository is assembly.repo
    assert ctx.namespace is assembly.args["namespace"]
    assert ctx.observation is assembly.args["observation"]
    assert ctx.claim is assembly.args["claim"]
    with pytest.raises(AttributeError):
        ctx.namespace = assembly.args["namespace"]
    assert ctx.assert_sources() is None


@pytest.mark.parametrize("name", ["namespace", "observation", "absence", "claim"])
async def test_copied_or_other_bound_source_is_refused(assembly, name):
    args = dict(assembly.args)
    value = args[name]
    args[name] = replace(value, request_id=uuid4()) if name == "claim" else replace(value)
    # Claim itself is a structural exact binding, unlike issuer capabilities.
    if name == "claim":
        args[name] = (
            replace(value, snapshot=replace(value.snapshot, actor_id=uuid4()))
            if hasattr(value.snapshot, "actor_id")
            else replace(value, snapshot=replace(value.snapshot, operation_id=uuid4()))
        )
    with pytest.raises(ValueError, match="^native_control_denied$"):
        module().NativeControlContext(**args)


@pytest.mark.parametrize(
    "name", ["settings", "repository", "original", "namespace_source", "security_source"]
)
async def test_caller_lookalike_is_not_a_production_source(assembly, name):
    args = dict(assembly.args)
    args[name] = SimpleNamespace(**getattr(args[name], "__dict__", {}))
    with pytest.raises(ValueError, match="^native_control_denied$"):
        module().NativeControlContext(**args)


async def test_nested_namespace_mutation_is_denied(assembly):
    ctx = module().NativeControlContext(**assembly.args)
    object.__setattr__(ctx.namespace.permissions, "prefix", "foreign")
    with pytest.raises(ValueError, match="^native_control_denied$"):
        ctx.assert_sources()


async def test_missing_full_verifier_is_upfront_refusal_without_native_or_db_write(
    assembly, monkeypatch
):
    m = module()
    ctx = m.NativeControlContext(**assembly.args)
    control = m.ConcreteNativeCutoverControl(ctx)
    original_import = m.importlib.import_module

    def missing(name):
        if name.endswith("access_epoch_verification_native"):
            raise ImportError("synthetic-private-marker")
        return original_import(name)

    monkeypatch.setattr(m.importlib, "import_module", missing)
    before = len(assembly.db.rows)
    with pytest.raises(ValueError, match="^native_control_unsupported$"):
        await control.acquire(uuid4(), str(uuid4()))
    assert len(assembly.db.rows) == before
    assert ctx.held_owner is None and ctx.journal is None


async def test_factory_support_check_is_available_before_epoch_creation(assembly, monkeypatch):
    m = module()
    ctx = m.NativeControlContext(**assembly.args)
    control = m.ConcreteNativeCutoverControl(ctx)
    actual_import = m.importlib.import_module

    def missing(name):
        if name.endswith("access_epoch_verification_native"):
            raise ImportError("private-marker")
        return actual_import(name)

    monkeypatch.setattr(m.importlib, "import_module", missing)
    before = len(assembly.db.rows)
    with pytest.raises(ValueError, match="^native_control_unsupported$"):
        control.assert_supported()
    assert len(assembly.db.rows) == before and assembly.db.statements == []
    assert ctx.epoch is None and ctx.held_owner is None


@pytest.mark.parametrize("bad", [True, "stop_old", [], {}, None])
async def test_expected_kind_has_closed_type_before_any_io(assembly, bad):
    m = module()
    control = m.ConcreteNativeCutoverControl(m.NativeControlContext(**assembly.args))
    with pytest.raises(ValueError, match="^native_control_denied$"):
        await control.expected(None, bad, True, None)
    assert assembly.db.statements == []


async def test_failed_support_cannot_be_reacquired_or_closed_into_success(assembly, monkeypatch):
    m = module()
    control = m.ConcreteNativeCutoverControl(m.NativeControlContext(**assembly.args))
    actual_import = m.importlib.import_module

    def missing(name):
        if name.endswith("access_epoch_verification_native"):
            raise ImportError("private-marker")
        return actual_import(name)

    monkeypatch.setattr(m.importlib, "import_module", missing)
    with pytest.raises(ValueError, match="^native_control_unsupported$"):
        await control.acquire(uuid4(), str(uuid4()))
    with pytest.raises(ValueError, match="^native_control_denied$"):
        await control.acquire(uuid4(), str(uuid4()))
    control.close()
    control.close()
    with pytest.raises(ValueError, match="^native_control_denied$"):
        control.assert_supported()


@pytest.mark.parametrize("field", ["snapshot_sha256", "original_deployment_sha256"])
async def test_mutated_issued_namespace_field_is_denied(assembly, field):
    ctx = module().NativeControlContext(**assembly.args)
    object.__setattr__(ctx.namespace, field, "a" * 64)
    with pytest.raises(ValueError, match="^native_control_denied$"):
        ctx.assert_sources()


@pytest.mark.parametrize("field", ["namespace_source", "original", "security_source"])
async def test_source_receiver_substitution_is_denied(assembly, field):
    ctx = module().NativeControlContext(**assembly.args)
    object.__setattr__(ctx, "_" + field, SimpleNamespace())
    with pytest.raises(ValueError, match="^native_control_denied$"):
        ctx.assert_sources()


@pytest.mark.parametrize(
    "kind",
    list(
        __import__(
            "ai_workshop.labs.rag.indexing.access_epoch_local", fromlist=["CUTOVER_ORDER"]
        ).CUTOVER_ORDER
    ),
)
async def test_no_branch_accepts_an_unissued_control_owner(assembly, kind):
    from ai_workshop.labs.rag.indexing.access_epoch_local import ControlOwnership
    from ai_workshop.labs.rag.indexing.access_epoch_types import (
        ControlExpectedIdentity,
        ReservedCutoverAction,
    )

    m = module()
    ctx = m.NativeControlContext(**assembly.args)
    control = m.ConcreteNativeCutoverControl(ctx)
    owner = ControlOwnership(uuid4(), str(uuid4()), control.control_port_id)
    action = ReservedCutoverAction(
        uuid4(),
        owner.execution_id,
        1,
        kind,
        ControlExpectedIdentity("{}", 0),
        owner.executor_generation,
    )
    with pytest.raises(ValueError, match="^native_control_denied$"):
        await control.execute(action, owner)
    with pytest.raises(ValueError, match="^native_control_denied$"):
        await control.reconcile(action, owner)
    assert ctx.held_owner is None and ctx.journal is None


async def test_controller_uses_actual_db_truth_and_missing_support_never_reserves(
    assembly, monkeypatch
):
    from uuid import UUID

    from ai_workshop.labs.rag.documents.models import RagIndexBuildRecord
    from ai_workshop.labs.rag.indexing.access_epoch_local import LocalAccessEpochController
    from ai_workshop.labs.rag.indexing.alias_models import AliasOperationRecord
    from ai_workshop.labs.rag.indexing.alias_recovery import AliasRecoveryService
    from ai_workshop.labs.rag.indexing.alias_recovery_types import AliasRecoveryError
    from ai_workshop.labs.rag.models.models import ProfileRecord

    c, db = assembly.source, assembly.db
    operation = db.operation
    db.rows.pop((AliasOperationRecord, db.operation_id))
    db.operation_id = operation.id = c.snapshot.operation_id
    for field in (
        "store_id",
        "cluster_uuid",
        "alias",
        "indexing_profile_id",
        "document_processing_profile_id",
        "created_at",
        "phase",
    ):
        setattr(operation, field, getattr(c.snapshot, field))
    operation.targets = list(c.snapshot.targets)
    db.rows[AliasOperationRecord, operation.id] = operation
    for pid, kind in c.profiles:
        db.rows[ProfileRecord, pid] = ProfileRecord(id=pid, kind=kind)
    build = UUID(c.snapshot.targets[0][-36:])
    db.rows[RagIndexBuildRecord, build] = RagIndexBuildRecord(
        id=build,
        indexing_profile_id=c.snapshot.indexing_profile_id,
        document_processing_profile_id=c.snapshot.document_processing_profile_id,
        index_name=c.snapshot.targets[0],
    )
    service = AliasRecoveryService(db, c.settings)
    claim = await service.freeze(operation.id, db.actor, uuid4(), c.snapshot.sha256)
    args = dict(assembly.args, claim=claim)
    m = module()
    ctx = m.NativeControlContext(**args)
    control = m.ConcreteNativeCutoverControl(ctx)
    epoch = await assembly.repo.acquire(claim, c.observed.identity)
    before = await assembly.repo.readback(claim)
    assert before.prepared == epoch and before.actions == ()
    actual_import = m.importlib.import_module

    def missing(name):
        if name.endswith("access_epoch_verification_native"):
            raise ImportError("synthetic-private-marker")
        return actual_import(name)

    monkeypatch.setattr(m.importlib, "import_module", missing)
    # Prepared readback means backend is not invoked; no fake verifier/proof exists.
    controller = LocalAccessEpochController(assembly.repo, SimpleNamespace(), control)
    with pytest.raises(AliasRecoveryError, match="^rag_alias_proof_invalid$"):
        await controller.advance(claim)
    assert await assembly.repo.readback(claim) == before
    assert ctx.held_owner is None and ctx.journal is None


def branch_port(assembly, c, monkeypatch):
    """Real port dispatch, real recorded slice; external SQL/kernel fixtures only.

    Missing final support deliberately prevents full acquire. This isolated
    branch harness exercises live-issued adapters without minting a verifier.
    """
    from ai_workshop.labs.rag.indexing.access_epoch_local import ControlOwnership

    m = module()
    context = m.NativeControlContext(**assembly.args)
    control = m.ConcreteNativeCutoverControl(context)
    monkeypatch.setattr(context, "assert_owned", c.journal._owned)
    monkeypatch.setattr(control, "_runtime", lambda: (context, c.epoch, c.journal, c.native))
    monkeypatch.setattr(control, "_owned", lambda owner: c.journal._owned())

    async def parent(action, ownership):
        c.journal._owned()
        state = await c.repo.readback(c.epoch.binding.claim)
        c.journal._owned()
        assert state.actions[-1].action == action
        return state

    monkeypatch.setattr(control, "_parent", parent)
    owner = ControlOwnership(
        c.owner.execution_id, c.owner.executor_generation, control.control_port_id
    )
    return m, context, control, owner


async def test_actual_app_recovery_retains_issued_cap_and_exact_prior_settlement(
    assembly, app_case, monkeypatch
):
    from tests.unit.labs.rag.indexing.test_access_epoch_app_retirement import reserve

    c = app_case
    action, ticket = await reserve(c)
    m, context, control, owner = branch_port(assembly, c, monkeypatch)
    context._apps = c.runner
    control._tickets[action.kind] = ticket
    control._expected_signatures[action.kind] = m._freeze(ticket)
    prior = await control.execute(action, owner)
    retained = context._caps["app_retirement"]
    native_calls = len(c.kernel.calls)
    recovered = await control.reconcile(action, owner)
    assert recovered is prior
    assert context._caps["app_retirement"] is retained
    assert len(c.kernel.calls) == native_calls
    c.runner.assert_issued(retained)
    with pytest.raises(ValueError, match="^native_control_denied$"):
        context._retain("app_retirement", replace(retained))


async def test_actual_admin_audit_recovery_retains_private_cap_and_exact_prior_settlement(
    assembly, admin_case, monkeypatch
):
    from tests.unit.labs.rag.indexing.test_access_epoch_bootstrap_audits import audit_case

    c = admin_case
    audit, action, credential = await audit_case(c)
    m, context, control, owner = branch_port(assembly, c, monkeypatch)
    context._administrator, context._audits = c.runner, audit
    # The real administrator has already completed its local reset; exercise
    # the actual recovery branch plus fresh five-read audit and later recovery.
    first = await control._dispatch(action, None)
    assert first is not None
    control._results[action.action_id] = first
    control._result_signatures[action.action_id] = m._freeze(first)
    old_credential, old_audit = context._caps["credential"], context._caps["admin_security"]
    assert old_credential.password.get_secret_value() == credential.password.get_secret_value()
    calls = len(c.native.calls)
    recovered = await control.reconcile(action, owner)
    assert recovered is first
    assert context._caps["credential"] is old_credential
    assert context._caps["admin_security"] is old_audit
    assert len(c.native.calls) == calls
    with pytest.raises(ValueError, match="^native_control_denied$"):
        context._retain("credential", replace(old_credential))


async def test_actual_repository_unknown_newer_than_prior_allows_fresh_reobservation(
    assembly, app_case, monkeypatch
):
    from datetime import UTC, datetime
    from uuid import UUID

    from ai_workshop.infrastructure.local.cutover_control_windows import WindowsControlLock
    from ai_workshop.labs.rag.indexing.access_epoch_app_retirement import RecordedAppRetirement
    from ai_workshop.labs.rag.indexing.access_epoch_submission import ProtectedControlJournal
    from ai_workshop.labs.rag.indexing.access_epoch_types import ControlSettlement
    from ai_workshop.labs.rag.indexing.alias_recovery_types import AliasRecoveryError
    from tests.unit.labs.rag.indexing.test_access_epoch_repository import setup
    from tests.unit.labs.rag.indexing.test_access_epoch_submission import Kernel, PrivateMemory

    _, repo, claim, original = await setup()
    epoch = await repo.acquire(claim, original)
    lock = WindowsControlLock(original.daemon_sha256, "ai-workshop", native=Kernel())
    held = lock.acquire(
        UUID(epoch.binding.execution_id), (await repo.readback(claim)).executor_generation
    )
    memory = PrivateMemory()
    journal = ProtectedControlJournal(
        module().PROJECT_ROOT, memory, memory, lock, held, lock.scope_sha256
    )
    c = SimpleNamespace(epoch=epoch, repo=repo, journal=journal, owner=held, native=app_case.native)
    c.runner = RecordedAppRetirement(epoch, repo, journal, app_case.issuer, c.native)
    try:
        ticket = await c.runner.prepare()
        action = await repo.reserve_action(epoch, ticket.kind, ticket.expected)
        m, context, control, owner = branch_port(assembly, c, monkeypatch)
        context._apps = c.runner
        control._tickets[action.kind] = ticket
        control._expected_signatures[action.kind] = m._freeze(ticket)
        prior = await control.execute(action, owner)
        unknown = ControlSettlement(
            action.action_id,
            action.execution_id,
            action.executor_generation,
            "unknown",
            "{}",
            datetime.now(UTC),
        )
        await repo.settle_action(action, unknown)
        with pytest.raises(AliasRecoveryError, match="rag_alias_claim_conflict"):
            await repo.settle_action(action, prior)
        calls = len(app_case.kernel.calls)
        recovered = await control.reconcile(action, owner)
        assert recovered is not None and recovered is not prior
        assert recovered.observed_at >= unknown.observed_at
        assert recovered.manifest_json == prior.manifest_json
        await repo.settle_action(action, recovered)
        assert (await repo.readback(claim)).actions[-1].outcome == "settled"
        assert len(app_case.kernel.calls) == calls
    finally:
        lock.close(held)


@pytest.mark.parametrize("change", ["same_pending", "newer_unknown", "failed_actual_read"])
async def test_actual_retirement_reobservation_preserves_source_event_time(
    assembly, settlement_case, monkeypatch, change
):
    import json
    from datetime import UTC, datetime

    from ai_workshop.labs.rag.indexing.access_epoch_process import RecordedOriginalControlProcess
    from ai_workshop.labs.rag.indexing.access_epoch_types import CutoverActionKind
    from tests.unit.labs.rag.indexing.test_access_epoch_settlement import reserved

    c = settlement_case
    stop = reserved(c, CutoverActionKind.STOP_OLD)
    stopped = await c.probe.observe(stop)
    stop_row = replace(
        c.repo.state.actions[-1],
        outcome="settled",
        manifest_json=stopped.manifest_json,
        observed_at=stopped.observed_at,
        event_sequence=stop.sequence + 1,
    )
    c.repo.state = replace(
        c.repo.state,
        actions=(stop_row,),
        phase="old_stopped",
        old_server_stopped_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    action = reserved(c, CutoverActionKind.RETIRE_OLD)
    prior = await c.probe.observe(action)
    c.native = SimpleNamespace()
    m, _, control, owner = branch_port(assembly, c, monkeypatch)
    control._original_process = RecordedOriginalControlProcess(
        c.epoch, c.repo, c.journal, c.native, c.journal.root
    )
    control._original_settlement = c.probe
    control._results[action.action_id] = prior
    control._result_signatures[action.action_id] = m._freeze(prior)
    c.probe.clock = lambda: datetime(2026, 1, 5, tzinfo=UTC)
    if change == "newer_unknown":
        old = c.repo.state.actions[-1]
        c.repo.state = replace(
            c.repo.state,
            actions=(
                stop_row,
                replace(
                    old,
                    outcome="unknown",
                    manifest_json="{}",
                    event_sequence=old.action.sequence + 1,
                    observed_at=datetime(2026, 1, 4, tzinfo=UTC),
                ),
            ),
        )
    elif change == "failed_actual_read":
        c.docker.fail = True
    observed = await control.reconcile(action, owner)
    if change == "failed_actual_read":
        assert observed is None
    else:
        assert observed is not None and observed.manifest_json == prior.manifest_json
        assert (
            json.loads(observed.manifest_json)["retired_at"] == "2026-01-03T00:00:00.000000+00:00"
        )
        assert (
            observed is prior
            if change == "same_pending"
            else observed.observed_at == datetime(2026, 1, 5, tzinfo=UTC)
        )


@pytest.fixture
async def preflight_boundary(assembly, monkeypatch):
    import hashlib
    import json

    from ai_workshop.infrastructure.local import control_process_windows as native
    from ai_workshop.labs.rag.indexing import access_epoch_route_commands as routes
    from ai_workshop.labs.rag.indexing import access_epoch_security_descriptor_source as descriptor
    from tests.unit.labs.rag.indexing.test_access_epoch_security_descriptor_source import Kernel

    packets = [f"public assembly fixture {i}\n".encode() for i in range(5)]
    kernel = Kernel(packets)
    monkeypatch.setattr(native, "NativeWindowsProcess", lambda: kernel)
    monkeypatch.setattr(descriptor, "_PINS", tuple(hashlib.sha256(x).hexdigest() for x in packets))
    monkeypatch.setattr(routes, "_binary_sha", lambda: "a" * 64)
    monkeypatch.setattr(routes, "_python_sha", lambda: "b" * 64)
    calls = []

    def run(argv, **options):
        calls.append((argv, options))
        packet = {
            "schema_version": 1,
            "java_feature": 25,
            "source_level": 21,
            "compiler_present": True,
        }
        return SimpleNamespace(returncode=0, stdout=json.dumps(packet).encode(), stderr=b"")

    monkeypatch.setattr(routes.subprocess, "run", run)
    return SimpleNamespace(kernel=kernel, calls=calls, descriptor=descriptor, routes=routes)


async def test_context_preepoch_actual_sources_are_owned_one_shot(assembly, preflight_boundary):
    m, boundary = module(), preflight_boundary
    ctx = m.NativeControlContext(**assembly.args)
    assert boundary.kernel.calls == boundary.calls == []
    assert ctx.route_commands is None and ctx.security_descriptor is None
    await ctx.prepare_sources()
    ctx.assert_preflight_sources()
    assert ctx.descriptor_source.assert_issued(ctx.security_descriptor) is None
    assert ctx.route_commands.context is ctx
    assert ctx.unmanaged is ctx.namespace_source.unmanaged(ctx.namespace)
    assert len(boundary.kernel.calls) == 5 and len(boundary.kernel.closed) == 25
    assert len(boundary.calls) == 1 and assembly.db.statements == []
    assert ctx.epoch is None and ctx.held_owner is None
    with pytest.raises(ValueError, match="^native_control_denied$"):
        await ctx.prepare_sources()
    assert len(boundary.kernel.calls) == 5 and len(boundary.calls) == 1


@pytest.mark.parametrize("member", ["descriptor", "source", "commands", "native"])
async def test_prepared_source_substitution_has_no_authority(assembly, preflight_boundary, member):
    ctx = module().NativeControlContext(**assembly.args)
    await ctx.prepare_sources()
    prepared = ctx._preflight_sources
    if member == "descriptor":
        object.__setattr__(prepared, "descriptor", replace(prepared.descriptor))
    else:
        object.__setattr__(prepared, member, SimpleNamespace())
    with pytest.raises(ValueError, match="^native_control_denied$"):
        ctx.assert_preflight_sources()


async def test_preflight_missing_software_poison_never_becomes_support(
    assembly, preflight_boundary
):
    ctx = module().NativeControlContext(**assembly.args)
    preflight_boundary.kernel.packets[0] = b"unknown software"
    with pytest.raises(ValueError, match="^native_control_denied$"):
        await ctx.prepare_sources()
    with pytest.raises(ValueError, match="^native_control_denied$"):
        await ctx.prepare_sources()
    with pytest.raises(ValueError, match="^native_control_unsupported$"):
        module().ConcreteNativeCutoverControl(ctx).assert_supported()
    assert len(preflight_boundary.kernel.calls) == 1
    assert preflight_boundary.calls == assembly.db.statements == []


async def test_preflight_route_receipt_cannot_be_copied_to_another_commands(
    assembly, preflight_boundary
):
    ctx = module().NativeControlContext(**assembly.args)
    await ctx.prepare_sources()
    original = ctx.route_commands
    other = preflight_boundary.routes.NativeRouteCommands(ctx)
    other._support = original._support
    other._support_signature = original._support_signature
    object.__setattr__(ctx._preflight_sources, "commands", other)
    with pytest.raises(ValueError, match="^native_control_denied$"):
        ctx.assert_preflight_sources()


async def test_prepared_sources_still_need_real_final_verifier_before_reservation(
    assembly, preflight_boundary, monkeypatch
):
    m = module()
    ctx = m.NativeControlContext(**assembly.args)
    await ctx.prepare_sources()
    actual_import = m.importlib.import_module

    def missing(name):
        if name.endswith("access_epoch_verification_native"):
            raise ImportError("synthetic-private-marker")
        return actual_import(name)

    monkeypatch.setattr(m.importlib, "import_module", missing)
    with pytest.raises(ValueError, match="^native_control_unsupported$"):
        m.ConcreteNativeCutoverControl(ctx).assert_supported()
    assert ctx.epoch is None and ctx.held_owner is None and assembly.db.statements == []


async def test_preepoch_cancellation_and_cleanup_keeps_primary_exception(
    assembly, preflight_boundary
):
    import asyncio

    ctx = module().NativeControlContext(**assembly.args)

    def cancelled(process):
        raise asyncio.CancelledError()

    preflight_boundary.kernel.poll = cancelled
    preflight_boundary.kernel.failure = "close"
    with pytest.raises(asyncio.CancelledError):
        await ctx.prepare_sources()
    assert ctx.security_descriptor is None and ctx.route_commands is None
    with pytest.raises(ValueError, match="^native_control_denied$"):
        await ctx.prepare_sources()
    assert len(preflight_boundary.kernel.calls) == 1 and len(preflight_boundary.kernel.closed) == 5
    assert assembly.db.statements == preflight_boundary.calls == []


async def test_preepoch_unknown_jdk_support_cannot_issue_combined_source(
    assembly, preflight_boundary, monkeypatch
):
    ctx = module().NativeControlContext(**assembly.args)
    monkeypatch.setattr(
        preflight_boundary.routes.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=b"{}", stderr=b""),
    )
    with pytest.raises(ValueError, match="^native_control_denied$"):
        await ctx.prepare_sources()
    assert ctx.security_descriptor is None and ctx.route_commands is None
    with pytest.raises(ValueError, match="^native_control_denied$"):
        await ctx.prepare_sources()
    assert len(preflight_boundary.kernel.calls) == 5 and assembly.db.statements == []


async def test_preepoch_attempt_marker_type_cannot_be_reset(assembly):
    ctx = module().NativeControlContext(**assembly.args)
    ctx._preflight_started = 0
    with pytest.raises(ValueError, match="^native_control_denied$"):
        ctx.assert_sources()


async def test_last_preepoch_check_failure_cannot_publish_reusable_source(
    assembly, preflight_boundary, monkeypatch
):
    ctx = module().NativeControlContext(**assembly.args)
    calls = 0

    def transient_binary_change():
        nonlocal calls
        calls += 1
        return "c" * 64 if calls == 5 else "a" * 64

    monkeypatch.setattr(preflight_boundary.routes, "_binary_sha", transient_binary_change)
    with pytest.raises(ValueError, match="^native_control_denied$"):
        await ctx.prepare_sources()
    assert calls == 5
    with pytest.raises(ValueError, match="^native_control_denied$"):
        ctx.assert_preflight_sources()
    assert ctx.security_descriptor is None and ctx.route_commands is None
    assert assembly.db.statements == []


async def test_preflight_retains_one_actual_security_inventory_issuer(assembly, preflight_boundary):
    from ai_workshop.labs.rag.indexing.access_epoch_security_inventory_native import (
        NativeSecurityInventory,
    )

    context = module().NativeControlContext(**assembly.args)
    await context.prepare_sources()
    issued = context.security_inventory_issuer
    assert type(issued) is NativeSecurityInventory and issued.context is context
    assert context.security_inventory_issuer is issued
    assert context.epoch is None and assembly.db.statements == []


async def test_context_rejects_equal_looking_security_issuer_substitution(
    assembly, preflight_boundary
):
    from ai_workshop.labs.rag.indexing.access_epoch_security_inventory_native import (
        NativeSecurityInventory,
    )

    context = module().NativeControlContext(**assembly.args)
    await context.prepare_sources()
    context._security_inventory = NativeSecurityInventory(context)
    with pytest.raises(ValueError, match="^native_control_denied$"):
        _ = context.security_inventory_issuer


@pytest.mark.parametrize("cancel", [False, True])
async def test_security_issuer_final_publication_failure_discards_all_preflight_caps(
    assembly, preflight_boundary, monkeypatch, cancel
):
    import asyncio

    cls = module().NativeControlContext
    getter = cls.security_inventory_issuer.fget
    context = cls(**assembly.args)
    published: list[object] = []

    def fail_once(current):
        value = getter(current)
        if value is not None and not published:
            published.append(value)
            if cancel:
                raise asyncio.CancelledError()
            raise ValueError("synthetic publication fault")
        return value

    monkeypatch.setattr(cls, "security_inventory_issuer", property(fail_once))
    error = asyncio.CancelledError if cancel else ValueError
    with pytest.raises(error):
        await context.prepare_sources()
    assert len(published) == 1 and context._preflight_failed is True
    assert context.security_inventory_issuer is None
    assert context.descriptor_source is None and context.route_commands is None
    with pytest.raises(ValueError):
        await context.prepare_sources()
    assert assembly.db.statements == [] and context.epoch is None


@pytest.mark.parametrize("mode", ["missing", "refuses", "false", "true", "cancel", "publication"])
async def test_partial_final_support_never_publishes_or_retries(
    assembly, preflight_boundary, monkeypatch, mode
):
    import asyncio

    m = module()
    context = m.NativeControlContext(**assembly.args)
    await context.prepare_sources()
    control = m.ConcreteNativeCutoverControl(context)
    actual_import = m.importlib.import_module
    created = []

    class IncompleteVerifier:
        __module__ = m._FINAL_MODULE

        def __init__(self, current):
            self.context = current
            self.checks = 0
            created.append(self)

        async def verify(self, *args):
            raise AssertionError("must_not_verify")

        def assert_issued(self, *args):
            raise AssertionError("must_not_issue")

        def assert_supported(self):
            self.checks += 1
            if mode == "refuses" or (mode == "publication" and self.checks >= 2):
                raise ValueError("synthetic support refusal")
            if mode == "cancel":
                raise asyncio.CancelledError()
            if mode == "false":
                return False
            if mode == "true":
                return True
            return None

    if mode == "missing":
        del IncompleteVerifier.assert_supported
    fake_module = SimpleNamespace(NativeFinalVerification=IncompleteVerifier)

    def incomplete(name):
        return fake_module if name == m._FINAL_MODULE else actual_import(name)

    monkeypatch.setattr(m.importlib, "import_module", incomplete)
    before = len(assembly.db.rows)
    error = asyncio.CancelledError if mode == "cancel" else ValueError
    with pytest.raises(error):
        control.assert_supported()
    assert created and len(created) == 1
    assert control._verification is None and context.verification is None
    with pytest.raises(ValueError, match="^native_control_unsupported$"):
        control.assert_supported()
    assert len(created) == 1
    assert len(assembly.db.rows) == before and assembly.db.statements == []
    assert context.epoch is None and context.held_owner is None
    assert len(preflight_boundary.kernel.calls) == 5


@pytest.mark.parametrize("kind", ["uuid", "datetime"])
def test_signature_rejects_subclasses_without_changing_exact_primitive_shape(kind: str) -> None:
    from datetime import UTC, datetime
    from uuid import UUID, uuid4

    from ai_workshop.labs.rag.indexing import access_epoch_control_native as control

    if kind == "uuid":

        class UUIDSubclass(UUID):
            pass

        ordinary_nonce = uuid4()
        altered_nonce = UUIDSubclass(int=ordinary_nonce.int)
        assert control._freeze(ordinary_nonce) == ("uuid", str(ordinary_nonce))
        assert ordinary_nonce == altered_nonce
        with pytest.raises(ValueError, match="^native_control_denied$"):
            control._freeze(altered_nonce)
    else:

        class DatetimeSubclass(datetime):
            pass

        ordinary_time = datetime(2020, 1, 1, tzinfo=UTC)
        altered_time = DatetimeSubclass(2020, 1, 1, tzinfo=UTC)
        assert control._freeze(ordinary_time) == ("datetime", ordinary_time.isoformat())
        assert ordinary_time == altered_time
        with pytest.raises(ValueError, match="^native_control_denied$"):
            control._freeze(altered_time)
