"""Internal owned request workspace; this is NOT launch authorization or readiness.

The caller must supply authorization, current settings evidence, durable fingerprint
binding and concurrency control. A configuration digest proves integrity, not consent.
Path checks narrow replacement races; they do not create a race-free OS sandbox.
Only the schema is written. Retained workspaces require exact-path diagnosis.
"""

from __future__ import annotations

import json
import os
import re
import stat
import threading
from contextlib import suppress
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from .codex_authorization import CodexCallIntent, CodexCallStage, CodexExecutionPayload
from .codex_command import build_codex_command
from .codex_events import CodexEventLimits
from .codex_runner_registry import CodexRunnerRegistry
from .codex_stream import CodexStreamResult
from .codex_wire import CODEX_GROUNDED_WIRE_SCHEMA_V1
from .structured_output import CONTEXTUALIZATION_SCHEMA_V1
from .structured_output_v2 import GROUNDED_GENERATION_SCHEMA_V2
from .windows_process import ProcessRequest


class CodexWorkspaceStream(Protocol):
    def run(
        self, request: ProcessRequest, event_limits: CodexEventLimits,
        cancellation: threading.Event | None = None,
    ) -> CodexStreamResult: ...


@dataclass(frozen=True, slots=True)
class CodexWorkspaceResult:
    stream: CodexStreamResult | None = field(default=None, repr=False)
    failure: str | None = None
    workspace_id: str | None = None
    cleanup_verified: bool = True
    process_termination_verified: bool = False


class CodexWorkspaceExecutor:
    def __init__(
        self, *, registry: CodexRunnerRegistry, stream_runner: CodexWorkspaceStream,
    ) -> None:
        self._registry = registry
        self._stream_runner = stream_runner

    def run(
        self, *, intent: CodexCallIntent, payload: CodexExecutionPayload,
        expected_configuration_sha256: str, timeout_seconds: float,
        cancellation: threading.Event | None = None,
        max_output_tokens: int | None = None,
    ) -> CodexWorkspaceResult:
        owner: _OwnedDirectory | None = None
        invoked = False
        process_termination_verified = True  # Nothing has been launched yet.
        stream: CodexStreamResult | None = None
        failure: str | None = None
        try:
            if (type(expected_configuration_sha256) is not str
                    or re.fullmatch(r"[0-9a-f]{64}", expected_configuration_sha256) is None):
                raise ValueError("fingerprint invalid")
            if type(intent) is not CodexCallIntent or type(payload) is not CodexExecutionPayload:
                raise ValueError("input invalid")
            runner = self._registry.resolve(intent.runner_ref)
            if runner.configuration_sha256 != expected_configuration_sha256:
                raise ValueError("fingerprint mismatch")
            event_limits = runner.event_limits
            if max_output_tokens is not None:
                if (type(max_output_tokens) is not int
                        or not 1 <= max_output_tokens <= event_limits.max_output_tokens):
                    raise ValueError("output budget invalid")
                event_limits = replace(event_limits, max_output_tokens=max_output_tokens)
            directory = runner.request_root / ("request-" + uuid4().hex)
            plan = build_codex_command(
                runner=runner, intent=intent, payload=payload,
                request_directory=directory, timeout_seconds=timeout_seconds,
            )
            trusted_schemas = (
                (GROUNDED_GENERATION_SCHEMA_V2, CODEX_GROUNDED_WIRE_SCHEMA_V1)
                if intent.stage is CodexCallStage.GENERATE else (CONTEXTUALIZATION_SCHEMA_V1,)
            )
            trusted_bytes = tuple(
                json.dumps(schema, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"), allow_nan=False).encode("utf-8")
                for schema in trusted_schemas
            )
            if plan.output_schema not in trusted_bytes:
                raise ValueError("untrusted schema")
            if cancellation is not None and cancellation.is_set():
                return CodexWorkspaceResult(failure="codex_workspace_cancelled",
                                            process_termination_verified=True)
            owner = _OwnedDirectory(directory, plan.output_schema)
            owner.create()
            current = self._registry.resolve(intent.runner_ref)
            if current.configuration_sha256 != expected_configuration_sha256:
                raise ValueError("configuration changed")
            owner.verify_schema()
            if cancellation is not None and cancellation.is_set():
                failure = "codex_workspace_cancelled"
            else:
                invoked = True
                process_termination_verified = False
                stream = self._stream_runner.run(
                    plan.process_request, event_limits, cancellation,
                )
                if (type(stream) is not CodexStreamResult
                        or stream.cleanup_verified is not True
                        or type(stream.active_processes_after_cleanup) is not int
                        or stream.active_processes_after_cleanup != 0):
                    return _retained(owner)
                process_termination_verified = True
        except Exception:
            if invoked:
                return _retained(owner)
            failure = "codex_workspace_preparation_failed"
        except BaseException:
            # Control-flow exceptions propagate. A possibly live process must keep
            # its workspace; only known allocations made before invocation are safe.
            if not invoked and owner is not None:
                with suppress(BaseException):
                    owner.cleanup()
            raise
        if owner is not None:
            try:
                owner.cleanup()
            except Exception:
                return _retained(owner, process_termination_verified=process_termination_verified)
        return CodexWorkspaceResult(
            stream=stream, failure=failure,
            workspace_id=owner.directory.name if owner is not None and owner.created else None,
            process_termination_verified=process_termination_verified,
        )


def _retained(owner: _OwnedDirectory | None, *,
              process_termination_verified: bool = False) -> CodexWorkspaceResult:
    return CodexWorkspaceResult(
        failure="codex_workspace_cleanup_failed", cleanup_verified=False,
        workspace_id=owner.directory.name if owner is not None else None,
        process_termination_verified=process_termination_verified,
    )


def _identity(metadata: os.stat_result) -> tuple[int, ...]:
    if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
        raise ValueError("reparse")
    if not metadata.st_ino:
        raise ValueError("unknown identity")
    # Directory child operations legitimately change size/mtime/ctime.
    return (metadata.st_dev, metadata.st_ino, stat.S_IFMT(metadata.st_mode),
            getattr(metadata, "st_birthtime_ns", 0))


def _directory_identity(path: Path) -> tuple[int, ...]:
    metadata = path.lstat()
    identity = _identity(metadata)
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("not directory")
    return identity


class _OwnedDirectory:
    def __init__(self, directory: Path, schema: bytes) -> None:
        self.directory = directory
        self.schema_path = directory / "output-schema.json"
        self.schema = schema
        self.ancestors = tuple(
            (path, _directory_identity(path)) for path in reversed(directory.parents)
        )
        self.child_identity: tuple[int, ...] | None = None
        self.schema_identity: tuple[int, ...] | None = None
        self.created = False
        self.allocation_attempted = False

    def check_chain(self) -> None:
        for path, identity in self.ancestors:
            if _directory_identity(path) != identity:
                raise ValueError("ancestor changed")
        if (self.child_identity is not None
                and _directory_identity(self.directory) != self.child_identity):
            raise ValueError("child changed")

    def create(self) -> None:
        self.check_chain()
        self.allocation_attempted = True
        try:
            self.directory.mkdir(exist_ok=False)
        except FileExistsError:
            # Exclusive creation explicitly rejected a pre-existing child.
            self.allocation_attempted = False
            raise
        self.created = True
        self.child_identity = _directory_identity(self.directory)
        self.check_chain()
        with self.schema_path.open("xb") as target:
            self.schema_identity = _identity(os.fstat(target.fileno()))
            if target.write(self.schema) != len(self.schema):
                raise OSError("short write")
        self.verify_schema()

    def verify_schema(self) -> None:
        self.check_chain()
        with os.scandir(self.directory) as entries:
            for entry in entries:
                if entry.name != "output-schema.json":
                    raise ValueError("unknown entry")
        before = self.schema_path.lstat()
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or _identity(before) != self.schema_identity):
            raise ValueError("schema changed")
        with self.schema_path.open("rb") as source:
            if _identity(os.fstat(source.fileno())) != self.schema_identity:
                raise ValueError("schema changed")
            if source.read(len(self.schema) + 1) != self.schema:
                raise ValueError("schema content changed")
        after = self.schema_path.lstat()
        if (_identity(after) != self.schema_identity or after.st_nlink != 1
                or before.st_mtime_ns != after.st_mtime_ns
                or before.st_size != after.st_size):
            raise ValueError("schema changed")
        self.check_chain()

    def cleanup(self) -> None:
        if not self.created:
            if self.allocation_attempted:
                self.check_chain()
                try:
                    self.directory.lstat()
                except FileNotFoundError:
                    return
                raise ValueError("allocation ownership unknown")
            return
        if self.child_identity is None:
            raise ValueError("ownership unknown")
        self.check_chain()
        if self.schema_identity is not None:
            self.verify_schema()
        with os.scandir(self.directory) as entries:
            for entry in entries:
                if self.schema_identity is None or entry.name != "output-schema.json":
                    raise ValueError("unknown entry")
        if self.schema_identity is not None:
            self.verify_schema()
            self.schema_path.unlink()
        self.check_chain()
        self.directory.rmdir()
        for path, identity in self.ancestors:
            if _directory_identity(path) != identity:
                raise ValueError("ancestor changed")
        try:
            self.directory.lstat()
        except FileNotFoundError:
            return
        raise ValueError("child still present")
