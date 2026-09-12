"""Private Win32 declarations, loaded only by the Windows runner.

Handle-list inheritance follows UpdateProcThreadAttribute; job accounting follows
QueryInformationJobObject (JobObjectBasicAccountingInformation).
"""

import ctypes as c
from ctypes import wintypes as w
from typing import Any


class StartupInfo(c.Structure):
    _fields_ = [
        ("cb", w.DWORD), ("reserved", w.LPWSTR), ("desktop", w.LPWSTR),
        ("title", w.LPWSTR), ("x", w.DWORD), ("y", w.DWORD),
        ("cx", w.DWORD), ("cy", w.DWORD), ("chars_x", w.DWORD),
        ("chars_y", w.DWORD), ("fill", w.DWORD), ("flags", w.DWORD),
        ("show", w.WORD), ("reserved_size", w.WORD), ("reserved_bytes", c.c_void_p),
        ("stdin", w.HANDLE), ("stdout", w.HANDLE), ("stderr", w.HANDLE),
    ]


class StartupInfoEx(c.Structure):
    _fields_ = [("startup", StartupInfo), ("attributes", c.c_void_p)]


class ProcessInfo(c.Structure):
    _fields_ = [("process", w.HANDLE), ("thread", w.HANDLE),
                ("pid", w.DWORD), ("tid", w.DWORD)]


class BasicLimits(c.Structure):
    _fields_ = [("process_time", c.c_int64), ("job_time", c.c_int64),
                ("flags", w.DWORD), ("min_ws", c.c_size_t), ("max_ws", c.c_size_t),
                ("active_limit", w.DWORD), ("affinity", c.c_size_t),
                ("priority", w.DWORD), ("scheduling", w.DWORD)]


class IoCounters(c.Structure):
    _fields_ = [(name, c.c_uint64) for name in
                ("read_ops", "write_ops", "other_ops", "read", "write", "other")]


class ExtendedLimits(c.Structure):
    _fields_ = [("basic", BasicLimits), ("io", IoCounters),
                ("process_memory", c.c_size_t), ("job_memory", c.c_size_t),
                ("peak_process", c.c_size_t), ("peak_job", c.c_size_t)]


class Accounting(c.Structure):
    _fields_ = [("user", c.c_int64), ("kernel", c.c_int64),
                ("period_user", c.c_int64), ("period_kernel", c.c_int64),
                ("faults", w.DWORD), ("total", w.DWORD),
                ("active", w.DWORD), ("terminated", w.DWORD)]


class Native:
    def __init__(self) -> None:
        self.dll = c.WinDLL("kernel32", use_last_error=True)
        signatures: dict[str, tuple[Any, list[Any]]] = {
            "CreateJobObjectW": (w.HANDLE, [c.c_void_p, w.LPCWSTR]),
            "SetInformationJobObject": (w.BOOL, [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]),
            "QueryInformationJobObject": (
                w.BOOL, [w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.c_void_p]),
            "AssignProcessToJobObject": (w.BOOL, [w.HANDLE, w.HANDLE]),
            "TerminateJobObject": (w.BOOL, [w.HANDLE, w.UINT]),
            "TerminateProcess": (w.BOOL, [w.HANDLE, w.UINT]),
            "CloseHandle": (w.BOOL, [w.HANDLE]),
            "ResumeThread": (w.DWORD, [w.HANDLE]),
            "WaitForSingleObject": (w.DWORD, [w.HANDLE, w.DWORD]),
            "GetExitCodeProcess": (w.BOOL, [w.HANDLE, c.POINTER(w.DWORD)]),
            "InitializeProcThreadAttributeList": (
                w.BOOL, [c.c_void_p, w.DWORD, w.DWORD, c.POINTER(c.c_size_t)]),
            "UpdateProcThreadAttribute": (w.BOOL, [c.c_void_p, w.DWORD, c.c_size_t,
                                                  c.c_void_p, c.c_size_t,
                                                  c.c_void_p, c.c_void_p]),
            "DeleteProcThreadAttributeList": (None, [c.c_void_p]),
            "CreateProcessW": (w.BOOL, [w.LPCWSTR, w.LPWSTR, c.c_void_p, c.c_void_p,
                                        w.BOOL, w.DWORD, c.c_void_p, w.LPCWSTR,
                                        c.POINTER(StartupInfoEx), c.POINTER(ProcessInfo)]),
            "PeekNamedPipe": (w.BOOL, [w.HANDLE, c.c_void_p, w.DWORD, c.c_void_p,
                                       c.POINTER(w.DWORD), c.c_void_p]),
        }
        for name, (restype, argtypes) in signatures.items():
            function = getattr(self.dll, name)
            function.restype = restype
            function.argtypes = argtypes

    def active_count(self, job: int) -> int:
        info = Accounting()
        if not self.dll.QueryInformationJobObject(job, 1, c.byref(info), c.sizeof(info), None):
            raise OSError("job_query_failed")
        return int(info.active)

    def close(self, handle: int) -> bool:
        return bool(self.dll.CloseHandle(handle))
