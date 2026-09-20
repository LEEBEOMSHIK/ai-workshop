"""Pure assembly of one Codex CLI request; this grants no launch authority.

A later coordinator owns current approval, payload/configuration fingerprint
binding, request-directory ownership, executable identity, and concurrency.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import ntpath
import os
import re
import subprocess
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from types import MappingProxyType
from typing import Any, NoReturn

from ai_workshop.labs.rag.generation.codex_authorization import (
    CodexCallIntent,
    CodexCallOperation,
    CodexCallStage,
    CodexExecutionPayload,
)
from ai_workshop.labs.rag.generation.codex_events import CodexEventLimits
from ai_workshop.labs.rag.generation.codex_runner_registry import (
    ResolvedCodexRunner,
    is_safe_codex_runner_reference,
)
from ai_workshop.labs.rag.generation.windows_process import ProcessLimits, ProcessRequest

_CLI_CONTRACT_VERSIONS = frozenset({"0.153.4", "0.155.1"})
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_MODEL_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")
_MAX_PROCESS_BYTES = 64 * 1024 * 1024
_ENVIRONMENT_KEYS = frozenset(
    {"SystemRoot", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "TEMP", "TMP", "CODEX_HOME"}
)
_ERROR_CODES = frozenset(
    {
        "codex_command_input_invalid",
        "codex_command_runner_mismatch",
        "codex_command_contract_unsupported",
        "codex_command_payload_mismatch",
        "codex_command_path_invalid",
        "codex_command_timeout_invalid",
        "codex_command_too_long",
    }
)


@dataclass(frozen=True, slots=True, repr=False)
class CodexCommandPlan:
    process_request: ProcessRequest
    output_schema_path: Path
    output_schema: bytes
    runner_configuration_sha256: str
    payload_sha256: str
    cli_contract_version: str


class CodexCommandError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code if code in _ERROR_CODES else "codex_command_input_invalid"
        super().__init__(self.code)


class _InvalidCommand(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code


def build_codex_command(
    *,
    runner: ResolvedCodexRunner,
    intent: CodexCallIntent,
    payload: CodexExecutionPayload,
    request_directory: Path,
    timeout_seconds: float,
) -> CodexCommandPlan:
    """Return immutable inputs without launch authority or filesystem access.

    The caller's later coordinator must own current approval, payload and
    configuration fingerprints, request ownership, executable identity, and
    concurrency before any launch.
    """

    failure_code: str | None = None
    try:
        return _build_codex_command(
            runner=runner,
            intent=intent,
            payload=payload,
            request_directory=request_directory,
            timeout_seconds=timeout_seconds,
        )
    except _InvalidCommand as error:
        failure_code = error.code
    except Exception:
        failure_code = "codex_command_input_invalid"
    raise CodexCommandError(failure_code)


def _build_codex_command(
    *,
    runner: ResolvedCodexRunner,
    intent: CodexCallIntent,
    payload: CodexExecutionPayload,
    request_directory: Path,
    timeout_seconds: float,
) -> CodexCommandPlan:
    if type(runner) is not ResolvedCodexRunner:
        _invalid("codex_command_input_invalid")
    if type(intent) is not CodexCallIntent or type(payload) is not CodexExecutionPayload:
        _invalid("codex_command_input_invalid")
    if not isinstance(request_directory, Path):
        _invalid("codex_command_input_invalid")

    _validate_runner(runner)
    _validate_intent(runner, intent)
    payload_sha256, developer_text = _validate_payload(runner, intent, payload)
    requested_timeout = _validate_requested_timeout(timeout_seconds)
    _validate_request_directory(runner.request_root, request_directory)

    output_schema_path = request_directory / "output-schema.json"
    developer_value = _toml_string(developer_text)
    argv = (
        "exec",
        "--strict-config",
        "--ignore-user-config",
        "--ephemeral",
        "--json",
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "--color",
        "never",
        "--model",
        intent.provider_model_id,
        "--cd",
        str(request_directory),
        "--output-schema",
        str(output_schema_path),
        "-c",
        'approval_policy="never"',
        "-c",
        'web_search="disabled"',
        "-c",
        "project_doc_max_bytes=0",
        "-c",
        "features.shell_tool=false",
        "-c",
        "features.multi_agent=false",
        "-c",
        "features.apps=false",
        "-c",
        "features.hooks=false",
        "-c",
        "developer_instructions=" + developer_value,
        "-",
    )
    command = subprocess.list2cmdline([str(runner.executable), *argv])
    if len(command.encode("utf-16-le")) // 2 >= 32767:
        _invalid("codex_command_too_long")

    limits = runner.process_limits
    process_limits = ProcessLimits(
        timeout_seconds=min(requested_timeout, float(limits.timeout_seconds)),
        stdin_bytes=limits.stdin_bytes,
        stdout_bytes=limits.stdout_bytes,
        stderr_bytes=limits.stderr_bytes,
        cleanup_seconds=limits.cleanup_seconds,
    )
    environment = MappingProxyType(dict(runner.environment))
    request = ProcessRequest(
        executable=runner.executable,
        argv=argv,
        cwd=request_directory,
        environment=environment,
        stdin=payload.stdin,
        limits=process_limits,
    )
    return CodexCommandPlan(
        process_request=request,
        output_schema_path=output_schema_path,
        output_schema=payload.output_schema,
        runner_configuration_sha256=runner.configuration_sha256,
        payload_sha256=payload_sha256,
        cli_contract_version=runner.expected_cli_version,
    )


def _validate_runner(runner: ResolvedCodexRunner) -> None:
    if not is_safe_codex_runner_reference(runner.reference):
        _invalid("codex_command_input_invalid")
    if runner.expected_cli_version not in _CLI_CONTRACT_VERSIONS:
        _invalid("codex_command_contract_unsupported")
    if not _valid_sha256(runner.executable_sha256) or not _valid_sha256(
        runner.configuration_sha256
    ):
        _invalid("codex_command_input_invalid")
    if not _safe_local_path(runner.executable) or not _safe_local_path(runner.request_root):
        _invalid("codex_command_input_invalid")
    if runner.executable.suffix.lower() != ".exe":
        _invalid("codex_command_input_invalid")
    _validate_process_limits(runner.process_limits)
    if type(runner.event_limits) is not CodexEventLimits:
        _invalid("codex_command_input_invalid")
    if type(runner.max_concurrent_requests) is not int or runner.max_concurrent_requests <= 0:
        _invalid("codex_command_input_invalid")
    _validate_environment(runner.environment)


def _validate_process_limits(limits: object) -> None:
    if type(limits) is not ProcessLimits:
        _invalid("codex_command_input_invalid")
    numeric_limits = (limits.timeout_seconds, limits.cleanup_seconds)
    if any(
        type(value) not in (int, float)
        or not math.isfinite(value)
        or not 0 < value <= 3600
        for value in numeric_limits
    ):
        _invalid("codex_command_input_invalid")
    byte_limits = (limits.stdin_bytes, limits.stdout_bytes, limits.stderr_bytes)
    if any(
        type(value) is not int or value < 0 or value > _MAX_PROCESS_BYTES
        for value in byte_limits
    ) or limits.stdout_bytes == 0:
        _invalid("codex_command_input_invalid")


def _validate_environment(environment: object) -> None:
    if not isinstance(environment, Mapping):
        _invalid("codex_command_input_invalid")
    seen: set[str] = set()
    for key, value in environment.items():
        if (
            type(key) is not str
            or key not in _ENVIRONMENT_KEYS
            or key.casefold() in seen
            or type(value) is not str
            or not _safe_local_path(Path(value))
        ):
            _invalid("codex_command_input_invalid")
        seen.add(key.casefold())


def _validate_intent(runner: ResolvedCodexRunner, intent: CodexCallIntent) -> None:
    if not is_safe_codex_runner_reference(intent.runner_ref):
        _invalid("codex_command_input_invalid")
    if intent.runner_ref != runner.reference:
        _invalid("codex_command_runner_mismatch")
    if not isinstance(intent.operation, CodexCallOperation) or not isinstance(
        intent.stage, CodexCallStage
    ):
        _invalid("codex_command_input_invalid")
    if type(intent.provider_model_id) is not str or _MODEL_PATTERN.fullmatch(
        intent.provider_model_id
    ) is None:
        _invalid("codex_command_input_invalid")
    if not _valid_sha256(intent.developer_instructions_sha256) or not _valid_sha256(
        intent.output_schema_sha256
    ):
        _invalid("codex_command_input_invalid")


def _validate_payload(
    runner: ResolvedCodexRunner,
    intent: CodexCallIntent,
    payload: CodexExecutionPayload,
) -> tuple[str, str]:
    if any(
        type(value) is not bytes
        for value in (payload.stdin, payload.developer_instructions, payload.output_schema)
    ):
        _invalid("codex_command_input_invalid")
    if len(payload.stdin) > runner.process_limits.stdin_bytes:
        _invalid("codex_command_input_invalid")
    developer_text = _utf8(payload.developer_instructions)
    if not developer_text or "\0" in developer_text or _has_surrogate(developer_text):
        _invalid("codex_command_input_invalid")
    _strict_json_object(payload.stdin)
    _strict_json_object(payload.output_schema)
    if not hmac.compare_digest(
        hashlib.sha256(payload.developer_instructions).hexdigest(),
        intent.developer_instructions_sha256,
    ) or not hmac.compare_digest(
        hashlib.sha256(payload.output_schema).hexdigest(), intent.output_schema_sha256
    ):
        _invalid("codex_command_payload_mismatch")
    payload_sha256 = payload.digest()
    if not _valid_sha256(payload_sha256):
        _invalid("codex_command_input_invalid")
    return payload_sha256, developer_text


def _strict_json_object(value: bytes) -> None:
    text = _utf8(value)

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = item
        return result

    def reject_constant(_value: str) -> NoReturn:
        raise ValueError("non-finite number")

    parsed = json.loads(
        text,
        object_pairs_hook=reject_duplicates,
        parse_constant=reject_constant,
    )
    if type(parsed) is not dict or not _valid_json_tree(parsed):
        _invalid("codex_command_input_invalid")


def _valid_json_tree(value: object) -> bool:
    if isinstance(value, str):
        return not _has_surrogate(value)
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str)
            and not _has_surrogate(key)
            and _valid_json_tree(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return all(_valid_json_tree(item) for item in value)
    return value is None or type(value) in (bool, int)


def _toml_string(value: str) -> str:
    encoded = json.dumps(value, ensure_ascii=False)
    # JSON permits a literal DEL while TOML basic strings do not.
    encoded = encoded.replace("\x7f", "\\u007f")
    parsed = tomllib.loads("developer_instructions=" + encoded)
    if parsed.get("developer_instructions") != value:
        _invalid("codex_command_input_invalid")
    return encoded


def _validate_requested_timeout(value: object) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 < value <= 3600
    ):
        _invalid("codex_command_timeout_invalid")
    return float(value)


def _validate_request_directory(root: Path, request_directory: Path) -> None:
    if not _safe_local_path(request_directory):
        _invalid("codex_command_path_invalid")
    windows_root = PureWindowsPath(str(root))
    windows_request = PureWindowsPath(str(request_directory))
    if windows_request == windows_root or windows_request.parent != windows_root:
        _invalid("codex_command_path_invalid")


def _safe_local_path(value: object) -> bool:
    if not isinstance(value, Path):
        return False
    raw = str(value)
    windows = PureWindowsPath(raw)
    path = Path(raw)
    raw_segments = tuple(segment for segment in re.split(r"[\\/]", raw) if segment)
    if (
        not raw
        or "\0" in raw
        or raw.startswith(("\\", "//"))
        or not path.is_absolute()
        or path == Path(path.anchor)
        or any(segment in (".", "..") for segment in raw_segments)
        or any(character in raw for character in ("%", "$", "~"))
        or (os.name != "nt" and (windows.drive or "\\" in raw))
        or _has_surrogate(raw)
    ):
        return False
    parts = windows.parts[1:] if windows.anchor else path.parts[1:]
    return not any(
        part.endswith((".", " "))
        or any(character in part for character in ':<>"|?*')
        or any(ord(character) < 32 or ord(character) == 127 for character in part)
        or ntpath.isreserved(part)
        for part in parts
    )


def _utf8(value: bytes) -> str:
    return value.decode("utf-8", errors="strict")


def _has_surrogate(value: str) -> bool:
    return any(0xD800 <= ord(character) <= 0xDFFF for character in value)


def _valid_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_PATTERN.fullmatch(value) is not None


def _invalid(code: str) -> NoReturn:
    raise _InvalidCommand(code)


__all__ = ["CodexCommandError", "CodexCommandPlan", "build_codex_command"]
