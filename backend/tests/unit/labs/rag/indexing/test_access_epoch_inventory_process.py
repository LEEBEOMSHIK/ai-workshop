"""Actual WindowsControlProcess boundary with fake kernel and private RAM ports."""

import asyncio
import importlib
import json
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from ai_workshop.infrastructure.local.control_process_windows import WindowsControlProcess

app_case: Any = importlib.import_module(
    "tests.unit.labs.rag.indexing.test_access_epoch_app_retirement"
).app_case
Kernel: Any = importlib.import_module(
    "tests.unit.labs.rag.indexing.test_access_epoch_final_auth_process"
).Kernel
bootstrap_case: Any = importlib.import_module(
    "tests.unit.labs.rag.indexing.test_access_epoch_bootstrap_retirement"
).bootstrap_case


def module() -> Any:
    return importlib.import_module("ai_workshop.labs.rag.indexing.access_epoch_inventory_process")


@pytest.fixture
async def case(app_case: Any, monkeypatch: pytest.MonkeyPatch) -> Any:  # noqa: F811
    c = app_case
    bindings = importlib.import_module(
        "tests.unit.labs.rag.indexing.test_access_epoch_inventory_binding"
    )
    b = await bindings.original_case(c)
    binding = await bindings.create(b, "original")
    monkeypatch.setattr(
        "ai_workshop.labs.rag.indexing.access_epoch_process._binary_sha", lambda: "c" * 64
    )
    kernel: Any = Kernel([b'{"synthetic_private_body":true}\n200'] * 8)
    native = WindowsControlProcess(native=kernel)

    def make(**changes: Any) -> Any:
        args = dict(
            factory=b.factory, binding=binding, repository=c.repo, journal=c.journal, native=native
        )
        args.update(changes)
        return module().RecordedInventoryReads(**args)

    return SimpleNamespace(
        base=c,
        factory=b.factory,
        binding=binding,
        parent=b.parent,
        repo=c.repo,
        journal=c.journal,
        memory=c.memory,
        kernel=kernel,
        native=native,
        make=make,
        runner=make(),
    )


def packet(c: Any, path: str) -> Any:
    return json.loads(c.memory.unprotect(c.memory.files[path]))


async def test_private_catalog_and_intent_precede_native_job_and_capture_is_issued(
    case: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = case
    monkeypatch.setenv("SYNTHETIC_SECRET", "never-forward")
    native_creates: list[dict[str, Any]] = []

    def check(name: str) -> None:
        if name == "create":
            catalog = packet(c, c.runner._catalog_path(c.parent))
            assert len(catalog["slots"]) == 1
            slot = catalog["slots"][0]
            assert slot["complete"] is False
            assert any(packet(c, path).get("state") == "intent" for path in c.memory.files)
            native_creates.append(catalog)

    c.kernel.before = check
    command = c.runner.commands.read_cluster("listing")
    observed = await c.runner.read(c.parent, command, 1)
    assert len(native_creates) == 1 and c.kernel.created == 1
    assert observed.parent == c.parent and observed.phase == "original" and observed.round == 1
    assert observed.purpose == "listing" and observed.index_name is None
    assert observed.private_body == b'{"synthetic_private_body":true}'
    assert "synthetic_private_body" not in repr(observed)
    assert c.runner.assert_issued(observed) is None
    assert c.repo.state.actions[-1].outcome == "pending"
    assert all("SYNTHETIC_SECRET" not in call[2] for call in c.kernel.calls if call[0] == "create")
    with pytest.raises(ValueError, match="inventory_process_denied"):
        c.runner.assert_issued(replace(observed))


async def test_completed_slot_recovers_with_fresh_command_and_no_native_replay(case: Any) -> None:
    c = case
    first = await c.runner.read(c.parent, c.runner.commands.read_cluster("listing"), 1)
    before_calls, before_files = list(c.kernel.calls), dict(c.memory.files)
    c.repo.state = replace(
        c.repo.state,
        actions=(
            *c.repo.state.actions[:-1],
            replace(
                c.repo.state.actions[-1], outcome="unknown", event_sequence=c.parent.sequence + 1
            ),
        ),
    )
    recovered_runner = c.make()
    second = await recovered_runner.read(
        c.parent, recovered_runner.commands.read_cluster("listing"), 1
    )
    assert second.private_body == first.private_body
    assert recovered_runner.assert_issued(second) is None
    assert c.kernel.calls == before_calls and c.memory.files == before_files


@pytest.mark.parametrize(
    "change",
    [
        "copy_command",
        "foreign_builder",
        "copy_binding",
        "factory",
        "repository",
        "native",
        "parent",
        "round_bool",
        "round_zero",
        "round_three_nonlisting",
        "round_four",
    ],
)
async def test_only_exact_builder_binding_parent_and_finite_rounds_can_launch(
    case: Any, change: str
) -> None:
    c = case
    command = c.runner.commands.read_cluster("listing")
    parent, round_number = c.parent, 1
    with pytest.raises(ValueError, match="inventory_process_denied"):
        if change == "copy_command":
            command = replace(command)
        elif change == "foreign_builder":
            builder = importlib.import_module(
                "ai_workshop.labs.rag.indexing.access_epoch_inventory_commands"
            ).InventoryCommands(c.binding, c.factory)
            command = builder.read_cluster("listing")
        elif change == "copy_binding":
            c.make(binding=replace(c.binding))
        elif change == "factory":
            c.make(factory=SimpleNamespace())
        elif change == "repository":
            c.make(repository=SimpleNamespace())
        elif change == "native":
            c.make(native=SimpleNamespace())
        elif change == "parent":
            parent = replace(parent, action_id=uuid4())
        elif change == "round_bool":
            round_number = True
        elif change == "round_zero":
            round_number = 0
        elif change == "round_three_nonlisting":
            command = c.runner.commands.read_cluster("nodes_info")
            round_number = 3
        else:
            round_number = 4
        await c.runner.read(parent, command, round_number)
    assert c.kernel.created == 0


@pytest.mark.parametrize(
    "change",
    [
        "closed",
        "unfrozen",
        "receipt",
        "generation",
        "prior_pending",
        "event_chain",
        "settled_parent",
        "phase",
    ],
)
async def test_fresh_db_guard_refuses_invalid_cutover_prefix_before_native(
    case: Any, change: str
) -> None:
    c = case
    state = c.repo.state
    if change == "closed":
        state = replace(state, operation_state="closed")
    elif change == "unfrozen":
        state = replace(state, gate_state="open")
    elif change == "receipt":
        state = replace(state, receipt=object())
    elif change == "generation":
        state = replace(state, executor_generation=str(uuid4()))
    elif change == "prior_pending":
        state = replace(
            state, actions=(replace(state.actions[0], outcome="pending"), *state.actions[1:])
        )
    elif change == "event_chain":
        state = replace(
            state, actions=(replace(state.actions[0], event_sequence=100), *state.actions[1:])
        )
    elif change == "settled_parent":
        state = replace(
            state, actions=(*state.actions[:-1], replace(state.actions[-1], outcome="settled"))
        )
    else:
        state = replace(state, phase="verified")
    c.repo.state = state
    with pytest.raises(ValueError, match="inventory_process_denied"):
        await c.runner.read(c.parent, c.runner.commands.read_cluster("listing"), 1)
    assert c.kernel.created == 0


async def test_owner_loss_after_resume_blocks_private_input_and_poison_prevents_replay(
    case: Any,
) -> None:
    c = case

    def change(name: str) -> None:
        if name == "resume":
            c.repo.state = replace(c.repo.state, executor_generation=str(uuid4()))

    c.kernel.before = change
    with pytest.raises(ValueError, match="inventory_process_denied"):
        await c.runner.read(c.parent, c.runner.commands.read_cluster("listing"), 1)
    assert c.kernel.created == 1
    assert not any(call[0] == "private_write" for call in c.kernel.calls)
    c.kernel.before = None
    c.repo.state = replace(c.repo.state, executor_generation=c.journal.owner.executor_generation)
    with pytest.raises(ValueError, match="inventory_process_denied"):
        replay = c.make()
        await replay.read(c.parent, replay.commands.read_cluster("nodes_info"), 1)
    assert c.kernel.created == 1


@pytest.mark.parametrize("failure", ["create", "resume", "private_write", "cancel"])
async def test_uncertain_helper_blocks_all_later_reads_without_second_submission(
    case: Any, failure: str
) -> None:
    c = case

    def fail(name: str) -> None:
        if name == ("resume" if failure == "cancel" else failure):
            if failure == "cancel":
                raise asyncio.CancelledError
            raise OSError("synthetic-private-native-error")

    c.kernel.before = fail
    with pytest.raises(asyncio.CancelledError if failure == "cancel" else ValueError):
        await c.runner.read(c.parent, c.runner.commands.read_cluster("listing"), 1)
    calls = list(c.kernel.calls)
    c.kernel.before = None
    with pytest.raises(ValueError, match="inventory_process_denied"):
        retry = c.make()
        await retry.read(c.parent, retry.commands.read_cluster("listing"), 1)
    assert c.kernel.calls == calls


async def test_initial_catalog_missing_after_write_failure_cannot_reopen_same_parent(
    case: Any,
) -> None:
    c = case

    def fail(path: str, content: bytes) -> None:
        raise OSError("synthetic-private-storage-error")

    c.memory.write = fail
    with pytest.raises(ValueError, match="inventory_process_denied"):
        await c.runner.read(c.parent, c.runner.commands.read_cluster("listing"), 1)
    with pytest.raises(ValueError, match="inventory_process_denied"):
        other = c.make()
        await other.read(c.parent, other.commands.read_cluster("listing"), 1)
    assert c.kernel.created == 0


@pytest.mark.parametrize(
    "output",
    [b'{"error":"synthetic-private"}\n403', b"{}\n000", b"x" * 262149],
    ids=["forbidden", "unknown_status", "oversized"],
)
async def test_failed_or_oversized_http_capture_never_issues_source_body(
    case: Any, output: bytes
) -> None:
    c = case
    c.kernel.outputs[0] = output
    with pytest.raises(ValueError, match="inventory_process_denied") as caught:
        await c.runner.read(c.parent, c.runner.commands.read_cluster("listing"), 1)
    assert "synthetic-private" not in str(caught.value)
    with pytest.raises(ValueError):
        await c.runner.read(c.parent, c.runner.commands.read_cluster("nodes_info"), 1)
    assert c.kernel.created == 1


async def test_finite_slot_limit_is_checked_before_another_native_creation(
    case: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = case
    monkeypatch.setattr(module(), "_MAX_SLOTS", 2)
    for purpose in ("listing", "nodes_info"):
        await c.runner.read(c.parent, c.runner.commands.read_cluster(purpose), 1)
    with pytest.raises(ValueError):
        await c.runner.read(c.parent, c.runner.commands.read_cluster("cluster_info"), 1)
    assert c.kernel.created == 2


async def test_raw_body_budget_reserves_a_bounded_response_before_launch(
    case: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = case
    monkeypatch.setattr(module(), "_MAX_TOTAL_BODY", 262144 + 10)
    await c.runner.read(c.parent, c.runner.commands.read_cluster("listing"), 1)
    with pytest.raises(ValueError):
        await c.runner.read(c.parent, c.runner.commands.read_cluster("nodes_info"), 1)
    assert c.kernel.created == 1


async def test_tampered_capture_or_catalog_cannot_issue_recovered_body(case: Any) -> None:
    c = case
    await c.runner.read(c.parent, c.runner.commands.read_cluster("listing"), 1)
    catalog = packet(c, c.runner._catalog_path(c.parent))
    path = c.runner._output_path(c.parent, catalog["slots"][0]["helper_id"])
    value = packet(c, path)
    value["binding"]["child"]["pid"] += 1
    c.memory.files[path] = c.memory.protect(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    )
    calls = list(c.kernel.calls)
    with pytest.raises(ValueError, match="inventory_process_denied"):
        recovered = c.make()
        await recovered.read(c.parent, recovered.commands.read_cluster("listing"), 1)
    assert c.kernel.calls == calls


@pytest.mark.parametrize("phase", ["bootstrap", "final"])
async def test_secure_phase_requires_actual_factory_and_keeps_collector_in_private_input(
    bootstrap_case: Any, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    c = bootstrap_case
    bindings = importlib.import_module(
        "tests.unit.labs.rag.indexing.test_access_epoch_inventory_binding"
    )
    b = await bindings.secure_case(c, monkeypatch, phase)
    binding = await bindings.create(b, phase)
    monkeypatch.setattr(module(), "PROJECT_ROOT", c.journal.root)
    kernel = Kernel([b'{"synthetic":"private-capture"}\n200'])
    runner = module().RecordedInventoryReads(
        b.factory, binding, c.repo, c.journal, WindowsControlProcess(native=kernel)
    )
    command = runner.commands.read_cluster("identity_state")
    secret = binding.collector_secret.get_secret_value()
    assert secret.encode() in command.private_stdin
    assert all(secret not in argument for argument in command.argv)
    result = await runner.read(b.parent, command, 1)
    assert result.phase == phase and runner.assert_issued(result) is None
    assert secret not in repr(result)
    assert kernel.created == 1


async def test_three_listing_rounds_are_distinct_and_closing_round_cannot_be_reopened(
    case: Any,
) -> None:
    c = case
    for round_number in (1, 2, 3):
        result = await c.runner.read(
            c.parent, c.runner.commands.read_cluster("listing"), round_number
        )
        assert result.round == round_number
    with pytest.raises(ValueError):
        await c.runner.read(c.parent, c.runner.commands.read_cluster("nodes_info"), 2)
    assert c.kernel.created == 3


@pytest.mark.parametrize(
    "field", ["stdout", "private_command", "missing_capture", "catalog_rollback"]
)
async def test_retained_native_origin_rejects_fabricated_or_missing_private_recovery(
    case: Any, field: str
) -> None:
    c = case
    await c.runner.read(c.parent, c.runner.commands.read_cluster("listing"), 1)
    catalog_path = c.runner._catalog_path(c.parent)
    catalog = packet(c, catalog_path)
    slot = catalog["slots"][0]
    output = c.runner._output_path(c.parent, slot["helper_id"])
    path = output
    value = packet(c, output)
    if field == "stdout":
        import base64

        value["stdout"] = base64.b64encode(b'{"fabricated":true}\n200').decode()
    elif field == "private_command":
        path = c.runner._slot_path(c.parent, slot["helper_id"], "command")
        value = packet(c, path)
        value["stdin"] = "ZmFrZQ=="
    elif field == "missing_capture":
        del c.memory.files[path]
    else:
        path, value = catalog_path, catalog
        value["slots"] = []
    if field != "missing_capture":
        c.memory.files[path] = c.memory.protect(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        )
    before = list(c.kernel.calls)
    with pytest.raises(ValueError, match="inventory_process_denied"):
        recovered = c.make()
        await recovered.read(c.parent, recovered.commands.read_cluster("listing"), 1)
    assert c.kernel.calls == before


async def test_lost_catalog_write_ack_never_allows_another_binding_for_same_parent(
    case: Any,
) -> None:
    c = case
    c.memory.lost_ack = True
    with pytest.raises(ValueError):
        await c.runner.read(c.parent, c.runner.commands.read_cluster("listing"), 1)
    c.memory.lost_ack = False
    # This is an actual factory-issued binding, still not permission to reopen.
    another = c.factory._issue("original", c.parent, c.binding.container_id, None)
    with pytest.raises(ValueError, match="inventory_process_denied"):
        c.make(binding=another)
    assert c.kernel.created == 0


async def test_completed_parent_prefix_cannot_drift_between_helpers(case: Any) -> None:
    c = case
    await c.runner.read(c.parent, c.runner.commands.read_cluster("listing"), 1)
    c.repo.state = replace(
        c.repo.state,
        actions=(
            replace(c.repo.state.actions[0], manifest_json='{"changed":true}'),
            *c.repo.state.actions[1:],
        ),
    )
    with pytest.raises(ValueError, match="inventory_process_denied"):
        await c.runner.read(c.parent, c.runner.commands.read_cluster("nodes_info"), 1)
    assert c.kernel.created == 1


async def test_owned_docker_binary_cannot_change_after_binding(
    case: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = case
    command = c.runner.commands.read_cluster("listing")
    monkeypatch.setattr(
        "ai_workshop.labs.rag.indexing.access_epoch_process._binary_sha", lambda: "d" * 64
    )
    with pytest.raises(ValueError, match="inventory_process_denied"):
        await c.runner.read(c.parent, command, 1)
    assert c.kernel.created == 0


@pytest.mark.parametrize("change", ["parent_expected", "boolean_round"])
async def test_issued_capture_signature_cannot_follow_mutated_nested_dto(
    case: Any, change: str
) -> None:
    c = case
    observed = await c.runner.read(c.parent, c.runner.commands.read_cluster("listing"), 1)
    if change == "parent_expected":
        object.__setattr__(observed.parent.expected, "identity_json", '{"changed":true}')
    else:
        object.__setattr__(observed, "round", True)
    with pytest.raises(ValueError, match="inventory_process_denied"):
        c.runner.assert_issued(observed)


async def test_public_revalidation_checks_fresh_owner_after_last_capture(case: Any) -> None:
    c = case
    await c.runner.read(c.parent, c.runner.commands.read_cluster("listing"), 1)
    assert await c.runner.revalidate(c.parent) is None
    c.repo.state = replace(c.repo.state, executor_generation=str(uuid4()))
    calls = list(c.kernel.calls)
    with pytest.raises(ValueError, match="inventory_process_denied"):
        await c.runner.revalidate(c.parent)
    assert c.kernel.calls == calls


async def test_prior_prefix_snapshot_does_not_alias_mutable_readback_dto(case: Any) -> None:
    c = case
    await c.runner.read(c.parent, c.runner.commands.read_cluster("listing"), 1)
    object.__setattr__(c.repo.state.actions[0], "manifest_json", '{"changed":true}')
    with pytest.raises(ValueError, match="inventory_process_denied"):
        await c.runner.read(c.parent, c.runner.commands.read_cluster("nodes_info"), 1)
    assert c.kernel.created == 1


async def test_repeated_recovery_reuses_one_capability_per_slot_and_bounds_private_retention(
    case: Any,
) -> None:
    c = case
    first = await c.runner.read(c.parent, c.runner.commands.read_cluster("listing"), 1)
    recovered = await c.runner.read(c.parent, c.runner.commands.read_cluster("listing"), 1)
    assert recovered is first
    assert c.kernel.created == 1
