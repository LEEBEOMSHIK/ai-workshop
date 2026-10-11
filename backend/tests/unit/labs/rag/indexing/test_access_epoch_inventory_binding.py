"""Inventory read authority binds current exact parent and issued source truth."""

import base64
import importlib
from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr

from ai_workshop.labs.rag.indexing.access_epoch_history_gate import VerifiedHistoricalControls
from ai_workshop.labs.rag.indexing.access_epoch_local import CUTOVER_ORDER
from ai_workshop.labs.rag.indexing.access_epoch_permissions import AccessEpochPermissions
from ai_workshop.labs.rag.indexing.access_epoch_repository import ActionReadback
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    ControlExpectedIdentity,
    CutoverActionKind,
    ReservedCutoverAction,
)
from ai_workshop.labs.rag.indexing.contracts import IndexDescriptor
from tests.unit.labs.rag.indexing import test_access_epoch_deployment as df
from tests.unit.labs.rag.indexing.test_access_epoch_app_retirement import (
    app_case,  # noqa: F401
    reserve,
)
from tests.unit.labs.rag.indexing.test_access_epoch_bootstrap_retirement import (
    bootstrap_case,  # noqa: F401
)
from tests.unit.labs.rag.indexing.test_access_epoch_final_auth_binding import binding_case


def module():
    return importlib.import_module("ai_workshop.labs.rag.indexing.access_epoch_inventory_binding")


def pending(c, kind):
    previous = c.repo.state.actions[-1].event_sequence
    action = ReservedCutoverAction(
        uuid4(),
        c.journal.owner.execution_id,
        previous + 1,
        kind,
        ControlExpectedIdentity("{}", previous),
        c.journal.owner.executor_generation,
    )
    c.repo.state = replace(
        c.repo.state,
        actions=(
            *c.repo.state.actions,
            ActionReadback(action, "pending", None, df.NOW, action.sequence),
        ),
    )
    return action


async def original_case(c):
    action, ticket = await reserve(c)
    retirement = await c.runner.run(action, ticket)
    row = c.repo.state.actions[0]
    c.repo.state = replace(
        c.repo.state,
        actions=(
            replace(
                row,
                outcome="settled",
                manifest_json=retirement.manifest_json,
                event_sequence=row.action.sequence + 1,
            ),
        ),
    )
    parent = pending(c, CutoverActionKind.STOP_OLD)
    history_ticket = VerifiedHistoricalControls("{}")

    class History:
        epoch, repository, journal = c.epoch, c.repo, c.journal
        revoked = False

        async def assert_verified(self, value):
            if self.revoked or value is not history_ticket:
                raise ValueError("synthetic-private-history-detail")

    history = History()
    permissions = AccessEpochPermissions("synthetic", ((uuid4(), None),))
    factory = module().InventoryReadBindingFactory.for_original(
        c.epoch,
        c.repo,
        c.journal,
        permissions,
        history,
        c.runner,
    )
    return SimpleNamespace(
        factory=factory,
        parent=parent,
        retirement=retirement,
        history=history,
        ticket=history_ticket,
    )


async def secure_case(c, monkeypatch, phase):
    b = await binding_case(c, monkeypatch)
    old = b.factory
    monkeypatch.setattr(module(), "PROJECT_ROOT", c.journal.root)
    factory = module().InventoryReadBindingFactory.for_secure(
        old.repository,
        old.keys,
        old.journal,
        old.deployment,
        old.bootstrap_factory,
        old.bootstrap,
        old.tls,
        old.store,
    )
    if phase == "bootstrap":
        count = CUTOVER_ORDER.index(CutoverActionKind.STOP_BOOTSTRAP)
        c.repo.state = replace(
            c.repo.state, phase="old_retired", actions=c.repo.state.actions[:count]
        )
        parent = pending(c, CutoverActionKind.STOP_BOOTSTRAP)
        observed = c.bootstrap
    else:
        parent = pending(c, CutoverActionKind.VERIFY_ACCESS)
        observed = b.final
    return SimpleNamespace(
        factory=factory, parent=parent, observed=observed, rows=b.rows, envelopes=b.envelopes
    )


async def create(b, phase):
    if phase == "original":
        return await b.factory.create_original(b.parent, b.retirement, b.ticket)
    return await getattr(b.factory, "create_" + phase)(b.parent, b.observed)


async def test_original_before_stop_requires_issued_apps_and_history(app_case):  # noqa: F811
    b = await original_case(app_case)
    value = await create(b, "original")
    assert value.phase == "original"
    assert value.parent_action_id == b.parent.action_id
    assert value.container_id == app_case.epoch.original.container_id
    assert value.collector_secret is None
    assert b.factory.assert_issued(value) is None
    with pytest.raises(ValueError, match="inventory_read_binding_unverified"):
        b.factory.assert_issued(replace(value))


@pytest.mark.parametrize("phase", ["bootstrap", "final"])
async def test_secure_reads_derive_collector_from_exact_completed_ledger(
    bootstrap_case,  # noqa: F811
    monkeypatch,
    phase,  # noqa: F811
):
    c = bootstrap_case
    b = await secure_case(c, monkeypatch, phase)
    value = await create(b, phase)
    assert value.phase == phase
    assert value.parent_action_id == b.parent.action_id
    assert value.epoch_id == UUID(c.epoch.binding.access_epoch_id)
    assert value.container_id == b.observed.container_id
    assert value.collector_secret == b.envelopes["collector"].secret
    assert value.permissions is b.factory.bootstrap.permissions
    assert "private" not in repr(value)
    assert b.factory.assert_issued(value) is None
    with pytest.raises(ValueError):
        b.factory.assert_issued(replace(value))
    assert c.native.calls == []


@pytest.mark.parametrize("phase", ["bootstrap", "final"])
async def test_unknown_parent_is_readable_without_reissuing_a_control(
    bootstrap_case,  # noqa: F811
    monkeypatch,
    phase,  # noqa: F811
):
    c = bootstrap_case
    b = await secure_case(c, monkeypatch, phase)
    c.repo.state = replace(
        c.repo.state,
        actions=(
            *c.repo.state.actions[:-1],
            replace(
                c.repo.state.actions[-1],
                outcome="unknown",
                manifest_json="{}",
                event_sequence=b.parent.sequence + 1,
            ),
        ),
    )
    assert (await create(b, phase)).phase == phase
    assert c.native.calls == []


async def test_original_unknown_parent_uses_existing_issued_history_only(app_case):  # noqa: F811
    b = await original_case(app_case)
    app_case.repo.state = replace(
        app_case.repo.state,
        actions=(
            app_case.repo.state.actions[0],
            replace(
                app_case.repo.state.actions[-1],
                outcome="unknown",
                manifest_json="{}",
                event_sequence=b.parent.sequence + 1,
            ),
        ),
    )
    assert (await create(b, "original")).collector_secret is None


@pytest.mark.parametrize("phase", ["bootstrap", "final"])
async def test_changing_protected_collector_between_reads_cannot_mint(
    bootstrap_case,  # noqa: F811
    monkeypatch,
    phase,  # noqa: F811
):
    c = bootstrap_case
    b = await secure_case(c, monkeypatch, phase)
    source = b.factory._sources
    original = source.store.read_prepared
    calls = 0

    def changed(epoch, ordinal, role, key_id):
        nonlocal calls
        value = original(epoch, ordinal, role, key_id)
        if role == "collector":
            calls += 1
            if calls == 2:
                return replace(
                    value,
                    secret=SecretStr(
                        base64.b64encode(
                            (key_id + ":different-synthetic").encode(),
                        ).decode()
                    ),
                )
        return value

    monkeypatch.setattr(source.store, "read_prepared", changed)
    with pytest.raises(ValueError, match="inventory_read_binding_unverified"):
        await create(b, phase)
    assert c.native.calls == []


@pytest.mark.parametrize(
    "change",
    [
        "copy_apps",
        "copy_history",
        "history_revoked",
        "wrong_parent",
        "settled_parent",
        "changed_generation",
        "prior_manifest",
        "closed",
        "receipt",
    ],
)
async def test_original_cannot_mint_from_unissued_or_wrong_current_state(
    app_case,  # noqa: F811
    change,  # noqa: F811
):
    c = app_case
    b = await original_case(c)
    if change == "copy_apps":
        b.retirement = replace(b.retirement)
    elif change == "copy_history":
        b.ticket = replace(b.ticket)
    elif change == "history_revoked":
        b.history.revoked = True
    elif change == "wrong_parent":
        b.parent = replace(b.parent, action_id=uuid4())
    elif change == "settled_parent":
        c.repo.state = replace(
            c.repo.state,
            actions=(
                c.repo.state.actions[0],
                replace(
                    c.repo.state.actions[1],
                    outcome="settled",
                    manifest_json="{}",
                    event_sequence=b.parent.sequence + 1,
                ),
            ),
        )
    elif change == "changed_generation":
        c.repo.state = replace(c.repo.state, executor_generation=str(uuid4()))
    elif change == "prior_manifest":
        c.repo.state = replace(
            c.repo.state,
            actions=(
                replace(c.repo.state.actions[0], manifest_json="{}"),
                c.repo.state.actions[1],
            ),
        )
    elif change == "closed":
        c.repo.state = replace(c.repo.state, operation_state="closed")
    else:
        c.repo.state = replace(c.repo.state, receipt=object())
    with pytest.raises(ValueError, match="inventory_read_binding_unverified"):
        await create(b, "original")


@pytest.mark.parametrize("phase", ["bootstrap", "final"])
@pytest.mark.parametrize(
    "change",
    [
        "copy_deployment",
        "wrong_parent",
        "settled_parent",
        "pending_keys",
        "descriptor",
        "group",
        "missing_secret",
        "secret_identity",
        "invalid_encoded",
        "tls",
        "generation",
        "bool_sequence",
        "prefix",
        "state_changes",
        "lost_owner",
    ],
)
async def test_secure_denies_unqualified_ledger_credentials_and_parent(
    bootstrap_case,  # noqa: F811
    monkeypatch,
    phase,
    change,  # noqa: F811
):
    c = bootstrap_case
    b = await secure_case(c, monkeypatch, phase)
    if change == "copy_deployment":
        b.observed = replace(b.observed)
    elif change == "wrong_parent":
        b.parent = replace(b.parent, kind=CutoverActionKind.START_REGISTERED_APPS)
    elif change == "settled_parent":
        c.repo.state = replace(
            c.repo.state,
            actions=(
                *c.repo.state.actions[:-1],
                replace(
                    c.repo.state.actions[-1],
                    outcome="settled",
                    manifest_json="{}",
                    event_sequence=b.parent.sequence + 1,
                ),
            ),
        )
    elif change == "pending_keys":
        b.rows[0] = replace(b.rows[0], outcome="pending", result=None)
    elif change == "descriptor":
        b.rows[0] = replace(
            b.rows[0], action=replace(b.rows[0].action, permissions_sha256="a" * 64)
        )
    elif change == "group":
        c.repo.state = replace(
            c.repo.state,
            actions=tuple(
                replace(x, manifest_json="{}")
                if x.action.kind == CutoverActionKind.ISSUE_ROLE_KEY
                else x
                for x in c.repo.state.actions
            ),
        )
    elif change == "missing_secret":
        b.envelopes["collector"] = None
    elif change == "secret_identity":
        b.envelopes["collector"] = replace(b.envelopes["collector"], key_id="different")
    elif change == "invalid_encoded":
        b.envelopes["collector"] = replace(
            b.envelopes["collector"],
            secret=SecretStr(
                base64.b64encode(b"wrong-id:synthetic").decode(),
            ),
        )
    elif change == "tls":
        monkeypatch.setattr(
            b.factory.tls, "assert_issued", lambda _: (_ for _ in ()).throw(ValueError())
        )
    elif change == "generation":
        c.repo.state = replace(c.repo.state, executor_generation=str(uuid4()))
    elif change == "bool_sequence":
        c.repo.state = replace(
            c.repo.state,
            actions=(
                replace(
                    c.repo.state.actions[0],
                    action=replace(c.repo.state.actions[0].action, sequence=True),
                ),
                *c.repo.state.actions[1:],
            ),
        )
    elif change == "prefix":
        c.repo.state = replace(c.repo.state, actions=c.repo.state.actions[1:])
    elif change == "state_changes":
        original = c.repo.readback
        calls = 0

        async def changed(claim):
            nonlocal calls
            calls += 1
            state = await original(claim)
            return replace(state, phase="verified") if calls >= 2 else state

        monkeypatch.setattr(c.repo, "readback", changed)
    else:
        c.journal.owner = replace(c.journal.owner)
    with pytest.raises(ValueError, match="inventory_read_binding_unverified"):
        await create(b, phase)
    assert c.native.calls == []


_SCOPE_MUTATIONS = [
    "prefix",
    "namespaces",
    "list_namespaces",
    "string_uuid",
    "nested_uuid",
    "equal_binding_replacement",
    "equal_factory_replacement",
]


def mutate_scope(factory, binding, change):
    permissions = binding.permissions
    if change == "prefix":
        object.__setattr__(permissions, "prefix", "foreign")
    elif change == "namespaces":
        object.__setattr__(permissions, "namespaces", ((uuid4(), None),))
    elif change == "list_namespaces":
        object.__setattr__(permissions, "namespaces", list(permissions.namespaces))
    elif change == "string_uuid":
        object.__setattr__(permissions, "namespaces", ((str(uuid4()), None),))
    elif change == "nested_uuid":
        object.__setattr__(permissions.namespaces[0][0], "int", uuid4().int)
    elif change == "equal_binding_replacement":
        object.__setattr__(binding, "permissions", replace(permissions))
    else:
        factory.permissions = replace(permissions)


@pytest.mark.parametrize("change", _SCOPE_MUTATIONS)
async def test_same_original_permission_object_mutation_or_equal_replacement_denied(
    app_case,  # noqa: F811
    change,  # noqa: F811
):
    b = await original_case(app_case)
    binding = await create(b, "original")
    mutate_scope(b.factory, binding, change)
    with pytest.raises(ValueError, match="inventory_read_binding_unverified"):
        b.factory.assert_issued(binding)
    if change != "equal_binding_replacement":
        with pytest.raises(ValueError, match="inventory_read_binding_unverified"):
            await create(b, "original")


@pytest.mark.parametrize("phase", ["bootstrap", "final"])
@pytest.mark.parametrize("change", _SCOPE_MUTATIONS)
async def test_same_secure_permission_object_mutation_or_equal_replacement_denied(
    bootstrap_case,  # noqa: F811
    monkeypatch,
    phase,
    change,  # noqa: F811
):
    b = await secure_case(bootstrap_case, monkeypatch, phase)
    binding = await create(b, phase)
    mutate_scope(b.factory, binding, change)
    with pytest.raises(ValueError, match="inventory_read_binding_unverified"):
        b.factory.assert_issued(binding)
    assert bootstrap_case.native.calls == []


async def test_existing_command_builder_cannot_read_after_prefix_scope_mutation(app_case):  # noqa: F811
    from ai_workshop.labs.rag.indexing.access_epoch_inventory_commands import InventoryCommands

    b = await original_case(app_case)
    binding = await create(b, "original")
    commands = InventoryCommands(binding, b.factory)
    profile = binding.permissions.namespaces[0][0]
    original = IndexDescriptor(1, "cosine").concrete_index_name(
        binding.permissions.prefix,
        profile,
        uuid4(),
    )
    commands.read_index(original, "metadata")
    object.__setattr__(binding.permissions, "prefix", "foreign")
    foreign = IndexDescriptor(1, "cosine").concrete_index_name("foreign", profile, uuid4())
    with pytest.raises(ValueError, match="inventory_command_denied"):
        commands.read_index(foreign, "metadata")
