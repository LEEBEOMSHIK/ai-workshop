from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tomllib
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any
from uuid import UUID

import pytest

from ai_workshop.labs.rag.generation.codex_authorization import (
    CodexCallIntent,
    CodexCallOperation,
    CodexCallStage,
    CodexExecutionPayload,
)
from ai_workshop.labs.rag.generation.codex_command import (
    CodexCommandError,
    build_codex_command,
)
from ai_workshop.labs.rag.generation.codex_events import CodexEventLimits
from ai_workshop.labs.rag.generation.codex_prompt import build_codex_prompt
from ai_workshop.labs.rag.generation.codex_runner_registry import ResolvedCodexRunner
from ai_workshop.labs.rag.generation.domain import (
    ContextPolicy,
    ConversationRole,
    ConversationTurn,
    GenerationProfile,
    GenerationRequest,
    GroundingEvidence,
)
from ai_workshop.labs.rag.generation.windows_process import ProcessLimits


def _uuid(value: int) -> UUID:
    return UUID(int=value)


def _payload(
    *,
    stdin: bytes = b'{"question":"synthetic question"}',
    developer_instructions: bytes = b"trusted developer instructions",
    output_schema: bytes = b'{"type":"object"}',
) -> CodexExecutionPayload:
    return CodexExecutionPayload(stdin, developer_instructions, output_schema)


def _intent(
    payload: CodexExecutionPayload,
    **changes: object,
) -> CodexCallIntent:
    values: dict[str, object] = {
        "actor_id": _uuid(1),
        "request_id": _uuid(2),
        "approval_id": _uuid(3),
        "operation": CodexCallOperation.SEARCH,
        "stage": CodexCallStage.GENERATE,
        "configuration_version_id": _uuid(4),
        "deployment_version_id": _uuid(5),
        "generation_profile_id": _uuid(6),
        "runner_ref": "codex-cli-verified",
        "runner_configuration_sha256": "b" * 64,
        "provider_model_id": "approved-model:v1.2",
        "developer_instructions_sha256": hashlib.sha256(
            payload.developer_instructions
        ).hexdigest(),
        "output_schema_sha256": hashlib.sha256(payload.output_schema).hexdigest(),
        "workspace_ids": (),
        "workspace_policy_bindings": (),
        "installation_policy_version_id": _uuid(7),
        "generation_disclosure_version": "codex-external-v1",
        "evidence_revisions": (),
    }
    values.update(changes)
    return CodexCallIntent(**values)  # type: ignore[arg-type]


def _runner(
    tmp_path: Path,
    *,
    environment: dict[str, str] | None = None,
    process_limits: ProcessLimits | None = None,
) -> ResolvedCodexRunner:
    return ResolvedCodexRunner(
        reference="codex-cli-verified",
        executable=tmp_path / "installation" / "codex.exe",
        expected_cli_version="0.153.4",
        executable_sha256="a" * 64,
        request_root=tmp_path / "requests",
        environment=environment if environment is not None else {},
        process_limits=process_limits
        or ProcessLimits(
            timeout_seconds=60.0,
            stdin_bytes=1_048_576,
            stdout_bytes=1_048_576,
            stderr_bytes=65_536,
            cleanup_seconds=5.0,
        ),
        event_limits=CodexEventLimits(),
        max_concurrent_requests=1,
        configuration_sha256="b" * 64,
    )


def _build(
    tmp_path: Path,
    *,
    runner: ResolvedCodexRunner | None = None,
    intent: CodexCallIntent | None = None,
    payload: CodexExecutionPayload | None = None,
    request_directory: Path | None = None,
    timeout_seconds: float = 30.0,
):
    selected_payload = payload or _payload()
    selected_runner = runner or _runner(tmp_path)
    return build_codex_command(
        runner=selected_runner,
        intent=intent or _intent(selected_payload),
        payload=selected_payload,
        request_directory=request_directory
        or selected_runner.request_root / "request-synthetic",
        timeout_seconds=timeout_seconds,
    )


def _generation_request() -> GenerationRequest:
    profile = GenerationProfile(
        profile_id=_uuid(10),
        profile_name="codex grounded generation",
        profile_version=2,
        model_id=_uuid(11),
        model_name="selected model",
        model_version=3,
        runtime_model="registry/selected-model",
        prompt_ref="rag-codex-answer-v2",
        context_prompt_ref="rag-codex-contextualize-v1",
        context_policy=ContextPolicy(max_history_turns=6, max_history_tokens=1024),
        timeout_seconds=30.0,
        max_output_tokens=512,
        temperature=0.1,
        response_schema_version=2,
    )
    evidence = GroundingEvidence(
        evidence_id=_uuid(12),
        text="Synthetic evidence text",
        document_id=_uuid(13),
        asset_version_id=_uuid(14),
        projection_id=_uuid(15),
        chunk_id=_uuid(16),
        element_id=_uuid(17),
        page=7,
        char_start=2,
        char_end=25,
        bbox=(1.0, 2.0, 3.0, 4.0),
    )
    return GenerationRequest(
        question="Synthetic question",
        resolved_query="synthetic resolved query",
        history=(ConversationTurn(ConversationRole.USER, "Earlier synthetic question"),),
        evidence=(evidence,),
        profile=profile,
        correlation_id="not-transmitted",
    )


def test_real_prompt_envelope_builds_exact_non_executing_command_plan(
    tmp_path: Path,
) -> None:
    envelope = build_codex_prompt(_generation_request())
    payload = CodexExecutionPayload(
        stdin=envelope.stdin_json.encode(),
        developer_instructions=envelope.developer_instructions.encode(),
        output_schema=envelope.output_schema_json.encode(),
    )
    runner = _runner(tmp_path)
    request_directory = runner.request_root / "request-synthetic"

    plan = _build(
        tmp_path,
        runner=runner,
        intent=_intent(payload),
        payload=payload,
        request_directory=request_directory,
    )

    assert plan.process_request.stdin == payload.stdin
    assert plan.output_schema == payload.output_schema
    assert plan.payload_sha256 == payload.digest()
    assert plan.runner_configuration_sha256 == runner.configuration_sha256
    assert plan.process_request.limits.timeout_seconds == 30.0
    assert plan.output_schema_path == request_directory / "output-schema.json"
    assert plan.cli_contract_version == "0.153.4"
    assert not hasattr(plan, "ready")
    assert not request_directory.exists()


def test_argv_has_stable_exact_contract_and_no_shell_command(tmp_path: Path) -> None:
    runner = _runner(tmp_path)
    request_directory = runner.request_root / "request-synthetic"

    plan = _build(tmp_path, runner=runner, request_directory=request_directory)

    assert plan.process_request.executable == runner.executable
    assert plan.process_request.cwd == request_directory
    assert plan.process_request.argv == (
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
        "approved-model:v1.2",
        "--cd",
        str(request_directory),
        "--output-schema",
        str(request_directory / "output-schema.json"),
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
        'developer_instructions="trusted developer instructions"',
        "-",
    )
    assert isinstance(plan.process_request.argv, tuple)


def test_toml_developer_instructions_round_trip_without_config_injection(
    tmp_path: Path,
) -> None:
    developer_text = (
        '신뢰 지침 🧪 "quoted" \\ path\nline\tcontrol:\x01 delete:\x7f '
        '\nfeatures.shell_tool=true\napproval_policy="on-request"'
    )
    payload = _payload(developer_instructions=developer_text.encode())

    plan = _build(tmp_path, payload=payload, intent=_intent(payload))

    argv = plan.process_request.argv
    developer_override = argv[-2]
    assert developer_override.startswith("developer_instructions=")
    assert tomllib.loads(developer_override)["developer_instructions"] == developer_text
    assert argv.count("-c") == 8
    assert "features.shell_tool=true" in developer_override
    assert argv[argv.index("features.shell_tool=false")] == "features.shell_tool=false"


def test_exact_payload_bytes_and_determinism_are_preserved(tmp_path: Path) -> None:
    payload = _payload(
        stdin=b'{  "question" : "synthetic" }\r\n',
        output_schema=b'{\n  "type": "object"\n}\n',
    )
    intent = _intent(payload)

    first = _build(tmp_path, payload=payload, intent=intent)
    second = _build(tmp_path, payload=payload, intent=intent)

    assert first == second
    assert first.process_request.stdin is payload.stdin
    assert first.output_schema is payload.output_schema
    assert first.payload_sha256 == payload.digest()


def test_environment_is_copied_immutable_and_not_inherited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "GLOBAL-SECRET-CANARY")
    monkeypatch.setenv("PATH", "GLOBAL-PATH-CANARY")
    source_environment = {"TEMP": str(tmp_path / "runner-temp")}
    runner = _runner(tmp_path, environment=source_environment)

    plan = _build(tmp_path, runner=runner)
    source_environment["TEMP"] = str(tmp_path / "changed")

    assert plan.process_request.environment == {"TEMP": str(tmp_path / "runner-temp")}
    assert isinstance(plan.process_request.environment, MappingProxyType)
    assert "OPENAI_API_KEY" not in plan.process_request.environment
    assert "PATH" not in plan.process_request.environment
    with pytest.raises(TypeError):
        plan.process_request.environment["TEMP"] = "other"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        plan.process_request = plan.process_request  # type: ignore[misc]


def test_builder_has_no_filesystem_or_process_side_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request_directory = _runner(tmp_path).request_root / "request-synthetic"
    before = tuple(tmp_path.rglob("*"))

    def forbidden(*_args: object, **_kwargs: object) -> Any:
        pytest.fail("command assembly attempted a filesystem or process side effect")

    monkeypatch.setattr(Path, "mkdir", forbidden)
    monkeypatch.setattr(Path, "write_bytes", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)
    monkeypatch.setattr(Path, "touch", forbidden)
    monkeypatch.setattr(Path, "unlink", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(os, "system", forbidden)

    plan = _build(tmp_path, request_directory=request_directory)

    assert plan.output_schema_path == request_directory / "output-schema.json"
    assert tuple(tmp_path.rglob("*")) == before


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("reference", "codex-other", "codex_command_runner_mismatch"),
        ("expected_cli_version", "0.153.5", "codex_command_contract_unsupported"),
        ("configuration_sha256", "B" * 64, "codex_command_input_invalid"),
        ("configuration_sha256", "b" * 63, "codex_command_input_invalid"),
        ("executable_sha256", "A" * 64, "codex_command_input_invalid"),
    ],
)
def test_invalid_runner_binding_is_rejected(
    tmp_path: Path, field: str, value: object, code: str
) -> None:
    runner = replace(_runner(tmp_path), **{field: value})

    _assert_error(code, lambda: _build(tmp_path, runner=runner))


@pytest.mark.parametrize(
    "model",
    [
        "",
        " model",
        "model ",
        "-unsafe",
        "model/name",
        "model name",
        "model;command",
        "model&command",
        "model$(command)",
        "mödel",
        "a" * 201,
        "model\x00name",
        "model\nname",
    ],
)
def test_provider_model_must_be_bounded_ascii_identifier(
    tmp_path: Path, model: str
) -> None:
    payload = _payload()

    _assert_error(
        "codex_command_input_invalid",
        lambda: _build(tmp_path, payload=payload, intent=_intent(payload, provider_model_id=model)),
    )


@pytest.mark.parametrize("model", ["a", "gpt-5.5", "provider:model_v1.2"])
def test_provider_model_accepts_no_single_hard_coded_model(
    tmp_path: Path, model: str
) -> None:
    payload = _payload()

    plan = _build(
        tmp_path,
        payload=payload,
        intent=_intent(payload, provider_model_id=model),
    )

    assert plan.process_request.argv[plan.process_request.argv.index("--model") + 1] == model


@pytest.mark.parametrize("field,value", [("operation", "search"), ("stage", "generate")])
def test_intent_stage_and_operation_require_real_enums(
    tmp_path: Path, field: str, value: str
) -> None:
    payload = _payload()
    intent = replace(_intent(payload), **{field: value})

    _assert_error("codex_command_input_invalid", lambda: _build(tmp_path, intent=intent))


@pytest.mark.parametrize(
    "change",
    [
        {"runner_ref": "codex-other"},
        {"developer_instructions_sha256": "A" * 64},
        {"developer_instructions_sha256": "a" * 63},
        {"output_schema_sha256": "A" * 64},
        {"output_schema_sha256": "a" * 65},
    ],
)
def test_invalid_intent_binding_is_rejected(
    tmp_path: Path, change: dict[str, object]
) -> None:
    payload = _payload()
    expected = (
        "codex_command_runner_mismatch"
        if "runner_ref" in change
        else "codex_command_input_invalid"
    )

    _assert_error(expected, lambda: _build(tmp_path, intent=replace(_intent(payload), **change)))


@pytest.mark.parametrize(
    "change",
    [
        {"developer_instructions": b"tampered trusted instructions"},
        {"output_schema": b'{"type":"array"}'},
    ],
)
def test_payload_tampering_after_intent_binding_is_rejected(
    tmp_path: Path, change: dict[str, bytes]
) -> None:
    original = _payload()
    tampered = replace(original, **change)

    _assert_error(
        "codex_command_payload_mismatch",
        lambda: _build(tmp_path, payload=tampered, intent=_intent(original)),
    )


@pytest.mark.parametrize(
    "developer_instructions",
    [b"", b"bad\xffutf8", b"before\x00after", b"surrogate:\xed\xa0\x80"],
)
def test_invalid_developer_instruction_bytes_are_rejected(
    tmp_path: Path, developer_instructions: bytes
) -> None:
    payload = _payload(developer_instructions=developer_instructions)

    _assert_error(
        "codex_command_input_invalid",
        lambda: _build(tmp_path, payload=payload, intent=_intent(payload)),
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("stdin", b""),
        ("stdin", b"\xff"),
        ("stdin", b"[]"),
        ("stdin", b'{"same":1,"same":2}'),
        ("stdin", b'{"nested":{"same":1,"same":2}}'),
        ("stdin", b'{"value":NaN}'),
        ("stdin", b'{"value":Infinity}'),
        ("stdin", b'{"value":-Infinity}'),
        ("stdin", b'{"value":1e400}'),
        ("output_schema", b""),
        ("output_schema", b"\xff"),
        ("output_schema", b"[]"),
        ("output_schema", b'{"type":"object","type":"array"}'),
        ("output_schema", b'{"value":NaN}'),
    ],
)
def test_stdin_and_schema_require_strict_finite_json_objects(
    tmp_path: Path, field: str, value: bytes
) -> None:
    payload = replace(_payload(), **{field: value})

    _assert_error(
        "codex_command_input_invalid",
        lambda: _build(tmp_path, payload=payload, intent=_intent(payload)),
    )


def test_stdin_must_fit_runner_budget(tmp_path: Path) -> None:
    payload = _payload(stdin=b'{"question":"too long"}')
    runner = _runner(
        tmp_path,
        process_limits=ProcessLimits(60.0, 4, 100, 100, 5.0),
    )

    _assert_error(
        "codex_command_input_invalid",
        lambda: _build(tmp_path, runner=runner, payload=payload, intent=_intent(payload)),
    )


@pytest.mark.parametrize(
    "limits",
    [
        ProcessLimits(True, 100, 100, 100, 5.0),
        ProcessLimits("60", 100, 100, 100, 5.0),  # type: ignore[arg-type]
        ProcessLimits(float("nan"), 100, 100, 100, 5.0),
        ProcessLimits(60.0, True, 100, 100, 5.0),
        ProcessLimits(60.0, 100, 0, 100, 5.0),
        ProcessLimits(60.0, 100, 100, -1, 5.0),
        ProcessLimits(60.0, 100, 100, 100, float("inf")),
    ],
)
def test_runner_process_limits_cannot_bypass_strict_types(
    tmp_path: Path, limits: ProcessLimits
) -> None:
    _assert_error(
        "codex_command_input_invalid",
        lambda: _build(tmp_path, runner=_runner(tmp_path, process_limits=limits)),
    )


@pytest.mark.parametrize(
    "timeout",
    [True, False, "30", 0, -1, float("nan"), float("inf"), 3601],
)
def test_requested_timeout_is_finite_positive_and_bounded(
    tmp_path: Path, timeout: object
) -> None:
    _assert_error(
        "codex_command_timeout_invalid",
        lambda: _build(tmp_path, timeout_seconds=timeout),  # type: ignore[arg-type]
    )


def test_requested_timeout_is_capped_by_runner_limit(tmp_path: Path) -> None:
    runner = _runner(
        tmp_path,
        process_limits=ProcessLimits(12.5, 1000, 2000, 3000, 4.0),
    )

    plan = _build(tmp_path, runner=runner, timeout_seconds=30.0)

    assert plan.process_request.limits == ProcessLimits(12.5, 1000, 2000, 3000, 4.0)


def _invalid_request_directories(runner: ResolvedCodexRunner, tmp_path: Path) -> list[Path]:
    root = runner.request_root
    return [
        Path("relative-request"),
        root,
        root / "nested" / "request",
        tmp_path / "outside",
        Path(str(root) + "\\safe\\..\\escape"),
        Path(str(root) + "\\bad\x00name"),
        Path("\\\\server\\share\\request"),
        Path("\\\\?\\C:\\request"),
        Path("\\\\.\\C:\\request"),
        Path(str(root) + "\\trailing."),
        Path(str(root) + "\\trailing "),
        Path(str(root) + "\\stream:other"),
        Path(str(root) + "\\CON"),
        Path(str(root) + "\\bad*name"),
        Path(str(root) + "\\bad\x01name"),
        Path(str(root) + "\\%TEMP%"),
        Path(str(root) + "\\SHORT~1"),
    ]


def test_request_directory_must_be_safe_strict_direct_child(tmp_path: Path) -> None:
    runner = _runner(tmp_path)

    for request_directory in _invalid_request_directories(runner, tmp_path):
        _assert_error(
            "codex_command_path_invalid",
            lambda request_directory=request_directory: _build(
                tmp_path, runner=runner, request_directory=request_directory
            ),
        )


@pytest.mark.parametrize(
    "reserved_name",
    ["COM\u00b9", "LPT\u00b2.txt", "COM\u00b3.log", "CON .txt"],
)
def test_request_directory_rejects_all_windows_reserved_name_forms(
    tmp_path: Path, reserved_name: str
) -> None:
    runner = _runner(tmp_path)

    _assert_error(
        "codex_command_path_invalid",
        lambda: _build(
            tmp_path,
            runner=runner,
            request_directory=runner.request_root / reserved_name,
        ),
    )


@pytest.mark.parametrize("name", ["COM10", "LPT20.txt", "CONSOLE.txt", "COM\u2074"])
def test_request_directory_accepts_non_reserved_near_names(
    tmp_path: Path, name: str
) -> None:
    runner = _runner(tmp_path)
    request_directory = runner.request_root / name

    plan = _build(tmp_path, runner=runner, request_directory=request_directory)

    assert plan.process_request.cwd == request_directory


@pytest.mark.parametrize("field", ["request_root", "executable"])
def test_runner_paths_are_revalidated_without_filesystem_access(
    tmp_path: Path, field: str
) -> None:
    runner = replace(_runner(tmp_path), **{field: Path("relative")})

    _assert_error("codex_command_input_invalid", lambda: _build(tmp_path, runner=runner))


def test_windows_command_length_cap_includes_developer_instructions(
    tmp_path: Path,
) -> None:
    payload = _payload(developer_instructions=("trusted-" * 5000).encode())

    _assert_error(
        "codex_command_too_long",
        lambda: _build(tmp_path, payload=payload, intent=_intent(payload)),
    )


def test_windows_command_length_cap_includes_executable(tmp_path: Path) -> None:
    runner = replace(
        _runner(tmp_path),
        executable=Path("C:\\" + "a" * 32_700 + "\\codex.exe"),
    )

    _assert_error("codex_command_too_long", lambda: _build(tmp_path, runner=runner))


def test_prohibited_flags_and_untrusted_payload_never_enter_argv(tmp_path: Path) -> None:
    stdin_canary = "PRIVATE-QUESTION-CANARY"
    schema_canary = "PRIVATE-SCHEMA-CANARY"
    payload = _payload(
        stdin=json.dumps({"question": stdin_canary}).encode(),
        output_schema=json.dumps({"title": schema_canary}).encode(),
    )

    plan = _build(tmp_path, payload=payload, intent=_intent(payload))
    joined = "\n".join(plan.process_request.argv)

    assert stdin_canary not in joined
    assert schema_canary not in joined
    for forbidden in (
        "--dangerously-bypass-approvals-and-sandbox",
        "--full-auto",
        "--add-dir",
        "--resume",
        "--fork",
        "--image",
        "--output-last-message",
        "--profile",
        "--search",
        "--enable",
        "--disable",
    ):
        assert forbidden not in plan.process_request.argv
    assert "ignore-rules" not in joined
    assert "full-access" not in joined


@pytest.mark.parametrize("argument", ["runner", "intent", "payload", "request_directory"])
def test_wrong_dto_types_fail_with_safe_unchained_errors(
    tmp_path: Path, argument: str
) -> None:
    payload = _payload()
    runner = _runner(tmp_path)
    values: dict[str, object] = {
        "runner": runner,
        "intent": _intent(payload),
        "payload": payload,
        "request_directory": runner.request_root / "request-synthetic",
        "timeout_seconds": 30.0,
    }
    values[argument] = object()

    _assert_error(
        "codex_command_input_invalid",
        lambda: build_codex_command(**values),  # type: ignore[arg-type]
    )


def test_repr_and_errors_do_not_leak_payload_or_paths(tmp_path: Path) -> None:
    stdin_canary = "PRIVATE-STDIN-CANARY"
    schema_canary = "PRIVATE-SCHEMA-CANARY"
    payload = _payload(
        stdin=json.dumps({"question": stdin_canary}).encode(),
        developer_instructions=b"PRIVATE-DEVELOPER-CANARY",
        output_schema=json.dumps({"title": schema_canary}).encode(),
    )
    plan = _build(tmp_path, payload=payload, intent=_intent(payload))

    assert stdin_canary not in repr(plan)
    assert schema_canary not in repr(plan)
    assert "PRIVATE-DEVELOPER-CANARY" not in repr(plan)
    assert str(tmp_path) not in repr(plan)

    invalid_intent = _intent(payload, provider_model_id="PRIVATE;MODEL;CANARY")
    error = _capture_error(lambda: _build(tmp_path, payload=payload, intent=invalid_intent))
    assert str(error) == "codex_command_input_invalid"
    assert repr(error) == "CodexCommandError('codex_command_input_invalid')"
    assert "PRIVATE" not in str(error)
    assert error.__cause__ is None
    assert error.__context__ is None


def _capture_error(operation: Any) -> CodexCommandError:
    with pytest.raises(CodexCommandError) as raised:
        operation()
    return raised.value


def _assert_error(code: str, operation: Any) -> None:
    error = _capture_error(operation)
    assert error.code == code
    assert str(error) == code
    assert error.__cause__ is None
    assert error.__context__ is None
