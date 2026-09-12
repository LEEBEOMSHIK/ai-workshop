"""Versioned body-free intent encoding. UUID arrays sort by ascending UUID integer.

The same normalization applies to issuing, reading and reconstructing current state.
Only the typed intent can be encoded; arbitrary application payloads are rejected.
"""

from dataclasses import fields
from re import fullmatch
from typing import NoReturn
from uuid import UUID

from ai_workshop.labs.rag.generation.codex_authorization import (
    CodexCallIntent,
    CodexCallOperation,
    CodexCallStage,
    EvidenceRevision,
    WorkspacePolicyBinding,
)


def _invalid() -> NoReturn:
    raise ValueError("invalid_codex_approval_binding")


def _object(value: object, keys: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        _invalid()
    return value


def _text(value: object) -> str:
    if type(value) is not str or not value.strip():
        _invalid()
    return value


def _uuid(value: object) -> UUID:
    try:
        return UUID(_text(value))
    except ValueError:
        _invalid()


def valid_sha256(value: object) -> bool:
    return type(value) is str and fullmatch(r"[0-9a-f]{64}", value) is not None


def _digest(value: object) -> str:
    if not valid_sha256(value):
        _invalid()
    return _text(value)


def _array(value: object) -> list[object]:
    if not isinstance(value, list):
        _invalid()
    return value


def decode_intent(value: object) -> CodexCallIntent:
    data = _object(value, {field.name for field in fields(CodexCallIntent)} | {"version"})
    if type(data["version"]) is not int or data["version"] != 3:
        _invalid()
    try:
        operation = CodexCallOperation(_text(data["operation"]))
        stage = CodexCallStage(_text(data["stage"]))
    except ValueError:
        _invalid()
    runner = _text(data["runner_ref"])
    if (
        len(runner) > 120
        or fullmatch(r"[a-z][a-z0-9]*-[a-z0-9]+(?:-[a-z0-9]+)*", runner) is None
        or runner.startswith(("sk-", "sess-", "key-", "token-", "secret-"))
    ):
        _invalid()
    workspaces = tuple(sorted(_uuid(item) for item in _array(data["workspace_ids"])))
    bindings = []
    for item in _array(data["workspace_policy_bindings"]):
        binding = _object(item, {"workspace_id", "policy_version_id"})
        bindings.append(
            WorkspacePolicyBinding(
                _uuid(binding["workspace_id"]), _uuid(binding["policy_version_id"])
            )
        )
    revisions = []
    for item in _array(data["evidence_revisions"]):
        revision = _object(item, {"revision_id", "content_sha256", "approval_generation"})
        generation = revision["approval_generation"]
        if type(generation) is not int or generation <= 0:
            _invalid()
        revisions.append(
            EvidenceRevision(
                _uuid(revision["revision_id"]), _digest(revision["content_sha256"]), generation
            )
        )
    if (
        len(set(workspaces)) != len(workspaces)
        or len({item.workspace_id for item in bindings}) != len(bindings)
        or {item.workspace_id for item in bindings} != set(workspaces)
        or len({item.revision_id for item in revisions}) != len(revisions)
    ):
        _invalid()
    return CodexCallIntent(
        actor_id=_uuid(data["actor_id"]),
        request_id=_uuid(data["request_id"]),
        approval_id=_uuid(data["approval_id"]),
        operation=operation,
        stage=stage,
        configuration_version_id=_uuid(data["configuration_version_id"]),
        deployment_version_id=_uuid(data["deployment_version_id"]),
        generation_profile_id=_uuid(data["generation_profile_id"]),
        runner_ref=runner,
        provider_model_id=_text(data["provider_model_id"]),
        developer_instructions_sha256=_digest(data["developer_instructions_sha256"]),
        output_schema_sha256=_digest(data["output_schema_sha256"]),
        workspace_ids=workspaces,
        workspace_policy_bindings=tuple(sorted(bindings, key=lambda item: item.workspace_id)),
        installation_policy_version_id=_uuid(data["installation_policy_version_id"]),
        generation_disclosure_version=_text(data["generation_disclosure_version"]),
        evidence_revisions=tuple(sorted(revisions, key=lambda item: item.revision_id)),
        runner_configuration_sha256=_digest(data["runner_configuration_sha256"]),
    )


def encode_intent(intent: CodexCallIntent) -> dict[str, object]:
    if type(intent) is not CodexCallIntent:
        _invalid()
    if not isinstance(intent.operation, CodexCallOperation) or not isinstance(
        intent.stage, CodexCallStage
    ):
        _invalid()
    data: dict[str, object] = {"version": 3}
    for field in fields(intent):
        value = getattr(intent, field.name)
        if (
            field.name.endswith("_id")
            and field.name != "provider_model_id"
            and not isinstance(value, UUID)
        ):
            _invalid()
        if isinstance(value, UUID):
            value = str(value)
        elif isinstance(value, (CodexCallOperation, CodexCallStage)):
            value = value.value
        data[field.name] = value
    try:
        if (
            any(not isinstance(item, UUID) for item in intent.workspace_ids)
            or any(
                not isinstance(item.workspace_id, UUID)
                or not isinstance(item.policy_version_id, UUID)
                for item in intent.workspace_policy_bindings
            )
            or any(not isinstance(item.revision_id, UUID) for item in intent.evidence_revisions)
        ):
            _invalid()
        data["workspace_ids"] = [str(item) for item in sorted(intent.workspace_ids)]
        data["workspace_policy_bindings"] = [
            {
                "workspace_id": str(item.workspace_id),
                "policy_version_id": str(item.policy_version_id),
            }
            for item in sorted(intent.workspace_policy_bindings, key=lambda item: item.workspace_id)
        ]
        data["evidence_revisions"] = [
            {
                "revision_id": str(item.revision_id),
                "content_sha256": item.content_sha256,
                "approval_generation": item.approval_generation,
            }
            for item in sorted(intent.evidence_revisions, key=lambda item: item.revision_id)
        ]
        decode_intent(data)
    except (TypeError, AttributeError, ValueError):
        _invalid()
    return data


def canonical_intent(intent: CodexCallIntent) -> CodexCallIntent:
    return decode_intent(encode_intent(intent))
