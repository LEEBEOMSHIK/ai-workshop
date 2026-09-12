"""Explicit synthetic connectivity proof; passive lookup never creates consent."""

import asyncio
import json
import re
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal, Protocol
from uuid import UUID, uuid4

from ai_workshop.labs.rag.deployments.domain import ProviderKind
from ai_workshop.shared.errors import AppError

from .codex_authorization import CodexCallOperation, CodexCallStage, EvidenceClassification
from .codex_events import CodexEventResult, CodexTokenUsage
from .codex_prompt import CodexPromptEnvelope, build_codex_prompt
from .codex_request import CodexRequestContext
from .codex_runner_registry import CodexRunnerRegistry, ResolvedCodexRunner
from .codex_stream import CodexStreamResult
from .codex_wire import parse_codex_grounded_wire_v1
from .codex_workspace import CodexWorkspaceResult
from .domain import (
    CODEX_GENERATION_DISCLOSURE_VERSION,
    ContextualizationRequest,
    ConversationRole,
    ConversationTurn,
    GenerationProfile,
    GenerationRequest,
    GenerationStatus,
)
from .execution import GenerationProviderError, ProviderExecutionMetadata, ProviderHealthResult
from .structured_output import parse_contextualization_v1


def _metadata(condition: bool) -> None:
    if not condition:
        raise ValueError("codex_verification_metadata_invalid")


def _text(value: object, limit: int = 180) -> bool:
    return type(value) is str and 0 < len(value) <= limit and value.isprintable()


def _digest(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _timestamp(value: object) -> bool:
    return type(value) is datetime and value.utcoffset() is not None


def _observed(result: CodexWorkspaceResult) -> str | None:
    if (
        type(result) is CodexWorkspaceResult
        and type(result.stream) is CodexStreamResult
        and type(result.stream.events) is CodexEventResult
    ):
        value = result.stream.events.observed_model
        if value is not None and _text(value):
            return value
    return None


@dataclass(frozen=True, slots=True)
class CodexPromptSignature:
    control_ref: str
    control_version: int
    control_sha256: str
    task_ref: str
    task_version: int
    task_sha256: str
    schema_ref: str
    schema_version: int
    schema_sha256: str
    developer_sha256: str

    def __post_init__(self) -> None:
        _metadata(
            all(_text(value, 120) for value in (self.control_ref, self.task_ref, self.schema_ref))
        )
        _metadata(
            all(
                type(value) is int and 1 <= value <= 1_000_000
                for value in (self.control_version, self.task_version, self.schema_version)
            )
        )
        _metadata(
            all(
                _digest(value)
                for value in (
                    self.control_sha256,
                    self.task_sha256,
                    self.schema_sha256,
                    self.developer_sha256,
                )
            )
        )

    @classmethod
    def from_envelope(cls, envelope: CodexPromptEnvelope) -> "CodexPromptSignature":
        return cls(
            envelope.control_ref,
            envelope.control_version,
            envelope.control_sha256,
            envelope.task_ref,
            envelope.task_version,
            envelope.task_sha256,
            envelope.schema_ref,
            envelope.schema_version,
            envelope.schema_sha256,
            sha256(envelope.developer_instructions.encode("utf-8")).hexdigest(),
        )


@dataclass(frozen=True, slots=True)
class CodexVerificationConfiguration:
    configuration_version_id: UUID
    workspace_ids: tuple[UUID, ...]
    profile: GenerationProfile
    profile_sha256: str


@dataclass(frozen=True, slots=True)
class CodexVerificationBinding:
    configuration_version_id: UUID
    generation_profile_id: UUID
    deployment_version_id: UUID
    profile_sha256: str
    runner_ref: str
    configuration_sha256: str
    cli_version: str
    executable_sha256: str
    requested_provider_model_id: str
    context_prompt: CodexPromptSignature
    answer_prompt: CodexPromptSignature

    def __post_init__(self) -> None:
        _metadata(
            all(
                type(value) is UUID
                for value in (
                    self.configuration_version_id,
                    self.generation_profile_id,
                    self.deployment_version_id,
                )
            )
        )
        _metadata(
            all(
                _digest(value)
                for value in (
                    self.profile_sha256,
                    self.configuration_sha256,
                    self.executable_sha256,
                )
            )
        )
        _metadata(
            _text(self.runner_ref, 120)
            and _text(self.cli_version, 80)
            and _text(self.requested_provider_model_id)
        )
        _metadata(
            type(self.context_prompt) is CodexPromptSignature
            and type(self.answer_prompt) is CodexPromptSignature
        )


@dataclass(frozen=True, slots=True)
class CodexVerificationAttempt:
    id: UUID
    configuration_version_id: UUID
    generation_profile_id: UUID
    deployment_version_id: UUID
    binding: CodexVerificationBinding | None
    checked_by: UUID
    checked_at: datetime
    success: bool
    safe_error_code: str | None
    requested_provider_model_id: str
    observed_provider_model_id: str | None
    usage_present: bool

    def __post_init__(self) -> None:
        _metadata(
            all(
                type(value) is UUID
                for value in (
                    self.id,
                    self.checked_by,
                    self.configuration_version_id,
                    self.generation_profile_id,
                    self.deployment_version_id,
                )
            )
        )
        _metadata(
            _timestamp(self.checked_at)
            and type(self.success) is bool
            and type(self.usage_present) is bool
        )
        _metadata(
            _text(self.requested_provider_model_id)
            and (self.observed_provider_model_id is None or _text(self.observed_provider_model_id))
        )
        _metadata(
            self.safe_error_code
            in {
                None,
                "codex_verification_failed",
                "codex_verification_cancelled",
                "codex_verification_model_mismatch",
            }
        )
        _metadata(self.binding is None or type(self.binding) is CodexVerificationBinding)
        if self.binding is not None:
            _metadata(
                (
                    self.configuration_version_id,
                    self.generation_profile_id,
                    self.deployment_version_id,
                    self.requested_provider_model_id,
                )
                == (
                    self.binding.configuration_version_id,
                    self.binding.generation_profile_id,
                    self.binding.deployment_version_id,
                    self.binding.requested_provider_model_id,
                )
            )
        _metadata(
            (
                self.success
                and self.binding is not None
                and self.usage_present
                and self.safe_error_code is None
            )
            or (not self.success and self.safe_error_code is not None)
        )


@dataclass(frozen=True, slots=True)
class CodexVerificationStatus:
    ready: bool
    safe_error_code: str | None
    requested_provider_model_id: str
    observed_provider_model_id: str | None
    model_identity_status: Literal["unknown", "verified", "mismatch"]
    checked_at: datetime | None


class CodexVerificationLookup(Protocol):
    async def load(
        self, *, actor_id: UUID, configuration_version_id: UUID
    ) -> CodexVerificationConfiguration | None: ...


class CodexVerificationProofs(Protocol):
    async def append_attempt(self, attempt: CodexVerificationAttempt) -> None: ...
    async def latest_attempt(
        self, configuration_version_id: UUID
    ) -> CodexVerificationAttempt | None: ...


class CodexVerificationExecutor(Protocol):
    async def execute(
        self, context: CodexRequestContext, *, request: ContextualizationRequest | GenerationRequest
    ) -> CodexWorkspaceResult: ...


@dataclass(frozen=True, slots=True)
class CodexStageAudit:
    id: UUID
    actor_id: UUID
    request_id: UUID
    configuration_version_id: UUID
    generation_profile_id: UUID
    deployment_version_id: UUID
    stage: CodexCallStage
    prompt: CodexPromptSignature
    payload_sha256: str
    runner_ref: str
    configuration_sha256: str
    cli_version: str
    executable_sha256: str
    requested_provider_model_id: str
    observed_provider_model_id: str | None
    outcome: Literal["completed", "failed", "cancelled"]
    safe_error_code: str | None
    latency_ms: int
    usage: CodexTokenUsage | None
    process_termination_verified: bool
    cleanup_verified: bool
    workspace_basename: str | None
    created_at: datetime
    correlation_id: UUID | None = None

    def __post_init__(self) -> None:
        _metadata(self.correlation_id is None or type(self.correlation_id) is UUID)
        _metadata(
            all(
                type(value) is UUID
                for value in (
                    self.id,
                    self.actor_id,
                    self.request_id,
                    self.configuration_version_id,
                    self.generation_profile_id,
                    self.deployment_version_id,
                )
            )
        )
        _metadata(type(self.stage) is CodexCallStage and type(self.prompt) is CodexPromptSignature)
        _metadata(
            all(
                _digest(value)
                for value in (
                    self.payload_sha256,
                    self.configuration_sha256,
                    self.executable_sha256,
                )
            )
        )
        _metadata(
            _text(self.runner_ref, 120)
            and _text(self.cli_version, 80)
            and _text(self.requested_provider_model_id)
            and (self.observed_provider_model_id is None or _text(self.observed_provider_model_id))
        )
        _metadata(
            self.outcome in {"completed", "failed", "cancelled"}
            and self.safe_error_code
            in {
                None,
                "codex_stage_failed",
                "codex_stage_cancelled",
                "codex_stage_model_mismatch",
                "codex_stage_schema_invalid",
            }
        )
        _metadata(
            type(self.latency_ms) is int
            and 0 <= self.latency_ms <= 2**63 - 1
            and type(self.process_termination_verified) is bool
            and type(self.cleanup_verified) is bool
            and _timestamp(self.created_at)
        )
        _metadata(
            self.workspace_basename is None
            or (
                type(self.workspace_basename) is str
                and re.fullmatch(r"request-[0-9a-f]{32}", self.workspace_basename) is not None
            )
        )
        _metadata(self.usage is None or type(self.usage) is CodexTokenUsage)
        if self.usage is not None:
            _metadata(
                all(
                    type(value) is int and 0 <= value <= 2**63 - 1
                    for value in (
                        self.usage.input_tokens,
                        self.usage.cached_input_tokens,
                        self.usage.output_tokens,
                    )
                )
            )
            _metadata(
                all(
                    value is None or (type(value) is int and 0 <= value <= 2**63 - 1)
                    for value in (
                        self.usage.reasoning_output_tokens,
                        self.usage.cache_write_input_tokens,
                    )
                )
            )


class CodexStageAuditPort(Protocol):
    async def append_stage(self, record: CodexStageAudit) -> None: ...


def stage_audit_record(
    *,
    context: CodexRequestContext,
    request: ContextualizationRequest | GenerationRequest,
    envelope: CodexPromptEnvelope,
    runner: ResolvedCodexRunner,
    payload_sha256: str,
    result: CodexWorkspaceResult | None,
    termination_verified: bool,
    cancelled: bool,
    latency_ms: int,
    created_at: datetime,
    correlation_id: UUID | None = None,
) -> CodexStageAudit:
    profile = request.profile
    deployment = profile.deployment
    if deployment is None:
        raise ValueError("codex_stage_audit_invalid")
    stage = (
        CodexCallStage.GENERATE
        if isinstance(request, GenerationRequest)
        else CodexCallStage.CONTEXTUALIZE
    )
    outcome: Literal["completed", "failed", "cancelled"] = "failed"
    code: str | None = "codex_stage_failed"
    usage = None
    observed = None
    try:
        if result is not None:
            events = _completed_events(result)
            observed = _observed(result)
            usage = _validated_usage(events, profile)
            if events.observed_model is not None and events.observed_model != profile.runtime_model:
                code = "codex_stage_model_mismatch"
                raise ValueError("codex_stage_model_mismatch")
            code = "codex_stage_schema_invalid"
            if isinstance(request, GenerationRequest):
                parse_codex_grounded_wire_v1(
                    events.final_text,
                    allowed_evidence_ids={item.evidence_id for item in request.evidence},
                )
            else:
                strict_context_query(events.final_text)
            outcome, code = "completed", None
    except Exception:
        pass
    if cancelled:
        outcome, code = "cancelled", "codex_stage_cancelled"
    workspace = result.workspace_id if result is not None else None
    if type(workspace) is not str or re.fullmatch(r"request-[0-9a-f]{32}", workspace) is None:
        workspace = None
    return CodexStageAudit(
        uuid4(),
        context.actor_id,
        context.request_id,
        context.configuration_version_id,
        profile.profile_id,
        deployment.id,
        stage,
        CodexPromptSignature.from_envelope(envelope),
        payload_sha256,
        runner.reference,
        runner.configuration_sha256,
        runner.expected_cli_version,
        runner.executable_sha256,
        profile.runtime_model,
        observed,
        outcome,
        code,
        latency_ms,
        usage,
        termination_verified,
        result is not None and result.cleanup_verified is True,
        workspace,
        created_at,
        correlation_id,
    )


def verification_binding(
    configuration: CodexVerificationConfiguration,
    runner: ResolvedCodexRunner,
) -> CodexVerificationBinding:
    profile = configuration.profile
    deployment = profile.deployment
    if (
        deployment is None
        or deployment.provider is not ProviderKind.DEVELOPMENT_CODEX_EXEC
        or not deployment.development_only
        or deployment.runner_ref != runner.reference
        or profile.prompt_ref != "rag-codex-answer-v3"
        or profile.runtime_model != deployment.provider_model_id
    ):
        raise ValueError("codex_verification_configuration_invalid")
    return CodexVerificationBinding(
        configuration.configuration_version_id,
        profile.profile_id,
        deployment.id,
        configuration.profile_sha256,
        runner.reference,
        runner.configuration_sha256,
        runner.expected_cli_version,
        runner.executable_sha256,
        deployment.provider_model_id,
        CodexPromptSignature.from_envelope(
            build_codex_prompt(ContextualizationRequest("", (), profile))
        ),
        CodexPromptSignature.from_envelope(
            build_codex_prompt(GenerationRequest("", "", (), (), profile, ""))
        ),
    )


def strict_stage_events(
    result: CodexWorkspaceResult, profile: GenerationProfile
) -> CodexEventResult:
    """Same strict stream/usage/identity guarantees for explicit verification and audit."""
    events = _completed_events(result)
    _validated_usage(events, profile)
    if events.observed_model is not None and events.observed_model != profile.runtime_model:
        raise ValueError("codex_verification_model_mismatch")
    return events


def _completed_events(result: CodexWorkspaceResult) -> CodexEventResult:
    if (
        type(result) is not CodexWorkspaceResult
        or result.failure is not None
        or result.cleanup_verified is not True
        or result.process_termination_verified is not True
    ):
        raise ValueError("codex_verification_cleanup_failed")
    stream = result.stream
    if (
        type(stream) is not CodexStreamResult
        or stream.cleanup_verified is not True
        or type(stream.active_processes_after_cleanup) is not int
        or stream.active_processes_after_cleanup != 0
        or stream.process_failure is not None
        or stream.event_failure is not None
        or type(stream.events) is not CodexEventResult
    ):
        raise ValueError("codex_verification_stream_failed")
    return stream.events


def _validated_usage(events: CodexEventResult, profile: GenerationProfile) -> CodexTokenUsage:
    usage = events.usage
    if (
        type(usage) is not CodexTokenUsage
        or any(
            type(value) is not int or value < 0
            for value in (usage.input_tokens, usage.cached_input_tokens, usage.output_tokens)
        )
        or any(
            value is not None and (type(value) is not int or value < 0)
            for value in (usage.reasoning_output_tokens, usage.cache_write_input_tokens)
        )
        or usage.cached_input_tokens > usage.input_tokens
        or (
            usage.reasoning_output_tokens is not None
            and usage.reasoning_output_tokens > usage.output_tokens
        )
        or usage.output_tokens > profile.max_output_tokens
    ):
        raise ValueError("codex_verification_usage_invalid")
    return usage


def strict_context_query(content: str) -> str:
    def reject_constant(value: str) -> object:
        raise ValueError("codex_verification_schema_invalid")

    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("codex_verification_schema_invalid")
            result[key] = value
        return result

    json.loads(content, object_pairs_hook=unique, parse_constant=reject_constant)
    return parse_contextualization_v1(content)


class CodexVerificationService:
    def __init__(
        self,
        *,
        lookup: CodexVerificationLookup,
        proofs: CodexVerificationProofs,
        registry: CodexRunnerRegistry,
        executor: CodexVerificationExecutor | None,
        environment: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._lookup, self._proofs, self._registry = lookup, proofs, registry
        self._executor, self._environment, self._clock = executor, environment, clock

    async def _load(
        self, actor_id: UUID, configuration_version_id: UUID
    ) -> CodexVerificationConfiguration:
        if self._environment not in {"local", "test"}:
            raise AppError(
                "codex_environment_forbidden", "Codex requires development environment.", 403
            )
        configuration = await self._lookup.load(
            actor_id=actor_id, configuration_version_id=configuration_version_id
        )
        if configuration is None:
            raise AppError("not_found", "The requested resource was not found.", 404)
        return configuration

    def _binding(self, configuration: CodexVerificationConfiguration) -> CodexVerificationBinding:
        deployment = configuration.profile.deployment
        if deployment is None or deployment.runner_ref is None:
            raise ValueError("codex_verification_configuration_invalid")
        return verification_binding(configuration, self._registry.resolve(deployment.runner_ref))

    async def status(
        self, *, actor_id: UUID, configuration_version_id: UUID
    ) -> CodexVerificationStatus:
        configuration = await self._load(actor_id, configuration_version_id)
        attempt = await self._proofs.latest_attempt(configuration_version_id)
        binding = None
        with suppress(Exception):
            binding = self._binding(configuration)
        ready = bool(
            binding is not None
            and attempt is not None
            and attempt.success is True
            and attempt.safe_error_code is None
            and attempt.usage_present is True
            and attempt.binding == binding
            and attempt.checked_at <= self._clock()
            and attempt.observed_provider_model_id in (None, binding.requested_provider_model_id)
        )
        observed = attempt.observed_provider_model_id if attempt is not None else None
        identity: Literal["unknown", "verified", "mismatch"] = (
            "unknown"
            if observed is None
            else "verified"
            if observed == configuration.profile.runtime_model
            else "mismatch"
        )
        return CodexVerificationStatus(
            ready,
            None
            if ready
            else (
                attempt.safe_error_code
                if attempt is not None and attempt.safe_error_code is not None
                else "codex_verification_required"
            ),
            configuration.profile.runtime_model,
            observed,
            identity,
            attempt.checked_at if attempt is not None else None,
        )

    async def health(
        self, *, context: CodexRequestContext, profile: GenerationProfile
    ) -> ProviderHealthResult:
        ready = False
        observed = None
        try:
            configuration = await self._load(context.actor_id, context.configuration_version_id)
            if configuration.profile == profile:
                status = await self.status(
                    actor_id=context.actor_id,
                    configuration_version_id=context.configuration_version_id,
                )
                ready, observed = status.ready, status.observed_provider_model_id
        except Exception:
            pass
        deployment = profile.deployment
        if deployment is None:
            raise GenerationProviderError("deployment_not_ready", retryable=False)
        return ProviderHealthResult(
            ready,
            observed,
            ProviderExecutionMetadata(
                ProviderKind.DEVELOPMENT_CODEX_EXEC,
                profile.runtime_model,
                deployment.id,
                None,
                None,
                0,
            ),
        )

    async def verify(
        self,
        *,
        actor_id: UUID,
        configuration_version_id: UUID,
        consented: bool,
        disclosure_version: str,
    ) -> CodexVerificationStatus:
        if consented is not True or disclosure_version != CODEX_GENERATION_DISCLOSURE_VERSION:
            raise AppError(
                "codex_consent_required", "Exact Codex disclosure consent is required.", 422
            )
        configuration = await self._load(actor_id, configuration_version_id)
        profile = configuration.profile
        deployment = profile.deployment
        if deployment is None:
            raise AppError(
                "codex_verification_configuration_invalid", "Codex configuration is invalid.", 422
            )
        context = CodexRequestContext(
            actor_id,
            uuid4(),
            CodexCallOperation.CONNECTION_CHECK,
            configuration_version_id,
            configuration.workspace_ids,
            EvidenceClassification.SYNTHETIC,
            True,
            disclosure_version,
        )
        binding = None
        code: str | None = "codex_verification_failed"
        observed = None
        usage_present = False
        cancelled = False
        try:
            binding = self._binding(configuration)
            if self._executor is None:
                raise ValueError("codex_verification_executor_unavailable")
            history = (
                ConversationTurn(ConversationRole.USER, "Synthetic connectivity check only."),
            )
            first = await self._executor.execute(
                context,
                request=ContextualizationRequest(
                    "Rewrite this synthetic connection question without adding facts.",
                    history,
                    profile,
                ),
            )
            observed = _observed(first)
            contextual = strict_stage_events(first, profile)
            query = strict_context_query(contextual.final_text)
            second = await self._executor.execute(
                context,
                request=GenerationRequest(
                    "Synthetic connectivity check. No evidence is supplied.",
                    query,
                    history,
                    (),
                    profile,
                    str(context.request_id),
                ),
            )
            observed = _observed(second)
            generated = strict_stage_events(second, profile)
            parsed = parse_codex_grounded_wire_v1(generated.final_text, allowed_evidence_ids=())
            if parsed.status is not GenerationStatus.INSUFFICIENT_EVIDENCE:
                raise ValueError("codex_verification_schema_invalid")
            if contextual.observed_model != generated.observed_model:
                raise ValueError("codex_verification_model_mismatch")
            observed = generated.observed_model
            usage_present = True
            if self._binding(configuration) != binding:
                raise ValueError("codex_verification_stale")
            code = None
        except asyncio.CancelledError:
            cancelled = True
            code = "codex_verification_cancelled"
        except ValueError as error:
            if str(error) == "codex_verification_model_mismatch":
                code = "codex_verification_model_mismatch"
        except Exception:
            pass
        attempt = CodexVerificationAttempt(
            uuid4(),
            configuration_version_id,
            profile.profile_id,
            deployment.id,
            binding,
            actor_id,
            self._clock(),
            code is None,
            code,
            profile.runtime_model,
            observed,
            usage_present,
        )
        commit = asyncio.create_task(self._proofs.append_attempt(attempt))
        while not commit.done():
            try:
                await asyncio.shield(commit)
            except asyncio.CancelledError:
                cancelled = True
        commit.result()
        if cancelled:
            raise asyncio.CancelledError
        return await self.status(
            actor_id=actor_id, configuration_version_id=configuration_version_id
        )
