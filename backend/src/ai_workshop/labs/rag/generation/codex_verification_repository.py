"""Independent passive SQL lookup and durable append-only proof/audit storage."""

import json
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import asdict, fields
from datetime import datetime
from functools import wraps
from hashlib import sha256
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ai_workshop.labs.rag.configurations.repository import SqlAlchemyRagConfigurationRepository
from ai_workshop.labs.rag.deployments.domain import DeploymentEnvironment, ProviderKind
from ai_workshop.labs.rag.models.domain import thaw_json
from ai_workshop.labs.rag.policies.domain import (
    exact_external_approval_is_current,
    resolve_external_transfer_policy,
)
from ai_workshop.labs.rag.policies.repository import SqlAlchemyDataPolicyRepository
from ai_workshop.platform.identity.domain import UserRole
from ai_workshop.platform.identity.models import UserRecord

from .codex_verification import (
    CodexPromptSignature,
    CodexStageAudit,
    CodexVerificationAttempt,
    CodexVerificationBinding,
    CodexVerificationConfiguration,
)
from .codex_verification_models import CodexStageAuditRecord, CodexVerificationAttemptRecord
from .domain import generation_disclosure
from .profile import resolve_generation_profile


def _safe[**P, T](operation: Callable[P, Awaitable[T]]) -> Callable[P, Coroutine[Any, Any, T]]:
    @wraps(operation)
    async def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
        try:
            return await operation(*args, **kwargs)
        except Exception:
            pass
        raise RuntimeError("codex_verification_storage_unavailable")

    return wrapped


def _json_default(value: object) -> str:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.isoformat()
    raise ValueError("codex_verification_metadata_invalid")


def _object(value: object) -> dict[str, object]:
    if type(value) is not dict:
        raise ValueError("codex_verification_metadata_invalid")
    return cast(dict[str, object], value)


def _binding(data: dict[str, object] | None) -> CodexVerificationBinding | None:
    if data is None:
        return None
    if set(data) != {field.name for field in fields(CodexVerificationBinding)}:
        raise ValueError("codex_verification_binding_invalid")
    values = dict(data)
    for name in ("configuration_version_id", "generation_profile_id", "deployment_version_id"):
        values[name] = UUID(str(values[name]))
    for name in ("context_prompt", "answer_prompt"):
        signature = _object(values[name])
        if set(signature) != {field.name for field in fields(CodexPromptSignature)}:
            raise ValueError("codex_verification_binding_invalid")
        values[name] = CodexPromptSignature(**signature)  # type: ignore[arg-type]
    return CodexVerificationBinding(**values)  # type: ignore[arg-type]


class SqlAlchemyCodexVerificationRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    @_safe
    async def append_attempt(self, attempt: CodexVerificationAttempt) -> None:
        if type(attempt) is not CodexVerificationAttempt:
            raise ValueError("codex_verification_metadata_invalid")
        binding = (
            json.loads(json.dumps(asdict(attempt.binding), default=_json_default, allow_nan=False))
            if attempt.binding is not None
            else None
        )
        async with self._sessions() as session, session.begin():
            session.add(
                CodexVerificationAttemptRecord(
                    id=attempt.id,
                    configuration_version_id=attempt.configuration_version_id,
                    generation_profile_id=attempt.generation_profile_id,
                    deployment_version_id=attempt.deployment_version_id,
                    checked_by=attempt.checked_by,
                    checked_at=attempt.checked_at,
                    binding=binding,
                    success=attempt.success,
                    usage_present=attempt.usage_present,
                    safe_error_code=attempt.safe_error_code,
                    requested_provider_model_id=attempt.requested_provider_model_id,
                    observed_provider_model_id=attempt.observed_provider_model_id,
                )
            )

    @_safe
    async def latest_attempt(
        self, configuration_version_id: UUID
    ) -> CodexVerificationAttempt | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(CodexVerificationAttemptRecord)
                .where(
                    CodexVerificationAttemptRecord.configuration_version_id
                    == configuration_version_id
                )
                .order_by(CodexVerificationAttemptRecord.sequence.desc())
                .limit(1)
            )
            if row is None:
                return None
            return CodexVerificationAttempt(
                row.id,
                row.configuration_version_id,
                row.generation_profile_id,
                row.deployment_version_id,
                _binding(row.binding),
                row.checked_by,
                row.checked_at,
                row.success,
                row.safe_error_code,
                row.requested_provider_model_id,
                row.observed_provider_model_id,
                row.usage_present,
            )

    @_safe
    async def append_stage(self, record: CodexStageAudit) -> None:
        if type(record) is not CodexStageAudit:
            raise ValueError("codex_verification_metadata_invalid")
        details = json.loads(json.dumps(asdict(record), default=_json_default, allow_nan=False))
        async with self._sessions() as session, session.begin():
            session.add(
                CodexStageAuditRecord(
                    id=record.id,
                    actor_id=record.actor_id,
                    request_id=record.request_id,
                    configuration_version_id=record.configuration_version_id,
                    generation_profile_id=record.generation_profile_id,
                    deployment_version_id=record.deployment_version_id,
                    stage=record.stage.value,
                    created_at=record.created_at,
                    details=details,
                )
            )


class SqlAlchemyCodexVerificationLookup:
    """No request attestation is created: actor, permission and policy are independently loaded."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession], *, environment: str) -> None:
        self._sessions, self._environment = sessions, environment

    @_safe
    async def load(
        self, *, actor_id: UUID, configuration_version_id: UUID
    ) -> CodexVerificationConfiguration | None:
        if self._environment not in {"local", "test"} or type(actor_id) is not UUID:
            return None
        async with self._sessions() as session, session.begin():
            policies = SqlAlchemyDataPolicyRepository(session)
            await policies.lock_external_execution_policy()
            actor = await session.get(UserRecord, actor_id)
            if actor is None or not actor.is_active or actor.role != UserRole.OWNER:
                return None
            configurations = SqlAlchemyRagConfigurationRepository(session)
            configuration = await configurations.find_version_visible(
                configuration_version_id, actor_id
            )
            if configuration is None or configuration.generation_profile_id is None:
                return None
            authorized = await configurations.authorized_workspace_ids(
                actor_id, configuration.workspace_ids
            )
            if set(authorized) != set(configuration.workspace_ids):
                return None
            generation = await configurations.find_profile(configuration.generation_profile_id)
            if generation is None or generation.deployment_version_id is None:
                return None
            deployment = await configurations.get_deployment_version(
                generation.deployment_version_id
            )
            if (
                deployment is None
                or deployment.provider is not ProviderKind.DEVELOPMENT_CODEX_EXEC
                or not deployment.development_only
                or DeploymentEnvironment.DEVELOPMENT not in deployment.allowed_environments
            ):
                return None
            model = await configurations.get_model_definition(deployment.model_definition_id)
            if model is None:
                return None
            profile = resolve_generation_profile(generation, deployment, model)
            installation = await policies.latest_installation_policy()
            workspace_policies = await policies.latest_workspace_policies(
                configuration.workspace_ids
            )
            if {item.workspace_id for item in workspace_policies} != set(
                configuration.workspace_ids
            ):
                return None
            policy = resolve_external_transfer_policy(
                provider=deployment.provider,
                installation=installation,
                workspaces=workspace_policies,
            )
            approval = await policies.get_external_approval_for_configuration(
                configuration_version_id
            )
            if (
                approval is None
                or not policy.allowed
                or not exact_external_approval_is_current(
                    approval_configuration_version_id=approval.configuration_version_id,
                    approval_deployment_version_id=approval.deployment_version_id,
                    approval_installation_policy_version_id=approval.installation_policy_version_id,
                    approval_disclosure_version=approval.disclosure_version,
                    approval_workspace_policy_snapshots=tuple(
                        (item.workspace_id, item.policy_version_id)
                        for item in approval.workspace_policies
                    ),
                    configuration_version_id=configuration_version_id,
                    deployment_version_id=deployment.id,
                    workspace_ids=configuration.workspace_ids,
                    policy=policy,
                    disclosure_version=generation_disclosure(deployment).version,
                )
            ):
                return None
            signature = sha256(
                json.dumps(
                    {
                        "generation": thaw_json(generation.config),
                        "model": thaw_json(model.config),
                        "profile_id": str(generation.id),
                        "profile_version": generation.version,
                        "model_id": str(model.id),
                        "model_version": model.version,
                        "deployment": {
                            **asdict(deployment),
                            "capabilities": sorted(deployment.capabilities),
                        },
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                    default=_json_default,
                    allow_nan=False,
                ).encode()
            ).hexdigest()
            return CodexVerificationConfiguration(
                configuration_version_id, tuple(sorted(authorized)), profile, signature
            )
