"""Fixed read-only Docker children; no cutover or phase authority is issued here.

The phase source must freshly validate SQL/material before and after every await.
Cancellation waits for actual same-thread close and never means verified cleanup.
"""

import asyncio
import base64
import json
import re
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Lock
from uuid import UUID

from ai_workshop.infrastructure.local.control_process_windows import (
    ChildToken,
    LocalProcessResult,
    WindowsControlProcess,
)
from ai_workshop.infrastructure.local.windows_private_state import (
    NativeWindowsPrivateState,
    ReadCapturePhase,
)
from ai_workshop.labs.rag.indexing.access_epoch_deployment import PROJECT_ROOT
from ai_workshop.labs.rag.indexing.alias_recovery_local_native import DOCKER_EXE, NETWORK

_OUTPUT_LIMIT = 2 * 1024 * 1024
_WAIT_MS = 10000
_ATTEMPTED: set[tuple[NativeWindowsPrivateState, int, int]] = set()
_ACTIVE: set[WindowsControlProcess] = set()
_REGISTRY_LOCK = Lock()


def _denied() -> ValueError:
    return ValueError("secured_read_process_denied")


class _StoppedRead(BaseException):
    pass


@dataclass(frozen=True, slots=True)
class SecuredDockerReadCatalog:
    """Validated input values, never an issued capability or caller command."""

    container_id: str
    image_id: str


def _argv(catalog: SecuredDockerReadCatalog, slot: int) -> tuple[str, ...]:
    if (
        type(catalog) is not SecuredDockerReadCatalog
        or type(catalog.container_id) is not str
        or re.fullmatch(r"[0-9a-f]{64}", catalog.container_id) is None
        or type(catalog.image_id) is not str
        or re.fullmatch(r"sha256:[0-9a-f]{64}", catalog.image_id) is None
        or type(slot) is not int
        or not 0 <= slot <= 4
    ):
        raise _denied()
    commands = (
        ("info", "--format", "{{json .}}"),
        ("container", "inspect", catalog.container_id),
        ("network", "inspect", NETWORK),
        ("image", "inspect", catalog.image_id),
        ("volume", "inspect", "ai-workshop_elasticsearch-data"),
    )
    return (DOCKER_EXE, "--host", "npipe:////./pipe/dockerDesktopLinuxEngine", *commands[slot])


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


async def _capture_docker_read(
    *,
    catalog: SecuredDockerReadCatalog,
    native: WindowsControlProcess,
    files: NativeWindowsPrivateState,
    nonce: UUID,
    slot: int,
    binding_json: str,
    environment: dict[str, str],
) -> LocalProcessResult:
    """One poisoned-on-attempt slot with a same-thread cleanup barrier.

    Native syscall completion is necessary: cancelling an await or reaching a
    Python deadline cannot prove a hanging child's cleanup. No retry is offered.
    """
    try:
        command = _argv(catalog, slot)
        if (
            type(native) is not WindowsControlProcess
            or type(files) is not NativeWindowsPrivateState
            or files.root != PROJECT_ROOT
            or files.private != PROJECT_ROOT / ".local-data/access-epoch/private"
            or native._limit != _OUTPUT_LIMIT
            or native._max_wait_ms != _WAIT_MS
            or native._children
            or native in _ACTIVE
            or type(nonce) is not UUID
            or nonce.int == 0
            or type(binding_json) is not str
            or not 0 < len(binding_json.encode()) <= 65536
            or type(environment) is not dict
        ):
            raise _denied()
        binding = json.loads(binding_json)
        if type(binding) is not dict or _canonical(binding).decode() != binding_json:
            raise _denied()
        allowed = {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH"}
        names: set[str] = set()
        for key, value in environment.items():
            if (
                type(key) is not str
                or key.upper() not in allowed
                or key.upper() in names
                or type(value) is not str
                or not value
                or "\0" in value
                or len(value.encode("utf-16-le")) > 65536
            ):
                raise _denied()
            names.add(key.upper())
        if "SYSTEMROOT" not in names:
            raise _denied()
        nonce_value = nonce.int
        capture_nonce = UUID(int=nonce_value)
        root_text = str(PROJECT_ROOT)
        fixed_root = Path(root_text)
        attempt = files, nonce_value, slot
        with _REGISTRY_LOCK:
            if attempt in _ATTEMPTED or native in _ACTIVE or native._children:
                raise _denied()
            _ATTEMPTED.add(attempt)
            _ACTIVE.add(native)
        env = dict(environment)
        pins = (
            id(native._native),
            id(files.kernel),
            id(files.advapi),
            id(files.crypt),
            str(files.root),
            str(files.private),
            files.owner,
            catalog.container_id,
            catalog.image_id,
        )
    except Exception:
        raise _denied() from None

    stop = Event()

    def check() -> None:
        if (
            pins
            != (
                id(native._native),
                id(files.kernel),
                id(files.advapi),
                id(files.crypt),
                str(files.root),
                str(files.private),
                files.owner,
                catalog.container_id,
                catalog.image_id,
            )
            or type(nonce) is not UUID
            or nonce.int != nonce_value
            or str(PROJECT_ROOT) != root_text
            or _canonical(binding).decode() != binding_json
            or _argv(catalog, slot) != command
            or native._limit != _OUTPUT_LIMIT
            or native._max_wait_ms != _WAIT_MS
            or environment != env
        ):
            raise _denied()

    def persist(phase: ReadCapturePhase, data: object) -> None:
        check()
        packet = _canonical(data)
        files.create_read_capture(capture_nonce, slot, phase, packet)
        check()
        if files.read_read_capture(capture_nonce, slot, phase) != packet:
            raise _denied()
        check()

    def child_packet(token: ChildToken) -> dict[str, object]:
        return {
            "pid": token.child.pid,
            "creation_time": token.child.creation_time,
            "job_id": str(token.child.job_id),
        }

    def worker() -> LocalProcessResult:
        token: ChildToken | None = None
        result: LocalProcessResult | None = None
        primary: BaseException | None = None
        cleanup_ok = False
        try:
            if stop.is_set():
                raise _StoppedRead()
            persist(
                "intent",
                {
                    "schema_version": 1,
                    "nonce": str(capture_nonce),
                    "slot": slot,
                    "binding": binding,
                    "command": command,
                    "started_at": datetime.now(UTC).isoformat(),
                },
            )
            if stop.is_set():
                raise _StoppedRead()
            check()
            token = native.create_suspended(command, dict(env), fixed_root)
            persist("child", child_packet(token))
            if stop.is_set():
                raise _StoppedRead()
            persist("resume_intent", child_packet(token))
            if stop.is_set():
                raise _StoppedRead()
            check()
            native.resume(token)
            check()
            result = native.wait(token, _WAIT_MS)
            check()
            if (
                type(result) is not LocalProcessResult
                or result.child is not token.child
                or type(result.exit_code) is not int
                or result.exit_code != 0
                or type(result.stdout) is not bytes
                or type(result.stderr) is not bytes
                or len(result.stdout) + len(result.stderr) > _OUTPUT_LIMIT
            ):
                raise _denied()
            persist(
                "terminal",
                {
                    "child": child_packet(token),
                    "exit_code": result.exit_code,
                    "completed_at": datetime.now(UTC).isoformat(),
                },
            )
        except BaseException as error:
            primary = error
        finally:
            if token is not None:
                try:
                    native.close(token)
                    cleanup_ok = True
                except BaseException as error:
                    if primary is None:
                        primary = error
                    else:
                        primary.add_note("secured_read_cleanup_unverified")
                try:
                    persist("cleanup", {"child": child_packet(token), "closed": cleanup_ok})
                except BaseException as error:
                    if primary is None:
                        primary = error
                    else:
                        primary.add_note("secured_read_capture_unverified")
        if primary is not None:
            if not isinstance(primary, Exception):
                raise primary
            raise _denied() from None
        if not cleanup_ok or result is None or token is None:
            raise _denied()
        if stop.is_set():
            raise _StoppedRead()
        persist(
            "capture",
            {
                "child": child_packet(token),
                "exit_code": result.exit_code,
                "stdout_b64": base64.b64encode(result.stdout).decode(),
                "stderr_b64": base64.b64encode(result.stderr).decode(),
            },
        )
        if stop.is_set():
            raise _StoppedRead()
        return result

    executor: ThreadPoolExecutor | None = None
    try:
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="secured-read")
        future = asyncio.get_running_loop().run_in_executor(executor, worker)
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError as primary:
            stop.set()
            while not future.done():
                try:
                    await asyncio.shield(future)
                except asyncio.CancelledError:
                    continue
                except BaseException:
                    break
            if future.done() and not future.cancelled():
                with suppress(BaseException):
                    future.result()
            raise primary
    except Exception:
        raise _denied() from None
    finally:
        # The worker barrier completed before this point; never close its child
        # on the event-loop thread or leave a cancelled executor task running.
        if executor is not None:
            executor.shutdown(wait=True)
        with _REGISTRY_LOCK:
            _ACTIVE.discard(native)
