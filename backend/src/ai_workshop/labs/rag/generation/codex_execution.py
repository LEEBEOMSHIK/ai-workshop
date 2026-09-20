"""Request-owned Codex lifecycle; caller cancellation never abandons its worker.

Only the workspace runs in a thread. Approval issuance, gate/consume, gate exit
and durable lease finalization belong to one shielded async task. No readiness
bypass is supplied here: connection checks use the same authorization boundary.
"""

import asyncio
import threading
from collections.abc import Callable
from contextlib import suppress
from dataclasses import replace
from datetime import datetime, timedelta
from math import isfinite
from time import monotonic
from typing import Protocol
from uuid import UUID

from ai_workshop.labs.rag.deployments.domain import ModelDeploymentVersion, ProviderKind

from .codex_authorization import (
    CodexAuthorizationError,
    CodexAuthorizationErrorCode,
    CodexAuthorizationSource,
    CodexCallIntent,
    CodexCallStage,
    CodexExecutionGate,
    CodexExecutionPayload,
)
from .codex_prompt import build_codex_prompt
from .codex_request import CodexRequestContext
from .codex_runner_registry import CodexRunnerRegistry
from .codex_slots import CodexExecutionSlots, CodexSlotError
from .codex_verification import CodexStageAuditPort, stage_audit_record
from .codex_workspace import CodexWorkspaceExecutor, CodexWorkspaceResult
from .domain import ContextualizationRequest, GenerationProfile, GenerationRequest
from .execution import GenerationProviderError


class CodexRequestAuthorizationSource(CodexAuthorizationSource, Protocol):
    async def issue_request(
        self,
        context: CodexRequestContext,
        *,
        stage: CodexCallStage,
        payload: CodexExecutionPayload,
        evidence_revision_ids: tuple[UUID, ...],
        ttl: timedelta,
    ) -> CodexCallIntent: ...


def _codex_deployment(profile: GenerationProfile) -> ModelDeploymentVersion:
    deployment = profile.deployment
    if (
        type(profile) is not GenerationProfile
        or deployment is None
        or deployment.provider is not ProviderKind.DEVELOPMENT_CODEX_EXEC
        or not deployment.development_only
        or deployment.runner_ref is None
        or profile.runtime_model != deployment.provider_model_id
        or profile.model_id != deployment.model_definition_id
        or profile.prompt_ref not in {"rag-codex-answer-v3", "rag-codex-answer-v4"}
        or (profile.prompt_ref == "rag-codex-answer-v4" and profile.evidence_budget is None)
        or profile.context_prompt_ref != "rag-codex-contextualize-v1"
        or type(profile.response_schema_version) is not int
        or profile.response_schema_version != 2
        or type(profile.max_output_tokens) is not int
        or profile.max_output_tokens <= 0
        or type(profile.timeout_seconds) not in (float, int)
        or not isfinite(profile.timeout_seconds)
        or profile.timeout_seconds <= 0
        or type(deployment.timeout_seconds) not in (float, int)
        or not isfinite(deployment.timeout_seconds)
        or deployment.timeout_seconds <= 0
    ):
        raise GenerationProviderError("codex_request_invalid", retryable=False)
    return deployment


class CodexRequestExecutor:
    def __init__(
        self,
        *,
        registry: CodexRunnerRegistry,
        source: CodexRequestAuthorizationSource,
        slots: CodexExecutionSlots,
        workspace: CodexWorkspaceExecutor,
        clock: Callable[[], datetime],
        audit: CodexStageAuditPort | None = None,
        correlation_id: UUID | None = None,
    ) -> None:
        self._registry = registry
        self._source = source
        self._slots = slots
        self._workspace = workspace
        self._gate = CodexExecutionGate(source=source, clock=clock)
        self._audit, self._clock = audit, clock
        if correlation_id is not None and type(correlation_id) is not UUID:
            raise GenerationProviderError("codex_request_invalid", retryable=False)
        self._correlation_id = correlation_id

    async def execute(
        self,
        context: CodexRequestContext,
        *,
        request: ContextualizationRequest | GenerationRequest,
    ) -> CodexWorkspaceResult:
        if self._audit is None:
            raise GenerationProviderError("codex_audit_required", retryable=False)
        cancellation = threading.Event()
        owned = asyncio.create_task(self._safe_owned(context, request, cancellation))
        interrupted = False
        while not owned.done():
            try:
                await asyncio.shield(owned)
            except asyncio.CancelledError:
                interrupted = True
                cancellation.set()
            except Exception:
                # Retrieve the sanitized owned result below, outside exception context.
                break
        if interrupted:
            with suppress(BaseException):
                owned.result()
            raise asyncio.CancelledError
        return owned.result()

    async def _safe_owned(
        self,
        context: CodexRequestContext,
        request: ContextualizationRequest | GenerationRequest,
        cancellation: threading.Event,
    ) -> CodexWorkspaceResult:
        code = "codex_execution_failed"
        try:
            return await self._owned(context, request, cancellation)
        except CodexAuthorizationError as error:
            if type(error.code) is CodexAuthorizationErrorCode:
                code = "codex_authorization_" + error.code.value
        except CodexSlotError as error:
            if error.code in {
                "codex_slot_invalid_input",
                "codex_slot_settings_mismatch",
                "codex_slot_lease_mismatch",
                "codex_slot_source_unavailable",
            }:
                code = error.code
        except GenerationProviderError as error:
            if error.code in {
                "codex_request_invalid",
                "codex_capacity_exhausted",
                "codex_binding_mismatch",
            }:
                code = error.code
        except Exception:
            pass
        raise GenerationProviderError(code, retryable=False)

    async def _owned(
        self,
        context: CodexRequestContext,
        request: ContextualizationRequest | GenerationRequest,
        cancellation: threading.Event,
    ) -> CodexWorkspaceResult:
        if type(context) is not CodexRequestContext or type(request) not in (
            ContextualizationRequest,
            GenerationRequest,
        ):
            raise GenerationProviderError("codex_request_invalid", retryable=False)
        context = replace(context)
        deployment = _codex_deployment(request.profile)
        assert deployment.runner_ref is not None
        runner = self._registry.resolve(deployment.runner_ref)
        timeout = min(
            request.profile.timeout_seconds,
            deployment.timeout_seconds,
            runner.process_limits.timeout_seconds,
        )
        output_limit = min(request.profile.max_output_tokens, runner.event_limits.max_output_tokens)
        envelope = build_codex_prompt(request)
        payload = CodexExecutionPayload(
            stdin=envelope.stdin_json.encode("utf-8"),
            developer_instructions=envelope.developer_instructions.encode("utf-8"),
            output_schema=envelope.output_schema_json.encode("utf-8"),
        )
        stage = (
            CodexCallStage.GENERATE
            if type(request) is GenerationRequest
            else CodexCallStage.CONTEXTUALIZE
        )
        revisions = (
            tuple(sorted({item.asset_version_id for item in request.evidence}))
            if isinstance(request, GenerationRequest)
            else ()
        )
        started = monotonic()
        lease = await self._slots.acquire(
            runner_ref=deployment.runner_ref,
            configuration_sha256=runner.configuration_sha256,
            max_concurrent=runner.max_concurrent_requests,
            request_id=context.request_id,
        )
        if lease is None:
            if self._audit is not None:
                await self._audit.append_stage(
                    stage_audit_record(
                        context=context,
                        request=request,
                        envelope=envelope,
                        runner=runner,
                        payload_sha256=payload.digest(),
                        result=None,
                        termination_verified=True,
                        cancelled=cancellation.is_set(),
                        latency_ms=max(0, int((monotonic() - started) * 1000)),
                        created_at=self._clock(),
                        correlation_id=self._correlation_id,
                    )
                )
            raise GenerationProviderError("codex_capacity_exhausted", retryable=False)
        termination_verified = True
        outcome_result: CodexWorkspaceResult | None = None
        try:
            if cancellation.is_set():
                outcome_result = CodexWorkspaceResult(
                    failure="codex_workspace_cancelled", process_termination_verified=True
                )
                return outcome_result
            intent = await self._source.issue_request(
                context,
                stage=stage,
                payload=payload,
                evidence_revision_ids=revisions,
                ttl=timedelta(minutes=5),
            )
            if (
                intent.runner_configuration_sha256 != runner.configuration_sha256
                or intent.runner_ref != deployment.runner_ref
                or intent.deployment_version_id != deployment.id
                or intent.generation_profile_id != request.profile.profile_id
                or intent.provider_model_id != request.profile.runtime_model
            ):
                raise GenerationProviderError("codex_binding_mismatch", retryable=False)

            async def worker(sent: CodexExecutionPayload) -> CodexWorkspaceResult:
                nonlocal termination_verified
                if cancellation.is_set():
                    return CodexWorkspaceResult(
                        failure="codex_workspace_cancelled", process_termination_verified=True
                    )
                termination_verified = False
                result = await asyncio.to_thread(
                    self._workspace.run,
                    intent=intent,
                    payload=sent,
                    expected_configuration_sha256=intent.runner_configuration_sha256,
                    timeout_seconds=timeout,
                    max_output_tokens=output_limit,
                    cancellation=cancellation,
                )
                if type(result) is not CodexWorkspaceResult:
                    raise GenerationProviderError("codex_execution_failed", retryable=False)
                termination_verified = result.process_termination_verified is True
                return result

            outcome_result = await self._gate.run(intent, payload, worker)
            return outcome_result
        finally:
            try:
                if self._audit is not None:
                    await self._audit.append_stage(
                        stage_audit_record(
                            context=context,
                            request=request,
                            envelope=envelope,
                            runner=runner,
                            payload_sha256=payload.digest(),
                            result=outcome_result,
                            termination_verified=termination_verified,
                            cancelled=cancellation.is_set(),
                            latency_ms=max(0, int((monotonic() - started) * 1000)),
                            created_at=self._clock(),
                            correlation_id=self._correlation_id,
                        )
                    )
            finally:
                await self._slots.complete(lease, process_termination_verified=termination_verified)
