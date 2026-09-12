from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from ai_workshop.labs.rag.generation.codex_authorization import (
    CodexCallIntent,
    CodexCallOperation,
    CodexCallStage,
    CodexExecutionPayload,
)
from ai_workshop.labs.rag.generation.codex_events import (
    CodexEventLimits,
    CodexEventResult,
    CodexTokenUsage,
)
from ai_workshop.labs.rag.generation.codex_runner_registry import (
    CodexRunnerRegistry,
    CodexRunnerSettings,
)
from ai_workshop.labs.rag.generation.codex_stream import CodexStreamResult
from ai_workshop.labs.rag.generation.structured_output import CONTEXTUALIZATION_SCHEMA_V1
from ai_workshop.labs.rag.generation.structured_output_v2 import GROUNDED_GENERATION_SCHEMA_V2
from ai_workshop.labs.rag.generation.windows_process import ProcessFailure, ProcessRequest


def _payload(stage: CodexCallStage = CodexCallStage.GENERATE) -> CodexExecutionPayload:
    schema = (GROUNDED_GENERATION_SCHEMA_V2 if stage == CodexCallStage.GENERATE
              else CONTEXTUALIZATION_SCHEMA_V1)
    return CodexExecutionPayload(
        b'{ "question" : "synthetic STDIN canary" }\n',
        b"synthetic DEVELOPER canary",
        json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                   allow_nan=False).encode("utf-8"),
    )


def _intent(payload: CodexExecutionPayload,
            stage: CodexCallStage = CodexCallStage.GENERATE) -> CodexCallIntent:
    return CodexCallIntent(
        actor_id=UUID(int=1), request_id=UUID(int=2), approval_id=UUID(int=3),
        operation=CodexCallOperation.SEARCH, stage=stage,
        configuration_version_id=UUID(int=4), deployment_version_id=UUID(int=5),
        generation_profile_id=UUID(int=6), runner_ref="codex-cli-synthetic",
        provider_model_id="synthetic-model",
        runner_configuration_sha256="c" * 64,
        developer_instructions_sha256=hashlib.sha256(payload.developer_instructions).hexdigest(),
        output_schema_sha256=hashlib.sha256(payload.output_schema).hexdigest(),
        workspace_ids=(), workspace_policy_bindings=(), installation_policy_version_id=UUID(int=7),
        generation_disclosure_version="synthetic-v1", evidence_revisions=(),
    )


def _registry(tmp_path: Path) -> CodexRunnerRegistry:
    executable = tmp_path / "installation" / "synthetic.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"synthetic non-executable fixture")
    root = tmp_path / "requests"
    root.mkdir()
    (root / "sentinel.txt").write_bytes(b"synthetic sibling")
    protected = tmp_path / "protected-repo"
    protected.mkdir()
    return CodexRunnerRegistry(
        {"codex-cli-synthetic": CodexRunnerSettings(
            executable=executable, expected_cli_version="0.153.4",
            executable_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
            request_root=root,
        )}, environment="test", protected_roots=(protected,),
    )


class FakeStream:
    def __init__(self, callback: Callable[[ProcessRequest], CodexStreamResult]) -> None:
        self.callback = callback
        self.calls: list[ProcessRequest] = []
        self.cancellations: list[threading.Event | None] = []
        self.limits: list[CodexEventLimits] = []

    def run(self, request: ProcessRequest, event_limits: CodexEventLimits,
            cancellation: threading.Event | None = None) -> CodexStreamResult:
        self.calls.append(request)
        self.cancellations.append(cancellation)
        self.limits.append(event_limits)
        return self.callback(request)


def test_success_owns_one_child_and_preserves_exact_payload(tmp_path: Path) -> None:
    assert importlib.util.find_spec(
        "ai_workshop.labs.rag.generation.codex_workspace"
    ) is not None, "request workspace lifecycle is not implemented"
    from ai_workshop.labs.rag.generation.codex_workspace import CodexWorkspaceExecutor

    registry = _registry(tmp_path)
    resolved = registry.resolve("codex-cli-synthetic")
    payload = _payload()
    original = (payload.stdin, payload.developer_instructions, payload.output_schema)
    success = CodexStreamResult(
        events=CodexEventResult(
            final_text='{"answer":"synthetic EVENT canary"}',
            thread_id="synthetic-thread", usage=CodexTokenUsage(3, 0, 2, None),
        ),
        active_processes_after_cleanup=0,
    )

    def inspect(request: ProcessRequest) -> CodexStreamResult:
        assert request.cwd.parent == resolved.request_root
        assert re.fullmatch(r"request-[0-9a-f]{32}", request.cwd.name)
        assert [path.name for path in request.cwd.iterdir()] == ["output-schema.json"]
        assert (request.cwd / "output-schema.json").read_bytes() == payload.output_schema
        assert request.stdin is payload.stdin
        assert request.limits.timeout_seconds == 10.0
        return success

    stream = FakeStream(inspect)
    result = CodexWorkspaceExecutor(registry=registry, stream_runner=stream).run(
        intent=_intent(payload), payload=payload,
        expected_configuration_sha256=resolved.configuration_sha256, timeout_seconds=10.0,
    )
    assert result.failure is None
    assert result.cleanup_verified
    assert result.stream is success
    assert result.process_termination_verified is True
    assert len(stream.calls) == 1
    assert stream.limits == [resolved.event_limits]
    assert not stream.calls[0].cwd.exists()
    assert result.workspace_id == stream.calls[0].cwd.name
    assert (resolved.request_root / "sentinel.txt").read_bytes() == b"synthetic sibling"
    assert original == (payload.stdin, payload.developer_instructions, payload.output_schema)
    assert str(tmp_path) not in repr(result)
    assert "canary" not in repr(result)


@pytest.mark.parametrize("stage,accepted", [
    (CodexCallStage.GENERATE, True), (CodexCallStage.CONTEXTUALIZE, False),
])
def test_wire_schema_allowed_only_for_generation(
    tmp_path: Path, stage: CodexCallStage, accepted: bool,
) -> None:
    from ai_workshop.labs.rag.generation.codex_wire import CODEX_GROUNDED_WIRE_SCHEMA_V1

    registry = _registry(tmp_path)
    wire = json.dumps(CODEX_GROUNDED_WIRE_SCHEMA_V1, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")
    payload = replace(_payload(), output_schema=wire)

    def inspect(request: ProcessRequest) -> CodexStreamResult:
        assert (request.cwd / "output-schema.json").read_bytes() == wire
        return CodexStreamResult(active_processes_after_cleanup=0)

    stream = FakeStream(inspect)
    result = _run(registry, stream, payload=payload, intent=_intent(payload, stage))
    assert result.cleanup_verified
    assert (result.failure is None) is accepted
    assert len(stream.calls) == int(accepted)
    assert [p.name for p in (tmp_path / "requests").iterdir()] == ["sentinel.txt"]


def _run(registry: CodexRunnerRegistry, stream: FakeStream, **changes: Any) -> Any:
    from ai_workshop.labs.rag.generation.codex_workspace import CodexWorkspaceExecutor

    payload = changes.pop("payload", _payload())
    intent = changes.pop("intent", _intent(payload))
    fingerprint = changes.pop("expected_configuration_sha256", None)
    if fingerprint is None:
        fingerprint = registry.resolve("codex-cli-synthetic").configuration_sha256
    return CodexWorkspaceExecutor(registry=registry, stream_runner=stream).run(
        intent=intent, payload=payload, expected_configuration_sha256=fingerprint,
        **{"timeout_seconds": 10.0, **changes},
    )


@pytest.mark.parametrize("limit", [1, 100, 16384, None])
def test_output_limit_only_narrows_without_registry_mutation(
    tmp_path: Path, limit: int | None,
) -> None:
    registry = _registry(tmp_path)
    before = registry.resolve("codex-cli-synthetic")
    stream = FakeStream(lambda _: CodexStreamResult(active_processes_after_cleanup=0))
    result = _run(registry, stream, max_output_tokens=limit)
    assert result.failure is None
    assert stream.limits[0].max_output_tokens == (16384 if limit is None else limit)
    assert registry.resolve("codex-cli-synthetic").event_limits == before.event_limits
    assert (
        registry.resolve("codex-cli-synthetic").configuration_sha256 == before.configuration_sha256
    )


@pytest.mark.parametrize("limit", [True, False, 0, -1, 16385, 1.0, "1"])
def test_invalid_output_limit_never_launches(tmp_path: Path, limit: object) -> None:
    registry = _registry(tmp_path)
    stream = FakeStream(lambda _: CodexStreamResult(active_processes_after_cleanup=0))
    result = _run(registry, stream, max_output_tokens=limit)
    assert result.failure == "codex_workspace_preparation_failed"
    assert result.process_termination_verified is True
    assert not stream.calls
    assert [p.name for p in (tmp_path / "requests").iterdir()] == ["sentinel.txt"]


def test_unknown_legacy_result_never_claims_process_termination() -> None:
    from ai_workshop.labs.rag.generation.codex_workspace import CodexWorkspaceResult

    assert CodexWorkspaceResult().process_termination_verified is False


@pytest.mark.parametrize("change", [
    {"expected_configuration_sha256": "a" * 64},
    {"expected_configuration_sha256": "A" * 64},
    {"expected_configuration_sha256": "private input"},
    {"timeout_seconds": 0},
    {"timeout_seconds": True},
    {"timeout_seconds": float("nan")},
    {"intent": replace(_intent(_payload()), provider_model_id="private;bad-model")},
    {"payload": replace(_payload(), output_schema=b'{"type":"object"}')},
    {"payload": _payload(CodexCallStage.CONTEXTUALIZE),
     "intent": _intent(_payload(CodexCallStage.CONTEXTUALIZE))},
])
def test_invalid_preparation_has_no_writes_or_callback(tmp_path: Path,
                                                      change: dict[str, Any]) -> None:
    registry = _registry(tmp_path)
    stream = FakeStream(lambda _: CodexStreamResult(active_processes_after_cleanup=0))
    result = _run(registry, stream, **change)
    assert result.failure is not None
    assert result.cleanup_verified
    assert result.process_termination_verified is True
    assert result.stream is None
    assert result.workspace_id is None
    assert not stream.calls
    assert "private" not in repr(result)
    assert [p.name for p in (tmp_path / "requests").iterdir()] == ["sentinel.txt"]


def test_contextualization_uses_its_own_trusted_schema(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    payload = _payload(CodexCallStage.CONTEXTUALIZE)

    def inspect(request: ProcessRequest) -> CodexStreamResult:
        assert (request.cwd / "output-schema.json").read_bytes() == payload.output_schema
        return CodexStreamResult(active_processes_after_cleanup=0)

    stream = FakeStream(inspect)
    result = _run(registry, stream, payload=payload,
                  intent=_intent(payload, CodexCallStage.CONTEXTUALIZE))
    assert result.failure is None
    assert result.cleanup_verified
    assert len(stream.calls) == 1


def test_cooperative_midcall_cancellation_passes_original_event(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    cancellation = threading.Event()

    def cancel(_: ProcessRequest) -> CodexStreamResult:
        cancellation.set()
        return CodexStreamResult(process_failure=ProcessFailure.CANCELLED,
                                 active_processes_after_cleanup=0)

    stream = FakeStream(cancel)
    result = _run(registry, stream, cancellation=cancellation)
    assert stream.cancellations == [cancellation]
    assert result.cleanup_verified
    assert result.stream.process_failure is ProcessFailure.CANCELLED
    assert not stream.calls[0].cwd.exists()


def test_terminated_event_failure_is_not_released_as_events(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    failed = CodexStreamResult(event_failure="codex_event_invalid_json",
                              active_processes_after_cleanup=0)
    stream = FakeStream(lambda _: failed)
    result = _run(registry, stream)
    assert result.stream is failed
    assert result.stream.events is None
    assert result.cleanup_verified
    assert result.process_termination_verified is True
    assert not stream.calls[0].cwd.exists()


def test_concurrent_calls_have_independent_owned_children(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    barrier = threading.Barrier(2)
    second_inside = threading.Event()
    first_finished = threading.Event()
    paths: list[Path] = []
    lock = threading.Lock()

    def inspect(request: ProcessRequest) -> CodexStreamResult:
        with lock:
            index = len(paths)
            paths.append(request.cwd)
        barrier.wait(timeout=5)
        if index == 0:
            assert second_inside.wait(timeout=5)
        else:
            second_inside.set()
            assert first_finished.wait(timeout=5)
            assert not paths[0].exists()
            assert (request.cwd / "output-schema.json").read_bytes() == _payload().output_schema
        return CodexStreamResult(active_processes_after_cleanup=0)

    def execute() -> Any:
        result = _run(registry, FakeStream(inspect))
        first_finished.set()
        return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(execute) for _ in range(2)]
        results = [future.result(timeout=10) for future in futures]
    assert len(set(paths)) == 2
    assert all(result.failure is None and result.cleanup_verified for result in results)
    assert all(not path.exists() for path in paths)
    assert (tmp_path / "requests" / "sentinel.txt").read_bytes() == b"synthetic sibling"


@pytest.mark.parametrize("operation", ["unlink", "rmdir"])
def test_simulated_delete_error_discards_success_and_keeps_outside_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str,
) -> None:
    registry = _registry(tmp_path)
    original = getattr(Path, operation)

    def fail(path: Path, *args: Any, **kwargs: Any) -> None:
        if path.name == "output-schema.json" or path.name.startswith("request-"):
            raise OSError("synthetic private delete error")
        original(path, *args, **kwargs)

    monkeypatch.setattr(Path, operation, fail)
    stream = FakeStream(lambda _: CodexStreamResult(active_processes_after_cleanup=0))
    result = _run(registry, stream)
    assert result.failure == "codex_workspace_cleanup_failed"
    assert not result.cleanup_verified
    assert result.stream is None
    assert stream.calls[0].cwd.exists()
    assert (tmp_path / "requests" / "sentinel.txt").read_bytes() == b"synthetic sibling"


def test_simulated_reparse_flag_retains_workspace_without_following_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _registry(tmp_path)
    original_lstat = Path.lstat

    def inspect(request: ProcessRequest) -> CodexStreamResult:
        def reparse(path: Path, *args: Any, **kwargs: Any) -> Any:
            metadata = original_lstat(path, *args, **kwargs)
            if path == request.cwd:
                return SimpleNamespace(st_mode=metadata.st_mode, st_file_attributes=0x400)
            return metadata

        monkeypatch.setattr(Path, "lstat", reparse)
        return CodexStreamResult(active_processes_after_cleanup=0)

    stream = FakeStream(inspect)
    result = _run(registry, stream)
    assert result.failure == "codex_workspace_cleanup_failed"
    assert result.stream is None
    assert not result.cleanup_verified
    assert (stream.calls[0].cwd / "output-schema.json").read_bytes() == _payload().output_schema


def test_collision_never_reuses_or_removes_existing_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_workshop.labs.rag.generation import codex_workspace

    registry = _registry(tmp_path)
    name = "request-" + "a" * 32
    collision = tmp_path / "requests" / name
    collision.mkdir()
    (collision / "unknown.txt").write_bytes(b"synthetic collision sentinel")
    monkeypatch.setattr(codex_workspace, "uuid4", lambda: UUID(hex="a" * 32))
    stream = FakeStream(lambda _: CodexStreamResult(active_processes_after_cleanup=0))
    result = _run(registry, stream)
    assert result.failure == "codex_workspace_preparation_failed"
    assert result.cleanup_verified
    assert result.workspace_id is None
    assert not stream.calls
    assert (collision / "unknown.txt").read_bytes() == b"synthetic collision sentinel"


def test_partial_write_is_retained_without_exposing_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _registry(tmp_path)
    original_open = Path.open

    class ShortWriter:
        def __init__(self, target: Any) -> None:
            self.target = target

        def __enter__(self) -> Any:
            return self

        def __exit__(self, *args: Any) -> None:
            self.target.close()

        def fileno(self) -> int:
            return self.target.fileno()

        def write(self, data: bytes) -> int:
            return self.target.write(data[:7])

    def short_open(path: Path, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        target = original_open(path, mode, *args, **kwargs)
        return ShortWriter(target) if mode == "xb" else target

    monkeypatch.setattr(Path, "open", short_open)
    stream = FakeStream(lambda _: CodexStreamResult(active_processes_after_cleanup=0))
    result = _run(registry, stream)
    assert result.failure == "codex_workspace_cleanup_failed"
    assert not result.cleanup_verified
    assert not stream.calls
    schema = tmp_path / "requests" / result.workspace_id / "output-schema.json"
    assert schema.read_bytes() == _payload().output_schema[:7]


def test_executable_change_during_preparation_prevents_callback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _registry(tmp_path)
    original_open = Path.open

    def change_executable(path: Path, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if mode == "xb":
            (tmp_path / "installation" / "synthetic.exe").write_bytes(b"changed synthetic bytes")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", change_executable)
    stream = FakeStream(lambda _: CodexStreamResult(active_processes_after_cleanup=0))
    result = _run(registry, stream)
    assert result.failure == "codex_workspace_preparation_failed"
    assert result.cleanup_verified
    assert not stream.calls
    assert [p.name for p in (tmp_path / "requests").iterdir()] == ["sentinel.txt"]


def test_no_ambient_cwd_environment_or_protected_repo_changes(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    current_directory = Path.cwd()
    environment = dict(os.environ)
    stream = FakeStream(lambda _: CodexStreamResult(active_processes_after_cleanup=0))
    result = _run(registry, stream)
    assert result.failure is None
    assert Path.cwd() == current_directory
    assert dict(os.environ) == environment
    assert list((tmp_path / "protected-repo").iterdir()) == []


def test_simulated_mkdir_error_after_creation_reports_uncertain_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _registry(tmp_path)
    original_mkdir = Path.mkdir

    def create_then_fail(path: Path, *args: Any, **kwargs: Any) -> None:
        original_mkdir(path, *args, **kwargs)
        if path.name.startswith("request-"):
            raise OSError("synthetic post-create failure")

    monkeypatch.setattr(Path, "mkdir", create_then_fail)
    stream = FakeStream(lambda _: CodexStreamResult(active_processes_after_cleanup=0))
    result = _run(registry, stream)
    assert result.failure == "codex_workspace_cleanup_failed"
    assert not result.cleanup_verified
    assert not stream.calls
    assert (tmp_path / "requests" / result.workspace_id).is_dir()


def test_unexpected_file_before_invocation_prevents_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _registry(tmp_path)
    original_open = Path.open

    def add_unknown(path: Path, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if mode == "xb":
            (path.parent / "unknown.txt").write_bytes(b"synthetic unknown prelaunch")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", add_unknown)
    stream = FakeStream(lambda _: CodexStreamResult(active_processes_after_cleanup=0))
    result = _run(registry, stream)
    assert result.failure == "codex_workspace_cleanup_failed"
    assert not result.cleanup_verified
    assert not stream.calls
    assert (tmp_path / "requests" / result.workspace_id / "unknown.txt").read_bytes() == (
        b"synthetic unknown prelaunch"
    )


def test_control_exception_before_invocation_cleans_known_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _registry(tmp_path)
    initial = registry.resolve("codex-cli-synthetic")
    original = registry.resolve
    calls = 0

    def interrupt_second_resolve(reference: str) -> Any:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt()
        return original(reference)

    monkeypatch.setattr(registry, "resolve", interrupt_second_resolve)
    stream = FakeStream(lambda _: CodexStreamResult(active_processes_after_cleanup=0))
    with pytest.raises(KeyboardInterrupt):
        _run(registry, stream, expected_configuration_sha256=initial.configuration_sha256)
    assert not stream.calls
    assert [p.name for p in initial.request_root.iterdir()] == ["sentinel.txt"]


def test_registry_rechecked_before_callback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _registry(tmp_path)
    initial = registry.resolve("codex-cli-synthetic")
    original_resolve = registry.resolve
    calls = 0

    def resolve(reference: str) -> Any:
        nonlocal calls
        calls += 1
        resolved = original_resolve(reference)
        return replace(resolved, configuration_sha256="c" * 64) if calls == 2 else resolved

    monkeypatch.setattr(registry, "resolve", resolve)
    stream = FakeStream(lambda _: CodexStreamResult(active_processes_after_cleanup=0))
    result = _run(registry, stream, expected_configuration_sha256=initial.configuration_sha256)
    assert result.failure is not None
    assert result.cleanup_verified
    assert not stream.calls
    assert [p.name for p in initial.request_root.iterdir()] == ["sentinel.txt"]


@pytest.mark.parametrize("evidence", [
    CodexStreamResult(cleanup_verified=False, active_processes_after_cleanup=0),
    CodexStreamResult(active_processes_after_cleanup=None),
    CodexStreamResult(active_processes_after_cleanup=False),
    CodexStreamResult(active_processes_after_cleanup=1),
    CodexStreamResult(active_processes_after_cleanup=0.0),  # type: ignore[arg-type]
    CodexStreamResult(cleanup_verified=1, active_processes_after_cleanup=0),  # type: ignore[arg-type]
    object(),
])
def test_unknown_termination_retains_schema_and_discards_stream(tmp_path: Path,
                                                              evidence: Any) -> None:
    registry = _registry(tmp_path)
    stream = FakeStream(lambda _: evidence)
    result = _run(registry, stream)
    assert result.failure == "codex_workspace_cleanup_failed"
    assert not result.cleanup_verified
    assert result.process_termination_verified is False
    assert result.stream is None
    assert (stream.calls[0].cwd / "output-schema.json").read_bytes() == _payload().output_schema


def test_stream_exception_is_safe_and_retained(tmp_path: Path) -> None:
    registry = _registry(tmp_path)

    def fail(_: ProcessRequest) -> CodexStreamResult:
        raise RuntimeError("private raw event and path canary")

    stream = FakeStream(fail)
    result = _run(registry, stream)
    assert result.failure == "codex_workspace_cleanup_failed"
    assert result.stream is None
    assert not result.cleanup_verified
    assert result.process_termination_verified is False
    assert stream.calls[0].cwd.exists()
    assert "canary" not in repr(result)


@pytest.mark.parametrize("mutation", ["unknown", "schema", "missing", "replacement"])
def test_cleanup_refuses_changed_owned_files(tmp_path: Path, mutation: str) -> None:
    registry = _registry(tmp_path)

    def mutate(request: ProcessRequest) -> CodexStreamResult:
        path = request.cwd / "output-schema.json"
        if mutation == "unknown":
            (request.cwd / "unknown.txt").write_bytes(b"unknown synthetic content")
        elif mutation == "schema":
            path.write_bytes(b"changed synthetic schema")
        elif mutation == "missing":
            path.unlink()
        else:
            request.cwd.rename(request.cwd.with_name("retained-original"))
            request.cwd.mkdir()
            path.write_bytes(_payload().output_schema)
        return CodexStreamResult(active_processes_after_cleanup=0)

    stream = FakeStream(mutate)
    result = _run(registry, stream)
    assert result.failure == "codex_workspace_cleanup_failed"
    assert not result.cleanup_verified
    assert result.process_termination_verified is True
    assert result.stream is None
    assert stream.calls[0].cwd.exists()
    assert (tmp_path / "requests" / "sentinel.txt").read_bytes() == b"synthetic sibling"


@pytest.mark.parametrize("failure", [ProcessFailure.NONZERO_EXIT, ProcessFailure.TIMEOUT,
                                     ProcessFailure.CANCELLED, ProcessFailure.OUTPUT_REJECTED])
def test_terminated_failure_cleans_and_preserves_failure_contract(tmp_path: Path,
                                                                failure: ProcessFailure) -> None:
    registry = _registry(tmp_path)
    failed = CodexStreamResult(process_failure=failure, active_processes_after_cleanup=0)
    stream = FakeStream(lambda _: failed)
    result = _run(registry, stream)
    assert result.cleanup_verified
    assert result.process_termination_verified is True
    assert result.failure is None
    assert result.stream is failed
    assert not stream.calls[0].cwd.exists()


def test_precancelled_request_does_not_invoke_stream(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    cancellation = threading.Event()
    cancellation.set()
    stream = FakeStream(lambda _: CodexStreamResult(active_processes_after_cleanup=0))
    result = _run(registry, stream, cancellation=cancellation)
    assert result.failure == "codex_workspace_cancelled"
    assert result.stream is None
    assert result.cleanup_verified
    assert result.process_termination_verified is True
    assert not stream.calls
    assert [p.name for p in (tmp_path / "requests").iterdir()] == ["sentinel.txt"]


@pytest.mark.parametrize("control", [KeyboardInterrupt, SystemExit])
def test_control_exception_after_invocation_retains_workspace(tmp_path: Path,
                                                              control: type[BaseException]) -> None:
    registry = _registry(tmp_path)

    def interrupt(_: ProcessRequest) -> CodexStreamResult:
        raise control()

    stream = FakeStream(interrupt)
    with pytest.raises(control):
        _run(registry, stream)
    assert (stream.calls[0].cwd / "output-schema.json").exists()


def test_schema_open_error_removes_only_empty_owned_child(tmp_path: Path,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    registry = _registry(tmp_path)
    original_open = Path.open

    def fail_open(path: Path, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if mode == "xb":
            raise OSError("synthetic private write error")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_open)
    stream = FakeStream(lambda _: CodexStreamResult(active_processes_after_cleanup=0))
    result = _run(registry, stream)
    assert result.failure == "codex_workspace_preparation_failed"
    assert result.cleanup_verified
    assert result.stream is None
    assert not stream.calls
    assert [p.name for p in (tmp_path / "requests").iterdir()] == ["sentinel.txt"]
