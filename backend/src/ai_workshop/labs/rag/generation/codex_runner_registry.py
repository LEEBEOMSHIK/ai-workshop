"""Server-owned Codex configuration and read-only executable integrity inspection.

Resolution is neither readiness nor permission to launch. A future launcher must
recheck the executable and bind this configuration to current request approval;
path/stat inspection here cannot eliminate replacement races after inspection.
"""

import hashlib
import json
import ntpath
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from types import MappingProxyType
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ai_workshop.labs.rag.generation.codex_events import CodexEventLimits
from ai_workshop.labs.rag.generation.windows_process import ProcessLimits

_ENVIRONMENT_KEYS = {
    key.casefold(): key
    for key in (
        "SystemRoot",
        "USERPROFILE",
        "LOCALAPPDATA",
        "APPDATA",
        "TEMP",
        "TMP",
        "CODEX_HOME",
    )
}
_ERROR_CODES = frozenset(
    {
        "codex_runner_configuration_invalid",
        "codex_runner_environment_forbidden",
        "codex_runner_reference_invalid",
        "codex_runner_reference_unknown",
        "codex_runner_unavailable",
        "codex_runner_reparse_path",
        "codex_runner_path_overlap",
        "codex_runner_executable_invalid",
        "codex_runner_directory_invalid",
        "codex_runner_hash_mismatch",
        "codex_runner_executable_changed",
    }
)


def is_safe_codex_runner_reference(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= 120
        and re.fullmatch(r"[a-z][a-z0-9]*-[a-z0-9]+(?:-[a-z0-9]+)*", value) is not None
        and not value.startswith(("sk-", "sess-", "key-", "token-", "secret-"))
    )


def _local_path(value: object) -> Path:
    """Syntax only: no resolve/stat, expansion, interpolation or filesystem reads."""
    if not isinstance(value, (str, Path)):
        raise ValueError("Codex runner requires an explicit local path.")
    raw = str(value)
    windows = PureWindowsPath(raw)
    path = Path(raw)
    if (
        not raw
        or "\0" in raw
        or raw.startswith(("\\", "//"))
        or not path.is_absolute()
        or path == Path(path.anchor)
        or ".." in windows.parts
        or ".." in path.parts
        or any(char in raw for char in ("%", "$", "~"))
        or (os.name != "nt" and (windows.drive or "\\" in raw))
    ):
        raise ValueError("Codex runner requires an explicit local path.")
    # Reject Windows aliases/streams that undermine lexical containment checks.
    parts = windows.parts[1:] if windows.anchor else path.parts[1:]
    if any(
        part.endswith((".", " "))
        or any(char in part for char in ':<>"|?*')
        or any(ord(char) < 32 for char in part)
        or ntpath.isreserved(part)
        for part in parts
    ):
        raise ValueError("Codex runner requires an explicit local path.")
    return path


class CodexRunnerLimits(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, hide_input_in_errors=True)

    timeout_seconds: float = Field(default=60.0, gt=0, le=3600, allow_inf_nan=False)
    stdin_bytes: int = Field(default=1_048_576, ge=0, le=64 * 1024 * 1024)
    stdout_bytes: int = Field(default=1_048_576, gt=0, le=64 * 1024 * 1024)
    stderr_bytes: int = Field(default=65_536, ge=0, le=64 * 1024 * 1024)
    cleanup_seconds: float = Field(default=5.0, gt=0, le=3600, allow_inf_nan=False)
    max_line_bytes: int = Field(default=262_144, gt=0)
    max_events: int = Field(default=64, gt=0)
    max_input_tokens: int = Field(default=131_072, gt=0)
    max_output_tokens: int = Field(default=16_384, gt=0)
    max_concurrent_requests: int = Field(default=1, gt=0)

    @model_validator(mode="before")
    @classmethod
    def reject_unknown_fields(cls, value: object) -> object:
        if isinstance(value, dict) and any(key not in cls.model_fields for key in value):
            raise ValueError("Codex runner limits contain unsupported fields.")
        return value

    @model_validator(mode="after")
    def validate_line_budget(self) -> Self:
        if self.max_line_bytes > self.stdout_bytes:
            raise ValueError("Codex runner line budget exceeds stdout budget.")
        return self


class CodexRunnerSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, hide_input_in_errors=True)

    executable: Path = Field(repr=False)
    expected_cli_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    executable_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_root: Path = Field(repr=False)
    environment: dict[str, str] = Field(default_factory=dict, repr=False)
    limits: CodexRunnerLimits = Field(default_factory=CodexRunnerLimits)

    @model_validator(mode="before")
    @classmethod
    def reject_unknown_fields(cls, value: object) -> object:
        # hide_input_in_errors does not hide unknown field names in error locations.
        if isinstance(value, dict) and any(key not in cls.model_fields for key in value):
            raise ValueError("Codex runner settings contain unsupported fields.")
        return value

    @field_validator("executable", "request_root", mode="before")
    @classmethod
    def validate_local_path(cls, value: object) -> Path:
        return _local_path(value)

    @field_validator("environment", mode="before")
    @classmethod
    def validate_environment(cls, value: object) -> dict[str, str]:
        if not isinstance(value, dict):
            raise ValueError("Codex runner environment requires an explicit map.")
        cleaned: dict[str, str] = {}
        for key, item in value.items():
            canonical = _ENVIRONMENT_KEYS.get(key.casefold()) if isinstance(key, str) else None
            if canonical is None or canonical in cleaned or not isinstance(item, str):
                raise ValueError("Codex runner environment contains an invalid entry.")
            cleaned[canonical] = str(_local_path(item))
        return cleaned


@dataclass(frozen=True, repr=False)
class ResolvedCodexRunner:
    reference: str
    executable: Path
    expected_cli_version: str
    executable_sha256: str
    request_root: Path
    environment: Mapping[str, str]
    process_limits: ProcessLimits
    event_limits: CodexEventLimits
    max_concurrent_requests: int
    configuration_sha256: str


class CodexRunnerReferenceError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code if code in _ERROR_CODES else "codex_runner_configuration_invalid"
        super().__init__(self.code)


class CodexRunnerRegistry:
    def __init__(
        self,
        entries: Mapping[str, CodexRunnerSettings],
        *,
        environment: str,
        protected_roots: tuple[Path, ...],
    ) -> None:
        failed = False
        copied: dict[str, CodexRunnerSettings] = {}
        roots: tuple[Path, ...] = ()
        try:
            if not isinstance(entries, Mapping) or not protected_roots:
                raise ValueError("Invalid registry configuration")
            roots = tuple(_local_path(root) for root in protected_roots)
            for name, entry in entries.items():
                if not is_safe_codex_runner_reference(name) or not isinstance(
                    entry, CodexRunnerSettings
                ):
                    raise ValueError("Invalid registry configuration")
                # Bypass Pydantic instance acceptance and revalidate nested DTOs.
                data = dict(entry.__dict__)
                if isinstance(data.get("limits"), CodexRunnerLimits):
                    data["limits"] = dict(data["limits"].__dict__)
                if entry.__pydantic_extra__:
                    data.update(entry.__pydantic_extra__)
                copied[name] = CodexRunnerSettings.model_validate(data)
        except (ValueError, TypeError, AttributeError, OSError):
            failed = True
        # Raising outside the handler prevents even __context__ exposing input.
        if failed:
            raise CodexRunnerReferenceError("codex_runner_configuration_invalid")
        self._entries = copied
        self._environment = environment
        self._protected_roots = roots

    def resolve(self, reference: str) -> ResolvedCodexRunner:
        if self._environment not in ("local", "test"):
            raise CodexRunnerReferenceError("codex_runner_environment_forbidden")
        if not is_safe_codex_runner_reference(reference):
            raise CodexRunnerReferenceError("codex_runner_reference_invalid")
        entry = self._entries.get(reference)
        if entry is None:
            raise CodexRunnerReferenceError("codex_runner_reference_unknown")
        failure: str | None = None
        try:
            self._inspect(entry)
        except CodexRunnerReferenceError as error:
            failure = error.code
        except (OSError, ValueError):
            failure = "codex_runner_unavailable"
        if failure is not None:
            raise CodexRunnerReferenceError(failure)
        limits = entry.limits
        canonical = json.dumps(entry.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return ResolvedCodexRunner(
            reference=reference,
            executable=entry.executable,
            expected_cli_version=entry.expected_cli_version,
            executable_sha256=entry.executable_sha256,
            request_root=entry.request_root,
            environment=MappingProxyType(dict(entry.environment)),
            process_limits=ProcessLimits(
                timeout_seconds=limits.timeout_seconds,
                stdin_bytes=limits.stdin_bytes,
                stdout_bytes=limits.stdout_bytes,
                stderr_bytes=limits.stderr_bytes,
                cleanup_seconds=limits.cleanup_seconds,
            ),
            event_limits=CodexEventLimits(
                max_total_bytes=limits.stdout_bytes,
                max_line_bytes=limits.max_line_bytes,
                max_events=limits.max_events,
                max_input_tokens=limits.max_input_tokens,
                max_output_tokens=limits.max_output_tokens,
            ),
            max_concurrent_requests=limits.max_concurrent_requests,
            configuration_sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        )

    def _inspect(self, entry: CodexRunnerSettings) -> None:
        environment_roots = tuple(Path(value) for value in entry.environment.values())
        paths = (entry.executable, entry.request_root, *environment_roots, *self._protected_roots)
        for path in paths:
            _inspect_components(path)
        # Canonicalization expands native aliases (e.g. Windows short names),
        # only after rejecting links, then inspect those expanded paths as well.
        canonical = {path: path.resolve() for path in paths}
        for path in canonical.values():
            _inspect_components(path)
        request_root = canonical[entry.request_root]
        for root in self._protected_roots:
            if _overlap(request_root, canonical[root]):
                raise CodexRunnerReferenceError("codex_runner_path_overlap")
        if _overlap(request_root, canonical[entry.executable].parent):
            raise CodexRunnerReferenceError("codex_runner_path_overlap")
        for directory in (entry.request_root, *environment_roots):
            if not stat.S_ISDIR(directory.lstat().st_mode):
                raise CodexRunnerReferenceError("codex_runner_directory_invalid")
        executable_stat = entry.executable.lstat()
        if entry.executable.suffix.lower() != ".exe" or not stat.S_ISREG(executable_stat.st_mode):
            raise CodexRunnerReferenceError("codex_runner_executable_invalid")
        digest = _executable_digest(entry.executable, executable_stat)
        if digest != entry.executable_sha256:
            raise CodexRunnerReferenceError("codex_runner_hash_mismatch")


def _overlap(left: Path, right: Path) -> bool:
    return left.is_relative_to(right) or right.is_relative_to(left)


def _inspect_components(path: Path) -> None:
    for component in (*reversed(path.parents), path):
        try:
            metadata = component.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
            raise CodexRunnerReferenceError("codex_runner_reparse_path")


def _stat_identity(value: os.stat_result) -> tuple[int, ...]:
    # Windows path stat infers executable mode from the suffix; fstat cannot.
    # ctime semantics can also differ. Compare those within each API below.
    # Read atime is deliberately excluded.
    return (
        value.st_dev,
        value.st_ino,
        stat.S_IFMT(value.st_mode),
        value.st_size,
        value.st_mtime_ns,
        getattr(value, "st_file_attributes", 0),
    )


def _stat_metadata(value: os.stat_result) -> tuple[int, ...]:
    return (
        *_stat_identity(value),
        value.st_mode,
        value.st_ctime_ns,
        getattr(value, "st_birthtime_ns", 0),
    )


def _executable_digest(path: Path, before: os.stat_result) -> str:
    expected = _stat_identity(before)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if _stat_identity(opened) != expected:
            raise CodexRunnerReferenceError("codex_runner_executable_changed")
        remaining = before.st_size
        while remaining:
            chunk = stream.read(min(65_536, remaining))
            if not chunk:
                raise CodexRunnerReferenceError("codex_runner_executable_changed")
            remaining -= len(chunk)
            digest.update(chunk)
        if _stat_metadata(os.fstat(stream.fileno())) != _stat_metadata(opened):
            raise CodexRunnerReferenceError("codex_runner_executable_changed")
    _inspect_components(path)
    if _stat_metadata(path.lstat()) != _stat_metadata(before):
        raise CodexRunnerReferenceError("codex_runner_executable_changed")
    return digest.hexdigest()
