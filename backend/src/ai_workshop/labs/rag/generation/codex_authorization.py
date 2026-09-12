"""Per-call authorization boundary for future Codex execution adapters."""

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from typing import Protocol, TypeVar, cast
from uuid import UUID

from ai_workshop.labs.rag.deployments.domain import DeploymentEnvironment
from ai_workshop.labs.rag.policies.domain import PolicyDecision
from ai_workshop.platform.identity.domain import UserRole


class CodexCallOperation(StrEnum):
    SEARCH = "search"
    EVALUATION = "evaluation"
    CONNECTION_CHECK = "connection_check"


class CodexCallStage(StrEnum):
    CONTEXTUALIZE = "contextualize"
    GENERATE = "generate"


class EvidenceClassification(StrEnum):
    PUBLIC = "public"
    SYNTHETIC = "synthetic"
    PRIVATE = "private"


class CodexAuthorizationErrorCode(StrEnum):
    SOURCE_UNAVAILABLE = "source_unavailable"
    INVALID_INTENT = "invalid_intent"
    UNAUTHENTICATED = "unauthenticated"
    ACTOR_NOT_AUTHORIZED = "actor_not_authorized"
    ENVIRONMENT_NOT_ALLOWED = "environment_not_allowed"
    INTENT_MISMATCH = "intent_mismatch"
    POLICY_DENIED = "policy_denied"
    CONSENT_REQUIRED = "consent_required"
    APPROVAL_REVOKED = "approval_revoked"
    APPROVAL_EXPIRED = "approval_expired"
    SCOPE_MISMATCH = "scope_mismatch"
    EVIDENCE_NOT_APPROVED = "evidence_not_approved"
    EVIDENCE_APPROVAL_CONFLICT = "evidence_approval_conflict"
    PAYLOAD_MISMATCH = "payload_mismatch"
    APPROVAL_ALREADY_CONSUMED = "approval_already_consumed"
    OPERATION_FAILED = "operation_failed"


class CodexAuthorizationError(RuntimeError):
    def __init__(self, code: CodexAuthorizationErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True, slots=True)
class WorkspacePolicyBinding:
    workspace_id: UUID
    policy_version_id: UUID


@dataclass(frozen=True, slots=True)
class EvidenceRevision:
    revision_id: UUID
    content_sha256: str
    approval_generation: int


@dataclass(frozen=True, slots=True)
class EvidenceApproval:
    revision_id: UUID
    content_sha256: str
    classification: EvidenceClassification
    approval_generation: int


@dataclass(frozen=True, slots=True)
class CodexCallIntent:
    actor_id: UUID
    request_id: UUID
    approval_id: UUID
    operation: CodexCallOperation
    stage: CodexCallStage
    configuration_version_id: UUID
    deployment_version_id: UUID
    generation_profile_id: UUID
    runner_ref: str
    provider_model_id: str
    developer_instructions_sha256: str
    output_schema_sha256: str
    workspace_ids: tuple[UUID, ...]
    workspace_policy_bindings: tuple[WorkspacePolicyBinding, ...]
    installation_policy_version_id: UUID
    generation_disclosure_version: str
    evidence_revisions: tuple[EvidenceRevision, ...]
    runner_configuration_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace_ids", tuple(self.workspace_ids))
        object.__setattr__(self, "workspace_policy_bindings", tuple(self.workspace_policy_bindings))
        object.__setattr__(self, "evidence_revisions", tuple(self.evidence_revisions))


@dataclass(frozen=True, slots=True, repr=False)
class CodexExecutionPayload:
    stdin: bytes
    developer_instructions: bytes
    output_schema: bytes

    def __post_init__(self) -> None:
        object.__setattr__(self, "stdin", bytes(self.stdin))
        object.__setattr__(self, "developer_instructions", bytes(self.developer_instructions))
        object.__setattr__(self, "output_schema", bytes(self.output_schema))

    def digest(self) -> str:
        digest = sha256()
        for part in (self.stdin, self.developer_instructions, self.output_schema):
            digest.update(len(part).to_bytes(8, byteorder="big"))
            digest.update(part)
        return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class CodexCurrentAuthorization:
    actor_id: UUID | None
    actor_role: UserRole | None
    actor_active: bool
    environment: DeploymentEnvironment
    current_intent: CodexCallIntent
    approved_by: UUID
    issued_at: datetime
    expires_at: datetime
    revoked: bool
    consented: bool
    policy: PolicyDecision
    allowed_workspace_ids: tuple[UUID, ...]
    evidence_approvals: tuple[EvidenceApproval, ...]
    approved_payload_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "allowed_workspace_ids", tuple(self.allowed_workspace_ids))
        object.__setattr__(self, "evidence_approvals", tuple(self.evidence_approvals))


class CodexAuthorizationSource(Protocol):
    """Trusted server-side source for current authorization state.

    An adapter must independently load current actor, policy, scope, evidence, and
    approval values; it must never construct ``current_intent`` by echoing the
    caller's intent. The context must serialize validation and consumption for an
    approval across processes. ``consume`` must make an atomic, durable reservation
    that does not roll back when the surrounding context exits because the operation
    fails or is cancelled. A real adapter is intentionally not provided here.
    """

    def locked_snapshot(
        self, intent: CodexCallIntent
    ) -> AbstractAsyncContextManager[CodexCurrentAuthorization | None]: ...

    async def consume(self, approval_id: UUID, request_id: UUID, stage: CodexCallStage) -> bool: ...


ResultT = TypeVar("ResultT")


class CodexExecutionGate:
    def __init__(
        self,
        *,
        source: CodexAuthorizationSource | None,
        clock: Callable[[], datetime],
    ) -> None:
        self._source = source
        self._clock = clock

    async def run(
        self,
        intent: CodexCallIntent,
        payload: CodexExecutionPayload,
        operation: Callable[[CodexExecutionPayload], Awaitable[ResultT]],
    ) -> ResultT:
        source = self._source
        if source is None:
            raise CodexAuthorizationError(CodexAuthorizationErrorCode.SOURCE_UNAVAILABLE)

        decision_code: CodexAuthorizationErrorCode | None = None
        source_error_code: CodexAuthorizationErrorCode | None = None
        operation_completed = False
        result: ResultT | None = None
        try:
            context = source.locked_snapshot(intent)
            async with context as snapshot:
                if snapshot is None:
                    decision_code = CodexAuthorizationErrorCode.SOURCE_UNAVAILABLE
                else:
                    decision_code = _authorization_error_code(
                        intent, payload, snapshot, self._clock()
                    )
                    if decision_code is None:
                        consumed = False
                        try:
                            consumed = await source.consume(
                                intent.approval_id, intent.request_id, intent.stage
                            )
                        except CodexAuthorizationError as error:
                            decision_code = error.code
                        except Exception:
                            decision_code = CodexAuthorizationErrorCode.SOURCE_UNAVAILABLE
                        if decision_code is None and not consumed:
                            decision_code = CodexAuthorizationErrorCode.APPROVAL_ALREADY_CONSUMED
                        if decision_code is None:
                            decision_code = _authorization_error_code(
                                intent, payload, snapshot, self._clock()
                            )
                        if decision_code is None:
                            try:
                                result = await operation(payload)
                            except Exception:
                                decision_code = CodexAuthorizationErrorCode.OPERATION_FAILED
                            else:
                                operation_completed = True
        except CodexAuthorizationError as error:
            source_error_code = error.code
        except Exception:
            source_error_code = CodexAuthorizationErrorCode.SOURCE_UNAVAILABLE

        if source_error_code is not None:
            raise CodexAuthorizationError(source_error_code)
        if decision_code is not None:
            raise CodexAuthorizationError(decision_code)
        if not operation_completed:
            raise CodexAuthorizationError(CodexAuthorizationErrorCode.SOURCE_UNAVAILABLE)
        return cast(ResultT, result)


def _authorization_error_code(
    intent: CodexCallIntent,
    payload: CodexExecutionPayload,
    snapshot: CodexCurrentAuthorization,
    now: datetime,
) -> CodexAuthorizationErrorCode | None:
    try:
        _authorize(intent, payload, snapshot, now)
    except CodexAuthorizationError as error:
        return error.code
    return None


def _authorize(
    intent: CodexCallIntent,
    payload: CodexExecutionPayload,
    snapshot: CodexCurrentAuthorization,
    now: datetime,
) -> None:
    if not _valid_intent_shape(intent):
        _deny(CodexAuthorizationErrorCode.INVALID_INTENT)
    if snapshot.actor_id is None or snapshot.actor_role is None:
        _deny(CodexAuthorizationErrorCode.UNAUTHENTICATED)
    if (
        snapshot.actor_id != intent.actor_id
        or snapshot.approved_by != intent.actor_id
        or snapshot.actor_role is not UserRole.OWNER
        or not snapshot.actor_active
    ):
        _deny(CodexAuthorizationErrorCode.ACTOR_NOT_AUTHORIZED)
    if snapshot.environment is not DeploymentEnvironment.DEVELOPMENT:
        _deny(CodexAuthorizationErrorCode.ENVIRONMENT_NOT_ALLOWED)
    if snapshot.current_intent != intent:
        _deny(CodexAuthorizationErrorCode.INTENT_MISMATCH)
    if snapshot.revoked:
        _deny(CodexAuthorizationErrorCode.APPROVAL_REVOKED)
    if not snapshot.consented:
        _deny(CodexAuthorizationErrorCode.CONSENT_REQUIRED)
    if (
        not _valid_utc(now)
        or not _valid_utc(snapshot.issued_at)
        or not _valid_utc(snapshot.expires_at)
    ):
        _deny(CodexAuthorizationErrorCode.APPROVAL_EXPIRED)
    if not snapshot.issued_at <= now < snapshot.expires_at:
        _deny(CodexAuthorizationErrorCode.APPROVAL_EXPIRED)
    if not snapshot.policy.allowed:
        _deny(CodexAuthorizationErrorCode.POLICY_DENIED)
    if not _policy_matches_intent(intent, snapshot.policy):
        _deny(CodexAuthorizationErrorCode.SCOPE_MISMATCH)
    if not _scope_matches(intent.workspace_ids, snapshot.allowed_workspace_ids):
        _deny(CodexAuthorizationErrorCode.SCOPE_MISMATCH)
    if not _evidence_matches(intent, snapshot.evidence_approvals):
        _deny(CodexAuthorizationErrorCode.EVIDENCE_NOT_APPROVED)
    if (
        sha256(payload.developer_instructions).hexdigest() != intent.developer_instructions_sha256
        or sha256(payload.output_schema).hexdigest() != intent.output_schema_sha256
        or payload.digest() != snapshot.approved_payload_sha256
    ):
        _deny(CodexAuthorizationErrorCode.PAYLOAD_MISMATCH)


def _valid_intent_shape(intent: CodexCallIntent) -> bool:
    workspace_ids = intent.workspace_ids
    binding_ids = tuple(binding.workspace_id for binding in intent.workspace_policy_bindings)
    evidence_ids = tuple(revision.revision_id for revision in intent.evidence_revisions)
    return (
        isinstance(intent.operation, CodexCallOperation)
        and isinstance(intent.stage, CodexCallStage)
        and bool(intent.runner_ref)
        and bool(intent.provider_model_id)
        and bool(intent.generation_disclosure_version)
        and _valid_sha256(intent.developer_instructions_sha256)
        and _valid_sha256(intent.output_schema_sha256)
        and _valid_sha256(intent.runner_configuration_sha256)
        and len(set(workspace_ids)) == len(workspace_ids)
        and len(set(binding_ids)) == len(binding_ids)
        and set(binding_ids) == set(workspace_ids)
        and len(set(evidence_ids)) == len(evidence_ids)
        and all(
            _valid_sha256(revision.content_sha256)
            and type(revision.approval_generation) is int
            and revision.approval_generation > 0
            for revision in intent.evidence_revisions
        )
    )


def _policy_matches_intent(intent: CodexCallIntent, policy: PolicyDecision) -> bool:
    policy_snapshots = tuple(policy.workspace_policy_snapshots)
    policy_workspace_ids = tuple(workspace_id for workspace_id, _ in policy_snapshots)
    binding_map = {
        binding.workspace_id: binding.policy_version_id
        for binding in intent.workspace_policy_bindings
    }
    return (
        policy.installation_policy_version_id == intent.installation_policy_version_id
        and len(set(policy_workspace_ids)) == len(policy_workspace_ids)
        and dict(policy_snapshots) == binding_map
        and tuple(policy.workspace_policy_version_ids)
        == tuple(policy_version_id for _, policy_version_id in policy_snapshots)
    )


def _scope_matches(requested: tuple[UUID, ...], allowed: tuple[UUID, ...]) -> bool:
    return len(set(allowed)) == len(allowed) and set(requested) == set(allowed)


def _evidence_matches(intent: CodexCallIntent, approvals: tuple[EvidenceApproval, ...]) -> bool:
    approval_ids = tuple(approval.revision_id for approval in approvals)
    if len(set(approval_ids)) != len(approval_ids):
        return False
    if any(
        approval.classification
        not in {EvidenceClassification.PUBLIC, EvidenceClassification.SYNTHETIC}
        or not _valid_sha256(approval.content_sha256)
        or type(approval.approval_generation) is not int
        or approval.approval_generation <= 0
        for approval in approvals
    ):
        return False
    expected = {
        revision.revision_id: (revision.content_sha256, revision.approval_generation)
        for revision in intent.evidence_revisions
    }
    actual = {
        approval.revision_id: (approval.content_sha256, approval.approval_generation)
        for approval in approvals
    }
    return actual == expected


def _valid_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _valid_utc(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() == timedelta(0)


def _deny(code: CodexAuthorizationErrorCode) -> None:
    raise CodexAuthorizationError(code)
