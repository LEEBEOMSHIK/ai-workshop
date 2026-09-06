from __future__ import annotations

import argparse
import asyncio
import ctypes
import errno
import json
import os
import signal
import stat
import subprocess
import tempfile
import uuid
from collections.abc import Callable, Sequence
from contextlib import suppress
from ctypes import wintypes
from dataclasses import asdict, dataclass
from pathlib import Path
from time import monotonic, sleep
from typing import BinaryIO, Never, Protocol, cast

from ai_workshop.labs.rag.generation.codex_app_server_gate import (
    ALLOWED_CODEX_APP_SERVER_VERSIONS,
    IsolationGateReport,
    IsolationObservation,
    attest_isolation,
)
from ai_workshop.labs.rag.generation.codex_app_server_probe import CodexAppServerProbe

_VERSION_TIMEOUT_SECONDS = 2.0
_VERSION_OUTPUT_LIMIT_BYTES = 1024
_PROBE_TIMEOUT_SECONDS = 5.0
_REPARSE_POINT = 0x0400
_FILE_READ_ATTRIBUTES = 0x0080
_DELETE = 0x00010000
_FILE_SHARE_READ = 0x0001
_FILE_SHARE_WRITE = 0x0002
_OPEN_EXISTING = 3
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_MAX_HANDLE_VALUE = _INVALID_HANDLE_VALUE or 0
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_FILE_DISPOSITION_INFO = 4


class _ByHandleFileInformation(ctypes.Structure):
    _fields_ = [
        ("dwFileAttributes", wintypes.DWORD),
        ("ftCreationTime_dwLowDateTime", wintypes.DWORD),
        ("ftCreationTime_dwHighDateTime", wintypes.DWORD),
        ("ftLastAccessTime_dwLowDateTime", wintypes.DWORD),
        ("ftLastAccessTime_dwHighDateTime", wintypes.DWORD),
        ("ftLastWriteTime_dwLowDateTime", wintypes.DWORD),
        ("ftLastWriteTime_dwHighDateTime", wintypes.DWORD),
        ("dwVolumeSerialNumber", wintypes.DWORD),
        ("nFileSizeHigh", wintypes.DWORD),
        ("nFileSizeLow", wintypes.DWORD),
        ("nNumberOfLinks", wintypes.DWORD),
        ("nFileIndexHigh", wintypes.DWORD),
        ("nFileIndexLow", wintypes.DWORD),
    ]


class _JobObjectBasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class _JobObjectExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JobObjectBasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _FileDispositionInformation(ctypes.Structure):
    _fields_ = [("DeleteFile", wintypes.BOOL)]


class _InvalidInvocation(Exception):
    pass


class _Probe(Protocol):
    async def probe(self) -> IsolationObservation: ...


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise _InvalidInvocation from None


@dataclass(slots=True)
class _PinnedDirectory:
    path: Path
    device: int
    inode: int
    windows_handle: int | None
    windows_identity: tuple[int, int] | None = None
    posix_fd: int | None = None

    def verify(self, boundary: Path) -> None:
        _reject_reparse_traversal(self.path)
        if self.path.resolve(strict=True) != self.path:
            raise _InvalidInvocation
        if not _is_within(self.path, boundary) and not _is_within(boundary, self.path):
            raise _InvalidInvocation
        details = self.path.stat(follow_symlinks=False)
        if details.st_dev != self.device or details.st_ino != self.inode:
            raise _InvalidInvocation
        if self.windows_handle is not None and self.windows_identity != _windows_identity(
            self.windows_handle
        ):
            raise _InvalidInvocation
        if self.posix_fd is not None:
            descriptor_details = os.fstat(self.posix_fd)
            if (
                descriptor_details.st_dev != self.device
                or descriptor_details.st_ino != self.inode
            ):
                raise _InvalidInvocation

    def close(self) -> None:
        if self.windows_handle is not None:
            _close_windows_handle(self.windows_handle)
            self.windows_handle = None
        if self.posix_fd is not None:
            os.close(self.posix_fd)
            self.posix_fd = None

    def stable_reference(self) -> Path:
        if self.posix_fd is not None:
            reference = Path(f"/proc/{os.getpid()}/fd/{self.posix_fd}")
            if not reference.exists():
                raise _InvalidInvocation
            return reference
        return self.path


def main(
    argv: Sequence[str] | None = None,
    *,
    repository_root: Path | None = None,
    probe_factory: Callable[..., _Probe] = CodexAppServerProbe,
    version_reader: Callable[[tuple[str, ...]], str] | None = None,
) -> int:
    """Run the no-content isolation gate without exposing local details."""
    run_directory: Path | None = None
    pinned_directories: list[_PinnedDirectory] = []
    cleanup_failed = False
    try:
        arguments = _parse_arguments(argv)
        root = _resolve_repository_root(repository_root)
        boundary = _prepare_boundary(root)
        codex_home = _validate_target(Path(arguments.codex_home), boundary, "home")
        report_directory = _validate_target(
            Path(arguments.report_dir), boundary, "report"
        )
        run_parent = boundary / "gate-runs"
        _reject_overlapping_roles(codex_home, report_directory, run_parent)
        _prepare_home_directory(codex_home)
        _prepare_report_directory(report_directory)

        run_directory = _create_run_directory(boundary)
        pinned_directories = _pin_directories(
            root,
            boundary,
            codex_home,
            report_directory,
            run_parent,
            run_directory,
            delete_access_path=run_directory,
        )

        read_version = version_reader or _read_cli_version
        cli_version = read_version((arguments.codex_command, "--version"))
        if cli_version not in ALLOWED_CODEX_APP_SERVER_VERSIONS:
            raise _InvalidInvocation

        _verify_pinned_directories(pinned_directories, boundary)
        probe_home = _stable_reference_for(codex_home, pinned_directories)
        probe_cwd = _stable_reference_for(run_directory, pinned_directories)
        try:
            probe = probe_factory(
                command=(
                    arguments.codex_command,
                    "app-server",
                    "--stdio",
                    "--strict-config",
                ),
                codex_home=probe_home,
                empty_cwd=probe_cwd,
                timeout_seconds=_PROBE_TIMEOUT_SECONDS,
                cli_version=cli_version,
            )
            observation = asyncio.run(probe.probe())
            report = attest_isolation(observation)
        except (asyncio.CancelledError, Exception):
            report = attest_isolation(_failed_observation(cli_version))
        _verify_pinned_directories(pinned_directories, boundary)
        _recheck_empty_report_directory(
            report_directory,
            _pinned_directory_for(report_directory, pinned_directories),
        )
        _write_report(
            report_directory,
            report,
            _pinned_directory_for(report_directory, pinned_directories),
        )
        _verify_pinned_directories(pinned_directories, boundary)
    except _InvalidInvocation:
        _emit_invalid_invocation()
        return 2
    except (TimeoutError, OSError, RuntimeError, ValueError):
        _emit_invalid_invocation()
        return 2
    finally:
        if run_directory is not None:
            run_pin: _PinnedDirectory | None = None
            try:
                run_pin = _pinned_directory_for(run_directory, pinned_directories)
                run_pin.verify(boundary)
                _remove_empty_run_directory(
                    run_directory,
                    run_pin,
                    _pinned_directory_for(run_directory.parent, pinned_directories),
                )
            except (OSError, _InvalidInvocation):
                cleanup_failed = True
            finally:
                if run_pin is not None:
                    try:
                        run_pin.close()
                    except (OSError, _InvalidInvocation):
                        cleanup_failed = True
        for pinned_directory in reversed(pinned_directories):
            if run_directory is not None and pinned_directory.path == run_directory:
                continue
            try:
                pinned_directory.close()
            except (OSError, _InvalidInvocation):
                cleanup_failed = True

    if cleanup_failed:
        _emit_invalid_invocation()
        return 2
    _emit_report(report)
    return 0 if report.status == "pass" else 1


def entrypoint() -> None:
    raise SystemExit(main())


def _parse_arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = _SafeArgumentParser(add_help=False)
    parser.add_argument("--codex-command", default=os.environ.get("AI_WORKSHOP_CODEX_COMMAND"))
    parser.add_argument("--codex-home", default=os.environ.get("AI_WORKSHOP_CODEX_HOME"))
    parser.add_argument("--report-dir", default=os.environ.get("AI_WORKSHOP_CODEX_REPORT_DIR"))
    arguments = parser.parse_args(argv)
    if not all(
        type(value) is str and value
        for value in (arguments.codex_command, arguments.codex_home, arguments.report_dir)
    ):
        raise _InvalidInvocation
    return arguments


def _resolve_repository_root(repository_root: Path | None) -> Path:
    root = repository_root or Path(__file__).resolve().parents[6]
    if not root.exists() or not root.is_dir():
        raise _InvalidInvocation
    _reject_reparse_traversal(root)
    return root.resolve(strict=True)


def _prepare_boundary(repository_root: Path) -> Path:
    local_data = repository_root / ".local-data"
    if not local_data.exists() or not local_data.is_dir():
        raise _InvalidInvocation
    _reject_reparse_traversal(local_data)

    boundary = local_data / "codex-app-server"
    if boundary.exists():
        if not boundary.is_dir():
            raise _InvalidInvocation
        _reject_reparse_traversal(boundary)
    else:
        boundary.mkdir()
    return boundary.resolve(strict=True)


def _validate_target(target: Path, boundary: Path, target_kind: str) -> Path:
    raw_target = _absolute_path(target)
    _reject_reparse_traversal(raw_target)
    if not raw_target.parent.exists() or not raw_target.parent.is_dir():
        raise _InvalidInvocation
    _reject_reparse_traversal(raw_target.parent)

    resolved_target = raw_target.resolve(strict=False)
    try:
        relative = resolved_target.relative_to(boundary)
    except ValueError as error:
        raise _InvalidInvocation from error
    if relative == Path(".") or not relative.parts:
        raise _InvalidInvocation
    if raw_target.exists() and not raw_target.is_dir():
        raise _InvalidInvocation
    if target_kind == "report" and raw_target.exists() and any(raw_target.iterdir()):
        raise _InvalidInvocation
    return resolved_target


def _prepare_report_directory(report_directory: Path) -> None:
    if report_directory.exists():
        if not report_directory.is_dir() or any(report_directory.iterdir()):
            raise _InvalidInvocation
    else:
        report_directory.mkdir()
    _reject_reparse_traversal(report_directory)
    if (report_directory / "gate-report.json").exists():
        raise _InvalidInvocation


def _prepare_home_directory(codex_home: Path) -> None:
    if codex_home.exists():
        if not codex_home.is_dir():
            raise _InvalidInvocation
    else:
        codex_home.mkdir()
    _reject_reparse_traversal(codex_home)


def _reject_overlapping_roles(
    codex_home: Path, report_directory: Path, run_parent: Path
) -> None:
    roles = (codex_home, report_directory, run_parent)
    for index, first in enumerate(roles):
        for second in roles[index + 1 :]:
            if _paths_overlap(first, second):
                raise _InvalidInvocation


def _paths_overlap(first: Path, second: Path) -> bool:
    return _is_within(first, second) or _is_within(second, first)


def _is_within(candidate: Path, parent: Path) -> bool:
    try:
        candidate.relative_to(parent)
    except ValueError:
        return False
    return True


def _create_run_directory(boundary: Path) -> Path:
    run_parent = boundary / "gate-runs"
    if run_parent.exists():
        if not run_parent.is_dir():
            raise _InvalidInvocation
        _reject_reparse_traversal(run_parent)
        if any(run_parent.iterdir()):
            raise _InvalidInvocation
    else:
        run_parent.mkdir()
    for _ in range(10):
        candidate = run_parent / f"run-{uuid.uuid4().hex}"
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        if any(candidate.iterdir()):
            raise _InvalidInvocation
        return candidate
    raise _InvalidInvocation


def _remove_empty_run_directory(
    run_directory: Path, run_pin: _PinnedDirectory, run_parent_pin: _PinnedDirectory
) -> None:
    if run_parent_pin.posix_fd is not None:
        name = run_directory.name
        details = os.stat(name, dir_fd=run_parent_pin.posix_fd, follow_symlinks=False)
        if details.st_dev != run_pin.device or details.st_ino != run_pin.inode:
            raise _InvalidInvocation
        os.rmdir(name, dir_fd=run_parent_pin.posix_fd)
        return
    if run_pin.windows_handle is None:
        raise _InvalidInvocation
    information = _FileDispositionInformation(True)
    if not _windows_kernel32().SetFileInformationByHandle(
        wintypes.HANDLE(run_pin.windows_handle),
        _FILE_DISPOSITION_INFO,
        ctypes.byref(information),
        ctypes.sizeof(information),
    ):
        raise _InvalidInvocation


def _read_cli_version(command: tuple[str, ...]) -> str:
    if len(command) != 2 or command[1] != "--version":
        raise _InvalidInvocation
    allowed_versions = tuple(ALLOWED_CODEX_APP_SERVER_VERSIONS)
    if len(allowed_versions) != 1:
        raise _InvalidInvocation
    allowed_version = allowed_versions[0]
    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        try:
            if os.name != "nt":
                process = subprocess.Popen(
                    command,
                    shell=False,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    start_new_session=True,
                )
            else:
                process = subprocess.Popen(
                    command,
                    shell=False,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_file,
                    stderr=stderr_file,
                )
        except (OSError, subprocess.SubprocessError):
            raise _InvalidInvocation from None
        job_handle: int | None = None
        try:
            if os.name == "nt":
                job_handle = _assign_windows_kill_on_close_job(process)
            try:
                returncode = _wait_for_version_process(
                    process, cast(BinaryIO, stdout_file), cast(BinaryIO, stderr_file)
                )
            except subprocess.TimeoutExpired:
                _stop_version_process(process)
                raise _InvalidInvocation from None
            stdout_file.seek(0)
            stderr_file.seek(0)
            stdout = stdout_file.read(_VERSION_OUTPUT_LIMIT_BYTES + 1)
            stderr = stderr_file.read(_VERSION_OUTPUT_LIMIT_BYTES + 1)
        finally:
            _stop_version_process(process)
            if job_handle is not None:
                _close_windows_handle(job_handle)
    if returncode != 0:
        raise _InvalidInvocation
    if (
        stdout != f"codex-cli {allowed_version}\n".encode()
        or stderr
    ):
        raise _InvalidInvocation
    return allowed_version


def _stop_version_process(process: subprocess.Popen[bytes]) -> None:
    if os.name != "nt":
        kill_process_group = getattr(os, "killpg", None)
        kill_signal = getattr(signal, "SIGKILL", None)
        if kill_process_group is None or kill_signal is None:
            with suppress(OSError):
                process.kill()
            return
        with suppress(OSError):
            kill_process_group(process.pid, signal.SIGTERM)
        cleanup_failed = False
        group_exists = True
        try:
            deadline = monotonic() + 0.2
            while monotonic() < deadline and _process_group_exists(
                kill_process_group, process.pid
            ):
                sleep(0.01)
            group_exists = _process_group_exists(kill_process_group, process.pid)
        except _InvalidInvocation:
            cleanup_failed = True
        if group_exists:
            with suppress(OSError):
                kill_process_group(process.pid, kill_signal)
        with suppress(OSError, subprocess.TimeoutExpired):
            process.wait(timeout=0.2)
        if cleanup_failed:
            raise _InvalidInvocation from None
        return
    if process.poll() is not None:
        return
    with suppress(OSError):
        process.terminate()
    try:
        process.wait(timeout=0.2)
    except (OSError, subprocess.TimeoutExpired):
        with suppress(OSError):
            process.kill()
        with suppress(OSError, subprocess.TimeoutExpired):
            process.wait(timeout=0.2)


def _process_group_exists(kill_process_group: object, process_id: int) -> bool:
    try:
        kill_process_group(process_id, 0)  # type: ignore[operator]
    except ProcessLookupError:
        return False
    except OSError as error:
        if error.errno == errno.ESRCH:
            return False
        raise _InvalidInvocation from None
    return True


def _write_report(
    report_directory: Path, report: IsolationGateReport, report_pin: _PinnedDirectory
) -> None:
    report_path = report_directory / "gate-report.json"
    if report_path.exists():
        raise _InvalidInvocation
    payload = json.dumps(
        asdict(report), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    temporary_name = f".gate-report-{uuid.uuid4().hex}.tmp"
    temporary_path = report_directory / temporary_name
    try:
        if report_pin.posix_fd is not None:
            descriptor = os.open(
                temporary_name,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
                dir_fd=report_pin.posix_fd,
            )
            output = os.fdopen(descriptor, "wb")
        else:
            output = temporary_path.open("xb")
        with output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        if report_pin.posix_fd is not None:
            os.link(
                temporary_name,
                "gate-report.json",
                src_dir_fd=report_pin.posix_fd,
                dst_dir_fd=report_pin.posix_fd,
                follow_symlinks=False,
            )
        else:
            os.link(temporary_path, report_path)
    except FileExistsError:
        raise _InvalidInvocation from None
    finally:
        if report_pin.posix_fd is not None:
            with suppress(FileNotFoundError):
                os.unlink(temporary_name, dir_fd=report_pin.posix_fd)
        else:
            with suppress(FileNotFoundError):
                temporary_path.unlink()


def _emit_invalid_invocation() -> None:
    print("status=invalid")
    print("safe_error_code=invalid_invocation")
    print("cli_version=unknown")


def _emit_report(report: IsolationGateReport) -> None:
    print(f"status={report.status}")
    print(f"safe_error_code={report.safe_error_code or 'none'}")
    print(f"cli_version={report.cli_version}")
    for violation in report.violations:
        print(f"rule_id={violation.rule_id}")
    print(f"observation_hash={report.observation_hash}")


def _absolute_path(path: Path) -> Path:
    return path if path.is_absolute() else Path.cwd() / path


def _reject_reparse_traversal(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if not os.path.lexists(current):
            continue
        details = os.lstat(current)
        attributes = getattr(details, "st_file_attributes", 0)
        if stat.S_ISLNK(details.st_mode) or attributes & _REPARSE_POINT:
            raise _InvalidInvocation


def _pin_directories(
    *directories: Path, delete_access_path: Path | None = None
) -> list[_PinnedDirectory]:
    if not directories:
        raise _InvalidInvocation
    root = directories[0]
    paths = _pin_paths_top_down(root, directories)
    if delete_access_path is not None and delete_access_path not in paths:
        raise _InvalidInvocation
    pinned: list[_PinnedDirectory] = []
    try:
        for path in paths:
            pinned.append(
                _pin_directory(path, delete_access=path == delete_access_path)
            )
    except BaseException:
        for item in reversed(pinned):
            with suppress(OSError, _InvalidInvocation):
                item.close()
        raise
    return pinned


def _pin_paths_top_down(root: Path, directories: Sequence[Path]) -> tuple[Path, ...]:
    unique_paths: dict[Path, None] = {}
    for directory in directories:
        try:
            relative = directory.relative_to(root)
        except ValueError as error:
            raise _InvalidInvocation from error
        current = root
        unique_paths.setdefault(current, None)
        for component in relative.parts:
            current /= component
            unique_paths.setdefault(current, None)
    return tuple(unique_paths)


def _pin_directory(
    directory: Path, *, delete_access: bool = False
) -> _PinnedDirectory:
    _reject_reparse_traversal(directory)
    details = directory.stat(follow_symlinks=False)
    if not stat.S_ISDIR(details.st_mode) or details.st_ino == 0:
        raise _InvalidInvocation
    if os.name != "nt":
        descriptor = _open_posix_directory(directory, details)
        return _PinnedDirectory(
            path=directory.resolve(strict=True),
            device=details.st_dev,
            inode=details.st_ino,
            windows_handle=None,
            posix_fd=descriptor,
        )
    handle = _open_windows_directory_handle(directory, delete_access=delete_access)
    identity = _windows_identity(handle)
    if identity[1] != details.st_ino:
        _close_windows_handle(handle)
        raise _InvalidInvocation
    return _PinnedDirectory(
        path=directory.resolve(strict=True),
        device=details.st_dev,
        inode=details.st_ino,
        windows_handle=handle,
        windows_identity=identity,
    )


def _open_windows_directory_handle(
    directory: Path, *, delete_access: bool = False
) -> int:
    desired_access = _FILE_READ_ATTRIBUTES | (_DELETE if delete_access else 0)
    handle = _windows_kernel32().CreateFileW(
        str(directory),
        desired_access,
        _FILE_SHARE_READ | _FILE_SHARE_WRITE,
        None,
        _OPEN_EXISTING,
        _FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    handle_value = ctypes.c_void_p(handle).value
    if handle_value is None or handle_value == _INVALID_HANDLE_VALUE:
        raise _InvalidInvocation
    return int(handle_value)


def _open_posix_directory(directory: Path, details: os.stat_result) -> int:
    required_flags = (getattr(os, "O_DIRECTORY", 0), getattr(os, "O_NOFOLLOW", 0))
    if not all(required_flags) or not Path("/proc/self/fd").is_dir():
        raise _InvalidInvocation
    try:
        descriptor = os.open(directory, os.O_RDONLY | required_flags[0] | required_flags[1])
    except OSError:
        raise _InvalidInvocation from None
    descriptor_details = os.fstat(descriptor)
    if (
        descriptor_details.st_dev != details.st_dev
        or descriptor_details.st_ino != details.st_ino
    ):
        os.close(descriptor)
        raise _InvalidInvocation
    return descriptor


def _close_windows_handle(handle: int) -> None:
    if not _windows_kernel32().CloseHandle(wintypes.HANDLE(handle)):
        raise _InvalidInvocation


def _windows_identity(handle: int) -> tuple[int, int]:
    information = _ByHandleFileInformation()
    if not _windows_kernel32().GetFileInformationByHandle(
        wintypes.HANDLE(handle), ctypes.byref(information)
    ):
        raise _InvalidInvocation
    return (
        int(information.dwVolumeSerialNumber),
        (int(information.nFileIndexHigh) << 32) | int(information.nFileIndexLow),
    )


def _windows_kernel32() -> ctypes.WinDLL:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.GetFileInformationByHandle.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_ByHandleFileInformation),
    ]
    kernel32.GetFileInformationByHandle.restype = wintypes.BOOL
    kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.SetFileInformationByHandle.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    kernel32.SetFileInformationByHandle.restype = wintypes.BOOL
    return kernel32


def _assign_windows_kill_on_close_job(process: subprocess.Popen[bytes]) -> int:
    process_handle = getattr(process, "_handle", None)
    if isinstance(process_handle, bool) or not isinstance(process_handle, int):
        raise _InvalidInvocation
    process_handle_value = int(process_handle)
    if (
        process_handle_value <= 0
        or process_handle_value > _MAX_HANDLE_VALUE
    ):
        raise _InvalidInvocation
    kernel32 = _windows_kernel32()
    job = kernel32.CreateJobObjectW(None, None)
    job_value = ctypes.c_void_p(job).value
    if job_value is None or job_value == _INVALID_HANDLE_VALUE:
        raise _InvalidInvocation
    information = _JobObjectExtendedLimitInformation()
    information.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel32.SetInformationJobObject(
        wintypes.HANDLE(job_value),
        _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
        ctypes.byref(information),
        ctypes.sizeof(information),
    ) or not kernel32.AssignProcessToJobObject(
        wintypes.HANDLE(job_value), wintypes.HANDLE(process_handle_value)
    ):
        _close_windows_handle(int(job_value))
        raise _InvalidInvocation
    return int(job_value)


def _wait_for_version_process(
    process: subprocess.Popen[bytes], stdout_file: BinaryIO, stderr_file: BinaryIO
) -> int:
    deadline = monotonic() + _VERSION_TIMEOUT_SECONDS
    while True:
        if (
            stdout_file.tell() > _VERSION_OUTPUT_LIMIT_BYTES
            or stderr_file.tell() > _VERSION_OUTPUT_LIMIT_BYTES
        ):
            raise subprocess.TimeoutExpired(process.args, _VERSION_TIMEOUT_SECONDS)
        returncode = process.poll()
        if returncode is not None:
            return returncode
        if monotonic() >= deadline:
            raise subprocess.TimeoutExpired(process.args, _VERSION_TIMEOUT_SECONDS)
        sleep(0.02)


def _verify_pinned_directories(
    pinned_directories: Sequence[_PinnedDirectory], boundary: Path
) -> None:
    for pinned_directory in pinned_directories:
        pinned_directory.verify(boundary)


def _stable_reference_for(
    path: Path, pinned_directories: Sequence[_PinnedDirectory]
) -> Path:
    for pinned_directory in pinned_directories:
        if pinned_directory.path == path:
            return pinned_directory.stable_reference()
    raise _InvalidInvocation


def _pinned_directory_for(
    path: Path, pinned_directories: Sequence[_PinnedDirectory]
) -> _PinnedDirectory:
    for pinned_directory in pinned_directories:
        if pinned_directory.path == path:
            return pinned_directory
    raise _InvalidInvocation


def _recheck_empty_report_directory(
    report_directory: Path, report_pin: _PinnedDirectory
) -> None:
    if report_pin.posix_fd is not None:
        if os.listdir(report_pin.posix_fd):
            raise _InvalidInvocation
    elif any(report_directory.iterdir()):
        raise _InvalidInvocation


def _failed_observation(cli_version: str) -> IsolationObservation:
    return IsolationObservation(
        cli_version=cli_version,
        config_read=False,
        requirements_read=False,
        effective_tool_inventory_read=False,
        forbidden_builtin_tool_count=None,
        shell_enabled=None,
        web_enabled=None,
        apps_enabled=None,
        plugins_enabled=None,
        multi_agent_enabled=None,
        mcp_callable_count=None,
        app_callable_count=None,
        plugin_enabled_count=None,
        skill_enabled_count=None,
        hook_enabled_count=None,
        approval_policy=None,
        sandbox_mode=None,
    )
