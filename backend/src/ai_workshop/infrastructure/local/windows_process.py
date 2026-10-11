"""Exact Windows process lifetimes, including the venv redirector child."""

import asyncio
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes as w
from pathlib import Path
from uuid import UUID

from ai_workshop.infrastructure.local.credential_store_windows import WindowsCredentialStore
from ai_workshop.infrastructure.local.service_launcher import SERVICE_MODULES
from ai_workshop.infrastructure.search.access_credentials import (
    AccessCredentialError,
    ChildLifetime,
    SecuredStoreIdentity,
    ServiceRole,
)


class ProcessEntry(ctypes.Structure):
    _fields_ = [
        ("size", w.DWORD),
        ("usage", w.DWORD),
        ("pid", w.DWORD),
        ("heap", ctypes.c_size_t),
        ("module", w.DWORD),
        ("threads", w.DWORD),
        ("parent_pid", w.DWORD),
        ("priority", w.LONG),
        ("flags", w.DWORD),
        ("exe", w.WCHAR * 260),
    ]


def process_identity(pid: int) -> tuple[str, Path]:
    if os.name != "nt":
        raise AccessCredentialError("credential_launch_denied")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.GetProcessTimes.argtypes = [
        w.HANDLE,
        ctypes.POINTER(w.FILETIME),
        ctypes.POINTER(w.FILETIME),
        ctypes.POINTER(w.FILETIME),
        ctypes.POINTER(w.FILETIME),
    ]
    kernel.QueryFullProcessImageNameW.argtypes = [
        w.HANDLE,
        w.DWORD,
        w.LPWSTR,
        ctypes.POINTER(w.DWORD),
    ]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        raise AccessCredentialError("credential_launch_denied")
    try:
        created, exited, system, user = w.FILETIME(), w.FILETIME(), w.FILETIME(), w.FILETIME()
        size, name = w.DWORD(32768), ctypes.create_unicode_buffer(32768)
        if not kernel.GetProcessTimes(
            handle,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(system),
            ctypes.byref(user),
        ) or not kernel.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(size)):
            raise AccessCredentialError("credential_launch_denied")
        return str((created.dwHighDateTime << 32) | created.dwLowDateTime), Path(name.value)
    finally:
        kernel.CloseHandle(handle)


def process_parents() -> dict[int, int]:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = w.HANDLE
    kernel.Process32FirstW.argtypes = [w.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.Process32NextW.argtypes = [w.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.CloseHandle.argtypes = [w.HANDLE]
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot in {None, ctypes.c_void_p(-1).value}:
        raise AccessCredentialError("credential_launch_denied")
    try:
        entry = ProcessEntry()
        entry.size = ctypes.sizeof(entry)
        result = {}
        good = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while good:
            result[entry.pid] = entry.parent_pid
            good = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        return result
    finally:
        kernel.CloseHandle(snapshot)


class NativeChildRuntime:
    def __init__(self, store: WindowsCredentialStore) -> None:
        self.store = store
        self.children: dict[UUID, subprocess.Popen[bytes]] = {}

    def start(
        self,
        argv: tuple[str, ...],
        env: dict[str, str],
        cwd: Path,
        identity: SecuredStoreIdentity,
        role: ServiceRole | None,
    ) -> ChildLifetime:
        launch_id = UUID(env["AI_WORKSHOP_ACCESS_LAUNCH_ID"])
        child = subprocess.Popen(
            argv,
            env=env,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        self.children[launch_id] = child
        outer_time, _outer_image = process_identity(child.pid)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            record = self.store.read_launch_record(launch_id)
            if record and record.get("kind") == "hello":
                pid = record.get("pid")
                if type(pid) is not int or pid <= 0:
                    raise AccessCredentialError("credential_launch_denied")
                created, image = process_identity(pid)
                parents = process_parents()
                if (
                    (pid != child.pid and parents.get(pid) != child.pid)
                    or record.get("creation_time") != created
                    or image
                    not in {
                        Path(sys.executable),
                        Path(getattr(sys, "_base_executable", sys.executable)),
                    }
                ):
                    raise AccessCredentialError("credential_launch_denied")
                if (
                    record.get("service") != argv[3]
                    or record.get("epoch_id") != str(identity.epoch_id)
                    or record.get("ordinal") != identity.ordinal
                ):
                    raise AccessCredentialError("credential_launch_denied")
                if argv[3] not in SERVICE_MODULES:
                    raise AccessCredentialError("credential_launch_denied")
                return ChildLifetime(
                    pid,
                    created,
                    SERVICE_MODULES[argv[3]],
                    role,
                    identity.epoch_id,
                    identity.ordinal,
                    child.pid,
                    outer_time,
                )
            if child.poll() is not None:
                raise AccessCredentialError("credential_launch_denied")
            time.sleep(0.05)
        raise AccessCredentialError("credential_outcome_unknown")

    async def wait_ack(self, launch_id: UUID, child: ChildLifetime) -> bool:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            record = self.store.read_launch_record(launch_id)
            if record and record.get("kind") == "ack":
                created, _image = process_identity(child.pid)
                return (
                    created == child.creation_time
                    and record.get("pid") == child.pid
                    and record.get("creation_time") == created
                    and record.get("epoch_id") == str(child.epoch_id)
                    and record.get("ordinal") == child.environment_epoch
                )
            await asyncio.sleep(0.05)
        return False
