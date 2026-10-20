"""The reviewed Windows Conda interpreter; no activation, overrides or fallback."""

import hashlib
import json
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

# Updating the descriptor requires a code review of this pin as well as its paths/hash.
DESCRIPTOR_SHA256 = "1a233b5d84a35b7df0dba52ae1beb77023799f1aa00a18445c2eef0bbbac67c4"


class PythonRuntimeError(ValueError):
    def __init__(self) -> None:
        super().__init__("local_python_runtime_unverified")


@dataclass(frozen=True, slots=True)
class ApprovedPython:
    executable: Path
    sha256: str


def _ordinary(path: Path) -> None:
    for component in (path, *path.parents):
        info = component.lstat()
        if getattr(info, "st_file_attributes", 0) & 0x400 or stat.S_ISLNK(info.st_mode):
            raise PythonRuntimeError()


def _read(path: Path, limit: int) -> bytes:
    _ordinary(path)
    with path.open("rb") as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= limit:
            raise PythonRuntimeError()
        data = source.read(limit + 1)
        after = os.fstat(source.fileno())
    _ordinary(path)
    current = path.stat()
    if (
        len(data) != before.st_size
        or len(data) > limit
        or any(
            (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
            != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            for value in (after, current)
        )
    ):
        raise PythonRuntimeError()
    return data


def _same_path(value: str, expected: Path) -> bool:
    path = Path(value)
    return path.is_absolute() and os.path.normcase(str(path)) == os.path.normcase(str(expected))


def approved_python(root: Path) -> ApprovedPython:
    """Revalidate the fixed descriptor, binary and already active process on each use."""
    try:
        descriptor = _read(root / "scripts/local_python_runtime.json", 4096)
        if hashlib.sha256(descriptor).hexdigest() != DESCRIPTOR_SHA256:
            raise PythonRuntimeError()
        value = json.loads(descriptor)
        if (
            type(value) is not dict
            or set(value) != {"schema", "prefix", "executable", "sha256"}
            or type(value["schema"]) is not int
            or value["schema"] != 1
            or type(value["prefix"]) is not str
            or value["executable"] != "python.exe"
            or type(value["sha256"]) is not str
        ):
            raise PythonRuntimeError()
        prefix = Path(value["prefix"])
        if not prefix.is_absolute():
            raise PythonRuntimeError()
        metadata = prefix / "conda-meta"
        _ordinary(metadata)
        if not metadata.is_dir():
            raise PythonRuntimeError()
        executable = prefix / "python.exe"
        digest = hashlib.sha256(_read(executable, 32 * 1024 * 1024)).hexdigest()
        if (
            digest != value["sha256"]
            or "PYTHONHOME" in os.environ
            or not _same_path(os.environ.get("CONDA_PREFIX", ""), prefix)
            or not _same_path(sys.prefix, prefix)
            or not _same_path(sys.executable, executable)
        ):
            raise PythonRuntimeError()
        return ApprovedPython(executable, digest)
    except Exception:
        raise PythonRuntimeError() from None
