"""Pinned public software source: no original Docker/JVM/network is invoked."""

import hashlib
from collections.abc import Callable
from dataclasses import replace
from importlib import import_module
from typing import Any, cast

import pytest

from ai_workshop.infrastructure.local.control_process_windows import (
    NativeChild,
    WindowsControlProcess,
)

deployment_case = cast(
    Callable[[pytest.MonkeyPatch], tuple[Any, ...]],
    import_module("tests.unit.labs.rag.indexing.test_access_epoch_native").deployment_case,
)


class Kernel:
    def __init__(self, packets: list[bytes]) -> None:
        self.packets = packets
        self.calls: list[Any] = []
        self.closed: list[int] = []
        self.resumed: list[int] = []
        self.outputs: dict[int, bytes] = {}
        self.code = 0
        self.failure: str | None = None
        self.active = 0

    def thread_id(self) -> int:
        return 1

    def create(self, argv: Any, env: Any, cwd: Any, *, stdin_pipe: bool = False) -> NativeChild:
        self.calls.append((argv, env, cwd, stdin_pipe))
        ordinal = len(self.calls) - 1
        base = 100 + ordinal * 10
        self.outputs[base + 3] = self.packets[ordinal]
        self.outputs[base + 4] = b""
        return NativeChild(base, base + 1, base + 2, base + 3, base + 4, base, "1000")

    def resume(self, thread: int) -> int:
        if self.failure == "resume":
            raise RuntimeError("synthetic-private-marker")
        self.resumed.append(thread)
        return 1

    def poll(self, process: int) -> bool:
        return True

    def active_processes(self, job: int) -> int:
        return self.active

    def read(self, pipe: int, limit: int) -> bytes:
        if self.failure == "read":
            raise RuntimeError("synthetic-private-marker")
        value = self.outputs[pipe][:limit]
        self.outputs[pipe] = self.outputs[pipe][len(value) :]
        return value

    def exit_code(self, process: int) -> int:
        return self.code

    def write(self, pipe: int, data: memoryview) -> int:
        raise AssertionError("stdin must use NUL")

    def close(self, handle: int) -> None:
        self.closed.append(handle)
        if self.failure == "close":
            raise RuntimeError("synthetic-private-marker")


async def case(monkeypatch: pytest.MonkeyPatch, *, wait_ms: int = 30000) -> tuple[Any, ...]:
    from ai_workshop.labs.rag.indexing import access_epoch_security_descriptor_source as module

    original, snapshot, runner, reader = deployment_case(monkeypatch)
    observation = await original.observe_deployment(snapshot)
    packets = [f"public software fixture {i}\n".encode() for i in range(5)]
    monkeypatch.setattr(module, "_PINS", tuple(hashlib.sha256(x).hexdigest() for x in packets))
    kernel = Kernel(packets)
    process = WindowsControlProcess(kernel, max_wait_ms=wait_ms)
    source = module.OriginalSecurityDescriptorSource(
        original.settings, original, observation, process
    )
    return module, source, snapshot, kernel, original, observation, runner, reader


async def test_five_owned_captures_emit_exact_closed_descriptor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, source, snapshot, kernel, original, observed, _, _ = await case(monkeypatch)
    cap = await source.observe(snapshot)
    assert type(cap) is module.ObservedSecurityDescriptor
    assert cap.image is observed.image
    assert cap.snapshot_sha256 == snapshot.sha256
    assert cap.original_deployment_sha256 == observed.identity.deployment_sha256
    assert (cap.primary_name, cap.alias_name, cap.index_format) == (".security-7", ".security", 6)
    assert (cap.security_version, cap.mapping_version) == ("8.14.0", 5)
    assert cap.hidden is True
    assert source.assert_issued(cap) is None
    assert len(kernel.calls) == len(kernel.resumed) == 5
    assert len(kernel.closed) == 25
    for argv, env, cwd, stdin in kernel.calls:
        assert argv[:5] == (
            module.DOCKER_EXE,
            "--host",
            "npipe:////./pipe/dockerDesktopLinuxEngine",
            "exec",
            observed.identity.container_id,
        )
        assert argv[5:10] == (
            "/usr/share/elasticsearch/jdk/bin/javap",
            "-c",
            "-p",
            "-constants",
            "-classpath",
        )
        assert env == {"SystemRoot": r"C:\Windows", "WINDIR": r"C:\Windows"}
        assert cwd == module._CWD and stdin is False
    assert "fixture" not in repr(cap)
    assert not hasattr(cap, "packets")
    with pytest.raises(ValueError, match="security_descriptor_source_unverified"):
        await source.observe(snapshot)


@pytest.mark.parametrize("slot", range(5))
@pytest.mark.parametrize("change", ["changed", "empty", "extra", "invalid_utf8", "bare_cr"])
async def test_each_full_packet_pin_is_required_and_failure_is_one_shot(
    monkeypatch: pytest.MonkeyPatch, slot: int, change: str
) -> None:
    _, source, snapshot, kernel, *_ = await case(monkeypatch)
    packet = kernel.packets[slot]
    kernel.packets[slot] = {
        "changed": packet.replace(b"fixture", b"altered"),
        "empty": b"",
        "extra": packet + b"x",
        "invalid_utf8": b"\xff",
        "bare_cr": packet.replace(b"\n", b"\r"),
    }[change]
    with pytest.raises(ValueError, match="^security_descriptor_source_unverified$"):
        await source.observe(snapshot)
    calls = len(kernel.calls)
    with pytest.raises(ValueError):
        await source.observe(snapshot)
    assert len(kernel.calls) == calls
    assert len(kernel.closed) == 5 * calls


async def test_only_crlf_normalization_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    _, source, snapshot, kernel, *_ = await case(monkeypatch)
    kernel.packets = [x.replace(b"\n", b"\r\n") for x in kernel.packets]
    source.assert_issued(await source.observe(snapshot))


@pytest.mark.parametrize(
    "failure", ["resume", "read", "close", "nonzero", "stderr", "oversize", "active"]
)
async def test_child_failure_poison_and_cleanup_never_issue(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    _, source, snapshot, kernel, *_ = await case(
        monkeypatch, wait_ms=1 if failure == "active" else 30000
    )
    if failure == "nonzero":
        kernel.code = 1
    elif failure == "stderr":
        create = kernel.create

        def noisy(*args: Any, **kwargs: Any) -> NativeChild:
            child = cast(NativeChild, create(*args, **kwargs))
            kernel.outputs[child.stderr] = b"synthetic-private-marker"
            return child

        monkeypatch.setattr(kernel, "create", noisy)
    elif failure == "oversize":
        kernel.packets[0] = b"x" * (1024 * 1024 + 1)
    elif failure == "active":
        kernel.active = 1
    else:
        kernel.failure = failure
    with pytest.raises(ValueError, match="^security_descriptor_source_unverified$") as error:
        await source.observe(snapshot)
    assert "synthetic-private-marker" not in str(error.value)
    assert kernel.closed or not kernel.calls
    with pytest.raises(ValueError):
        await source.observe(snapshot)


@pytest.mark.parametrize("change", ["copy", "nonce", "field", "image", "image_nested", "source"])
async def test_capability_copy_mutation_foreign_source_denied(
    monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    _, source, snapshot, _, _, _, *_ = await case(monkeypatch)
    cap = await source.observe(snapshot)
    if change == "copy":
        cap = replace(cap)
    elif change == "nonce":
        object.__setattr__(cap.nonce, "int", 0)
    elif change == "field":
        object.__setattr__(cap, "primary_name", "foreign")
    elif change == "image":
        object.__setattr__(cap, "image", replace(cap.image))
    elif change == "image_nested":
        object.__setattr__(cap.image, "architecture", "foreign")
    else:
        source = (await case(monkeypatch))[1]
    with pytest.raises(ValueError):
        source.assert_issued(cap)


@pytest.mark.parametrize(
    "change",
    ["settings", "secret", "observer", "observation", "snapshot", "process", "native", "limit"],
)
async def test_bound_sources_revalidate_before_any_owned_helper(
    monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    _, source, snapshot, kernel, original, observed, *_ = await case(monkeypatch)
    if change == "settings":
        source.settings = source.settings.model_copy()
    elif change == "secret":
        from pydantic import SecretStr

        source.settings.secret_key = SecretStr("x" * 40)
    elif change == "observer":
        original.reader = object()
    elif change == "observation":
        object.__setattr__(observed.identity, "deployment_sha256", "f" * 64)
    elif change == "snapshot":
        snapshot = replace(snapshot, cluster_uuid="foreign")
    elif change == "process":
        source.process = WindowsControlProcess(Kernel(kernel.packets))
    elif change == "native":
        source.process._native = Kernel(kernel.packets)
    else:
        source.process._limit = 2 * 1024 * 1024
    with pytest.raises(ValueError):
        await source.observe(snapshot)
    assert not kernel.calls


async def test_final_identity_change_prevents_issuance(monkeypatch: pytest.MonkeyPatch) -> None:
    _, source, snapshot, kernel, original, *_ = await case(monkeypatch)
    observe = original.observe_original
    count = 0

    async def changed(snap: Any) -> Any:
        nonlocal count
        result = await observe(snap)
        count += 1
        return replace(result, ephemeral_id="foreign") if count == 2 else result

    monkeypatch.setattr(original, "observe_original", changed)
    with pytest.raises(ValueError):
        await source.observe(snapshot)
    assert len(kernel.calls) == 5


async def test_cancellation_poison_is_propagated(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    _, source, snapshot, kernel, original, *_ = await case(monkeypatch)

    async def cancelled(snap: Any) -> Any:
        raise asyncio.CancelledError()

    monkeypatch.setattr(original, "observe_original", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await source.observe(snapshot)
    with pytest.raises(ValueError):
        await source.observe(snapshot)
    assert not kernel.calls


async def test_capture_child_association_mutation_is_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, source, snapshot, *_ = await case(monkeypatch)
    cap = await source.observe(snapshot)
    child = source._captures[cap][0][1]
    object.__setattr__(child.job_id, "int", 0)
    with pytest.raises(ValueError):
        source.assert_issued(cap)


async def test_aggregate_limit_uses_actual_crlf_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    module, source, snapshot, kernel, *_ = await case(monkeypatch)
    normalized = b"x\n" * 300000
    monkeypatch.setattr(module, "_PINS", (hashlib.sha256(normalized).hexdigest(),) * 5)
    kernel.packets = [normalized.replace(b"\n", b"\r\n")] * 5
    with pytest.raises(ValueError):
        await source.observe(snapshot)
    assert len(kernel.calls) == 5
    assert not source._issued


async def test_midcapture_settings_loss_does_not_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    _, source, snapshot, kernel, *_ = await case(monkeypatch)
    close = kernel.close

    def lose_owner(handle: int) -> None:
        close(handle)
        source.settings.elasticsearch_url = "http://127.0.0.1:9201"

    monkeypatch.setattr(kernel, "close", lose_owner)
    with pytest.raises(ValueError):
        await source.observe(snapshot)
    assert len(kernel.calls) == 1
    assert len(kernel.closed) == 5
    assert not source._issued


async def test_capture_cancellation_closes_owned_child_and_consumes_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    _, source, snapshot, kernel, *_ = await case(monkeypatch)

    def interrupt(handle: int) -> int:
        raise asyncio.CancelledError()

    monkeypatch.setattr(kernel, "resume", interrupt)
    with pytest.raises(asyncio.CancelledError):
        await source.observe(snapshot)
    assert len(kernel.closed) == 5
    with pytest.raises(ValueError):
        await source.observe(snapshot)


@pytest.mark.parametrize("argument", ["settings", "original", "observation", "process"])
async def test_constructor_accepts_only_exact_actual_source_types(
    monkeypatch: pytest.MonkeyPatch, argument: str
) -> None:
    module, source, _, _, *_ = await case(monkeypatch)
    values = [source.settings, source.original, source.observation, source.process]
    values[["settings", "original", "observation", "process"].index(argument)] = object()
    with pytest.raises(ValueError, match="^security_descriptor_source_unverified$"):
        module.OriginalSecurityDescriptorSource(*values)


@pytest.mark.parametrize("stage", ["resume", "wait"])
async def test_primary_cancellation_survives_cleanup_failure(
    monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    import asyncio

    _, source, snapshot, kernel, *_ = await case(monkeypatch)
    kernel.failure = "close"
    cancellation = asyncio.CancelledError()

    def interrupt(*args: Any) -> Any:
        raise cancellation

    monkeypatch.setattr(source.process, stage, interrupt)
    with pytest.raises(asyncio.CancelledError) as caught:
        await source.observe(snapshot)
    assert caught.value is cancellation
    assert len(kernel.closed) == 5
    assert source.cleanup_unverified is True
    assert not source._issued
    assert source._attempted is True
    with pytest.raises(ValueError):
        await source.observe(snapshot)
