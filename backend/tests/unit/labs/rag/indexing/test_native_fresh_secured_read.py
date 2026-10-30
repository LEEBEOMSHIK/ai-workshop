"""Fresh committed observations through actual classes and synthetic I/O only."""

import asyncio
import importlib.util
import json
from copy import copy, deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256

import pytest

from tests.unit.labs.rag.indexing.native_fresh_secured_read_fixture_support import (
    assert_clean,
    prepare_transport,
    raw,
)

pytestmark = pytest.mark.asyncio
pytest_plugins = ["tests.unit.labs.rag.indexing.native_secured_read_graph_support"]


def module():
    name = "ai_workshop.labs.rag.indexing.access_epoch_fresh_secured_read"
    assert importlib.util.find_spec(name) is not None, "committed_fresh_source_missing"
    return importlib.import_module(name)


async def test_source_contract_is_present_and_direct_construction_is_denied():
    m = module()
    with pytest.raises((TypeError, ValueError)):
        m.NativeFreshSecuredReadSource()
    assert callable(m.NativeFreshSecuredReadSource.open_committed)


@pytest.mark.parametrize("method", ["observe_committed", "assert_observed", "close"])
async def test_source_contract_has_retained_observation_and_close_methods(method):
    assert callable(getattr(module().NativeFreshSecuredReadSource, method))


async def test_full_synthetic_fixture_matches_existing_new_assembly_catalog_and_decoders(
    material_graph,
    monkeypatch,
):
    from ai_workshop.labs.rag.indexing.access_epoch_docker_packets import validate_docker_identity
    from ai_workshop.labs.rag.indexing.access_epoch_server_packets import (
        ServerReadExpectation,
        validate_server_packets,
    )
    from tests.unit.labs.rag.indexing.native_fresh_secured_read_fixture_support import raw
    from tests.unit.labs.rag.indexing.test_access_epoch_docker_packets import arguments

    fixture = await prepare_transport(material_graph, monkeypatch)
    recipe = fixture.recipe
    deployment = validate_docker_identity(**arguments(recipe.docker))
    assert deployment.container_id == material_graph[3].proof.new_container_id
    public = validate_server_packets(
        ServerReadExpectation(**recipe.expected),
        **{name: raw(value) for name, value in recipe.server.items()},
        sampled_at=datetime.now(UTC),
    )
    assert material_graph[3].proof.new_ephemeral_id in public
    assert len(fixture.catalog.keys) == 3
    assert not fixture.kernel.created and not fixture.https.used
    assert material_graph[0].dml_count == material_graph[0].commit_count == 0


async def test_exact_five_docker_nine_https_issue_one_opaque_observation(
    material_graph, monkeypatch
):
    m = module()
    fixture = await prepare_transport(material_graph, monkeypatch)
    _, _, _, c, _ = material_graph
    before = datetime.now(UTC)
    reads = material_graph[0].select_count
    async with m.NativeFreshSecuredReadSource.open_committed() as source:
        assert not fixture.kernel.created and not fixture.https.used
        assert material_graph[0].select_count == reads
        cap = await source.observe_committed(c.claim)
        source.assert_observed(cap)
        assert cap.phase == "verified" and cap.ordinal == c.epoch.binding.ordinal
        assert str(cap.epoch_id) == c.epoch.binding.access_epoch_id
        assert str(cap.execution_id) == c.epoch.binding.execution_id
        assert before <= cap.start_at <= cap.end_at <= datetime.now(UTC)
        assert len(fixture.kernel.created) == 5 and len(fixture.https.used) == 9
        assert cap != copy(cap) and cap != replace(cap)
        public = json.loads(cap.public_json)
        assert set(public) == {
            "schema_version",
            "server",
            "config",
            "tls",
            "auth_policy",
            "key_ids",
        }
        assert type(public["schema_version"]) is int and public["schema_version"] == 1
        assert public["tls"] == fixture.recipe.docker.hashes
        assert (
            public["auth_policy"]
            == json.loads(dict(c.evidence.manifests)["auth_policy"])["auth_policy"]
        )
        assert dict(public["key_ids"]) == {key.role: key.key_id for key in fixture.catalog.keys}
        assert public["config"] == {
            "secured_yaml_sha256": sha256(fixture.recipe.docker.secured).hexdigest(),
            "public_security_profile": "project_http_tls_transport_mtls",
        }
        assert public["server"]["stable_node_id"] == c.proof.stable_node_id
        assert cap.public_json == raw(public).decode()
        assert all(
            key.encoded.get_secret_value() not in cap.public_json for key in fixture.catalog.keys
        )
        reads = material_graph[0].select_count
        for invalid in (copy(cap), replace(cap)):
            with pytest.raises(ValueError):
                source.assert_observed(invalid)
        with pytest.raises(ValueError):
            copy(source).assert_observed(cap)
        async with m.NativeFreshSecuredReadSource.open_committed() as other:
            with pytest.raises(ValueError):
                other.assert_observed(cap)
        original = cap.public_json
        object.__setattr__(cap, "public_json", "{}")
        with pytest.raises(ValueError):
            source.assert_observed(cap)
        object.__setattr__(cap, "public_json", original)
        source.assert_observed(cap)
        nonce_integer = cap.nonce.int

        class IntegerSubtype(int):
            pass

        try:
            object.__setattr__(cap.nonce, "int", IntegerSubtype(nonce_integer))
            with pytest.raises(ValueError):
                source.assert_observed(cap)
        finally:
            object.__setattr__(cap.nonce, "int", nonce_integer)
        source.assert_observed(cap)
        with pytest.raises(ValueError):
            await source.observe_committed(copy(c.claim))
        assert material_graph[0].select_count == reads
        assert len(fixture.kernel.created) == 5 and len(fixture.https.used) == 9
        assert "api_key" not in repr(cap) and "synthetic-reader" not in repr(cap)
    with pytest.raises(ValueError):
        source.assert_observed(cap)
    with pytest.raises(ValueError):
        await source.observe_committed(c.claim)
    await source.close()
    assert_clean(fixture)


async def test_full_fixture_runs_actual_native_lifecycle_and_http_parser(
    material_graph, monkeypatch
):
    from uuid import uuid4

    from ai_workshop.infrastructure.local.control_process_windows import WindowsControlProcess
    from ai_workshop.labs.rag.indexing.access_epoch_https_read import _capture_https_read
    from ai_workshop.labs.rag.indexing.access_epoch_secured_read_assembly import (
        NativeSecuredReadAssembly,
    )
    from ai_workshop.labs.rag.indexing.access_epoch_secured_read_process import (
        SecuredDockerReadCatalog,
        _capture_docker_read,
    )
    from tests.unit.labs.rag.indexing.native_fresh_secured_read_fixture_support import (
        assert_clean,
        raw,
    )

    fixture = await prepare_transport(material_graph, monkeypatch)
    nonce = uuid4()
    async with NativeSecuredReadAssembly.open_original() as assembly:
        deps = assembly.bind_committed()
        catalog = SecuredDockerReadCatalog(
            fixture.recipe.docker.manifest["container_id"],
            fixture.recipe.docker.manifest["image_id"],
        )
        for slot, name in enumerate(("daemon", "container", "network", "image", "volume")):
            native = WindowsControlProcess(max_output_bytes=2 * 1024 * 1024, max_wait_ms=10000)
            result = await _capture_docker_read(
                catalog=catalog,
                native=native,
                files=deps.private,
                nonce=nonce,
                slot=slot,
                binding_json='{"synthetic":true}',
                environment={"SYSTEMROOT": "C:\\Windows"},
            )
            assert result.exit_code == 0
            assert result.stdout == raw(fixture.recipe.docker.bodies[name])
        for slot in range(9):
            result = await _capture_https_read(fixture.catalog, slot)
            assert result.body
    assert len(fixture.kernel.created) == 5 and len(fixture.https.used) == 9
    assert_clean(fixture)


async def test_fresh_nonce_and_forward_receipt_then_backward_phase_denied(
    material_graph, monkeypatch
):
    from tests.unit.labs.rag.indexing.test_native_committed_tls import receipt

    m = module()
    fixture = await prepare_transport(material_graph, monkeypatch, rounds=2)
    store, _, _, c, _ = material_graph
    prior = deepcopy(store.tables)
    async with m.NativeFreshSecuredReadSource.open_committed() as source:
        first = await source.observe_committed(c.claim)
        await receipt(material_graph)
        second = await source.observe_committed(c.claim)
        assert first.nonce != second.nonce
        assert first.phase == "verified" and second.phase == "receipted"
        assert first.end_at <= second.start_at
        source.assert_observed(second)
        assert len(fixture.kernel.created) == 10 and len(fixture.https.used) == 18
        store.tables = prior
        with pytest.raises(ValueError):
            await source.observe_committed(c.claim)
        assert len(fixture.kernel.created) == 10 and len(fixture.https.used) == 18
    assert_clean(fixture)


@pytest.mark.parametrize("change", ["floor", "credential", "binary", "tls_identity"])
async def test_late_external_drift_prevents_observation_and_poison_stops_retry(
    material_graph, monkeypatch, change
):
    from ai_workshop.labs.rag.indexing.access_epoch_models import AccessEpochFloorRecord

    m = module()
    fixture = await prepare_transport(material_graph, monkeypatch)
    store, _, _, _, material = material_graph
    changed = False

    def after_response(event):
        nonlocal changed
        if event != "file_close" or changed:
            return
        changed = True
        if change == "floor":
            store.tables[AccessEpochFloorRecord.__tablename__][0]["identity"]["ordinal"] += 1
        elif change == "credential":
            # Ciphertext file loss is an external credential-state change.
            credential = next(
                path for path in material.files.rglob("*.dpapi") if "reader" in path.name
            )
            credential.unlink()
        elif change == "binary":
            fixture.binary.write_bytes(b"synthetic-replaced-binary-never-executed")
        else:
            target = material.mapped(fixture.recipe.tls.fixed_paths[1])
            replacement = target.with_suffix(".replacement")
            replacement.write_bytes(target.read_bytes())
            replacement.replace(target)

    fixture.https.peers[-1].hook = after_response
    async with m.NativeFreshSecuredReadSource.open_committed() as source:
        with pytest.raises(ValueError):
            await source.observe_committed(material_graph[3].claim)
        assert changed and len(fixture.https.used) == 9
        counts = len(fixture.kernel.created), len(fixture.https.used)
        with pytest.raises(ValueError):
            await source.observe_committed(material_graph[3].claim)
        assert (len(fixture.kernel.created), len(fixture.https.used)) == counts
    assert_clean(fixture)


@pytest.mark.parametrize("slot", [0, 8])
async def test_https_failure_never_issues_partial_capability_or_retries(
    material_graph, monkeypatch, slot
):
    m = module()
    fixture = await prepare_transport(material_graph, monkeypatch)
    fixture.https.peers[slot].respond(b"{}", status=503)
    async with m.NativeFreshSecuredReadSource.open_committed() as source:
        with pytest.raises(ValueError):
            await source.observe_committed(material_graph[3].claim)
        assert len(fixture.kernel.created) == 5
        assert len(fixture.https.used) == slot + 1
        with pytest.raises(ValueError):
            await source.observe_committed(material_graph[3].claim)
        assert len(fixture.https.used) == slot + 1
    assert_clean(fixture)


@pytest.mark.parametrize("failure", ["nonzero_exit", "wrong_identity"])
async def test_docker_failure_stops_before_any_https_read(material_graph, monkeypatch, failure):
    m = module()
    fixture = await prepare_transport(material_graph, monkeypatch)
    if failure == "nonzero_exit":
        fixture.kernel.exit_status = 23
    else:
        fixture.kernel.bodies[0] = b'{"ID":"other-daemon","OSType":"linux"}'
    async with m.NativeFreshSecuredReadSource.open_committed() as source:
        with pytest.raises(ValueError):
            await source.observe_committed(material_graph[3].claim)
        assert len(fixture.kernel.created) == (1 if failure == "nonzero_exit" else 5)
        assert not fixture.https.used
        before = len(fixture.kernel.created)
        with pytest.raises(ValueError):
            await source.observe_committed(material_graph[3].claim)
        assert len(fixture.kernel.created) == before
    assert_clean(fixture)


async def test_repeated_cancellation_waits_for_real_socket_cleanup_and_invalidates_source(
    material_graph, monkeypatch
):
    m = module()
    fixture = await prepare_transport(material_graph, monkeypatch)
    peer = fixture.https.peers[0]
    peer.allow_close.clear()
    source = None
    try:
        async with m.NativeFreshSecuredReadSource.open_committed() as source:
            task = asyncio.create_task(source.observe_committed(material_graph[3].claim))
            # Event barrier, no timer-based assumption about SQL/crypto speed.
            async with asyncio.timeout(240):
                while not peer.closing.is_set() and not task.done():
                    await asyncio.sleep(0.001)
            assert peer.closing.is_set() and not task.done()
            before = len(fixture.kernel.created), len(fixture.https.used)
            with pytest.raises(ValueError):
                await source.observe_committed(material_graph[3].claim)
            assert (len(fixture.kernel.created), len(fixture.https.used)) == before
            assert not task.done()
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            peer.allow_close.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            with pytest.raises(ValueError):
                await source.observe_committed(material_graph[3].claim)
            assert len(fixture.https.used) == 1
    finally:
        peer.allow_close.set()
        if source is not None:
            await source.close()
    assert_clean(fixture)


async def test_attempt_timeout_waits_for_socket_cleanup_and_preserves_note(
    material_graph, monkeypatch
):
    """Advance only the real event-loop clock, never product budgets or guards."""
    m = module()
    fixture = await prepare_transport(material_graph, monkeypatch)
    peer = fixture.https.peers[0]
    peer.allow_close.clear()
    peer.cleanup_error = True
    task = None
    try:
        async with m.NativeFreshSecuredReadSource.open_committed() as source:
            task = asyncio.create_task(source.observe_committed(material_graph[3].claim))
            async with asyncio.timeout(240):
                while not peer.closing.is_set() and not task.done():
                    await asyncio.sleep(0.001)
            assert peer.closing.is_set() and not task.done()
            loop = asyncio.get_running_loop()
            real_time = loop.time
            assert task.cancelling() == 0
            with monkeypatch.context() as external_clock:
                external_clock.setattr(loop, "time", lambda: real_time() + 241.0)
                # Due timer callbacks get actual loop turns. No task.cancel()
                # substitutes for the source's configured attempt deadline.
                for _ in range(20):
                    await asyncio.sleep(0)
                    if task.cancelling():
                        break
                assert task.cancelling() > 0
                assert not task.done(), "timeout_returned_before_socket_cleanup"
            assert not peer.allow_close.is_set()
            peer.allow_close.set()
            with pytest.raises(ValueError) as failure:
                await task
            assert "secured_https_cleanup_unverified" in getattr(failure.value, "__notes__", ())
            assert len(fixture.kernel.created) == 5 and len(fixture.https.used) == 1
            with pytest.raises(ValueError):
                await source.observe_committed(material_graph[3].claim)
            assert len(fixture.https.used) == 1
    finally:
        peer.allow_close.set()
        if task is not None and not task.done():
            task.cancel()
            await asyncio.wait((task,), timeout=5)
    # A failed socket close remains explicitly unverified; assert only the
    # separately confirmed native/DPAPI/SQL resources here.
    store, _, _, _, material = material_graph
    assert not fixture.kernel.open and not material.retained
    assert store.dml_count == store.commit_count == 0
    assert all(connection.closed for connection in store.connections)


async def test_external_close_does_not_wait_for_context_owner_task_to_exit(
    material_graph, monkeypatch
):
    """Owner directly observes: close must join the operation, not its caller task."""
    m = module()
    fixture = await prepare_transport(material_graph, monkeypatch)
    peer = fixture.https.peers[0]
    peer.allow_close.clear()
    published = asyncio.Queue(maxsize=1)

    async def own_context_and_observe():
        async with m.NativeFreshSecuredReadSource.open_committed() as source:
            published.put_nowait(source)
            await source.observe_committed(material_graph[3].claim)

    owner = asyncio.create_task(own_context_and_observe())
    closer = None
    try:
        source = await asyncio.wait_for(published.get(), timeout=15)
        async with asyncio.timeout(240):
            while not peer.closing.is_set() and not owner.done():
                await asyncio.sleep(0.001)
        assert peer.closing.is_set() and not owner.done()
        closer = asyncio.create_task(source.close())
        await asyncio.sleep(0)
        assert not closer.done()
        peer.allow_close.set()
        done, pending = await asyncio.wait((owner, closer), timeout=15)
        assert not pending, "external_close_waited_for_whole_context_owner_task"
        assert done == {owner, closer}
        assert closer.result() is None
        with pytest.raises(asyncio.CancelledError):
            owner.result()
        await source.close()
        assert len(fixture.https.used) == 1
    finally:
        peer.allow_close.set()
        tasks = [task for task in (owner, closer) if task is not None and not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=5)
    assert_clean(fixture)
