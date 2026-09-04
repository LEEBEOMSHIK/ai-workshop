from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from time import perf_counter
from typing import TYPE_CHECKING, Protocol
from uuid import UUID, uuid4

from ai_workshop.labs.rag.deployments.domain import (
    DeploymentCapability,
    ExecutionLocation,
    ModelDeploymentVersion,
)
from ai_workshop.labs.rag.embeddings.contracts import EmbeddingRuntimeUnavailableError
from ai_workshop.labs.rag.generation.audit import (
    GenerationExecutionAudit,
    WorkspacePolicyAuditSnapshot,
)
from ai_workshop.labs.rag.generation.citation_validation import CitationValidator
from ai_workshop.labs.rag.generation.contracts import (
    GenerationRuntimePort,
    GenerationRuntimeResponseError,
    GenerationRuntimeUnavailableError,
)
from ai_workshop.labs.rag.generation.domain import (
    ContextualizationRequest,
    ConversationRole,
    ConversationTurn,
    GenerationExecutionSnapshot,
    GenerationOutcome,
    GenerationProfile,
    GenerationRequest,
    GenerationStatus,
    GroundingEvidence,
    generation_execution_snapshot,
)
from ai_workshop.labs.rag.generation.execution import (
    GenerationProviderError,
    ProviderExecutionMetadata,
    ResolvedGenerationRuntime,
)
from ai_workshop.labs.rag.generation.integrity import ConversationTurnSigner
from ai_workshop.labs.rag.generation.prompts import (
    PromptNotFoundError,
    prompt_reference_version,
)
from ai_workshop.labs.rag.highlighting.domain import (
    EvidenceSelection,
    EvidenceSource,
)
from ai_workshop.labs.rag.highlighting.service import EvidenceSelector
from ai_workshop.labs.rag.policies.domain import PolicyDecision
from ai_workshop.labs.rag.retrieval.domain import FusedHit, ResolvedSearchScope
from ai_workshop.labs.rag.retrieval.service import (
    DenseRetrieverPort,
    HybridRetrievalService,
    SearchScopeResolverPort,
    SparseRetrieverPort,
)
from ai_workshop.labs.rag.search.configuration_port import (
    ResolvedExternalApproval,
    ResolvedSearchConfiguration,
    SearchConfigurationResolverPort,
)
from ai_workshop.shared.errors import AppError
from ai_workshop.shared.request_context import correlation_id_context

if TYPE_CHECKING:
    from ai_workshop.labs.rag.search.schemas import SearchRequest


class GenerationPolicyResolverPort(Protocol):
    async def resolve(
        self,
        *,
        deployment: ModelDeploymentVersion,
        workspace_ids: tuple[UUID, ...],
    ) -> PolicyDecision: ...


class GenerationRuntimeResolverPort(Protocol):
    def resolve(
        self,
        deployment: ModelDeploymentVersion,
        policy: PolicyDecision,
    ) -> ResolvedGenerationRuntime: ...


class GenerationAuditRepositoryPort(Protocol):
    async def add(self, audit: GenerationExecutionAudit) -> GenerationExecutionAudit: ...

    async def commit(self) -> None: ...


@dataclass(frozen=True, slots=True)
class PreparedGeneration:
    runtime: GenerationRuntimePort
    policy: PolicyDecision
    execution: GenerationExecutionSnapshot


class SearchSourceResolverPort(Protocol):
    async def resolve(
        self,
        *,
        actor_id: UUID,
        indexing_profile_id: UUID,
        hits: tuple[FusedHit, ...],
    ) -> tuple[EvidenceSource, ...]: ...


@dataclass(frozen=True, slots=True)
class RelatedSource:
    source: EvidenceSource


@dataclass(frozen=True, slots=True)
class SearchResult:
    selection: EvidenceSelection
    configuration: ResolvedSearchConfiguration
    related_sources: tuple[RelatedSource, ...]
    retrieved_evidence_ids: tuple[UUID, ...] = ()
    resolved_query: str = ""
    generation: GenerationOutcome = GenerationOutcome(
        status=GenerationStatus.NOT_REQUESTED
    )


class SearchApplicationService:
    def __init__(
        self,
        *,
        configuration_resolver: SearchConfigurationResolverPort,
        scope_resolver: SearchScopeResolverPort,
        sparse_retriever: SparseRetrieverPort,
        dense_retriever: DenseRetrieverPort,
        source_resolver: SearchSourceResolverPort,
        turn_signer: ConversationTurnSigner | None = None,
        generation_policy_resolver: GenerationPolicyResolverPort | None = None,
        generation_runtime_resolver: GenerationRuntimeResolverPort | None = None,
        generation_audit_repository: GenerationAuditRepositoryPort | None = None,
    ) -> None:
        self.configuration_resolver = configuration_resolver
        self.scope_resolver = scope_resolver
        self.sparse_retriever = sparse_retriever
        self.dense_retriever = dense_retriever
        self.source_resolver = source_resolver
        self.turn_signer = turn_signer
        self.generation_policy_resolver = generation_policy_resolver
        self.generation_runtime_resolver = generation_runtime_resolver
        self.generation_audit_repository = generation_audit_repository

    async def search(self, *, actor_id: UUID, request: SearchRequest) -> SearchResult:
        configuration = await self.configuration_resolver.resolve(
            request.configuration_id,
            actor_id,
        )
        return await self._search(actor_id=actor_id, request=request, configuration=configuration)

    async def search_exact(
        self,
        *,
        actor_id: UUID,
        configuration_version_id: UUID,
        request: SearchRequest,
    ) -> SearchResult:
        configuration = await self.configuration_resolver.resolve_version(
            configuration_version_id,
            actor_id,
        )
        if request.configuration_id != configuration.configuration_id:
            raise AppError("not_found", "The requested resource was not found.", 404)
        return await self._search(actor_id=actor_id, request=request, configuration=configuration)

    async def _search(
        self,
        *,
        actor_id: UUID,
        request: SearchRequest,
        configuration: ResolvedSearchConfiguration,
    ) -> SearchResult:
        if configuration.experimental and not request.experimental:
            raise AppError(
                "experimental_opt_in_required",
                "The selected configuration requires explicit experimental opt-in.",
                409,
            )
        policy = configuration.answer_policy
        if configuration.answer_policy_version_id is None or policy is None:
            raise AppError(
                "answer_policy_missing",
                "The selected search configuration has no answer policy version.",
                409,
            )
        requested_workspace_ids = tuple(dict.fromkeys(request.workspace_ids))
        requested_folder_ids = tuple(dict.fromkeys(request.folder_ids))
        if not set(requested_workspace_ids).issubset(configuration.workspace_ids):
            raise AppError("not_found", "The requested resource was not found.", 404)

        resolved_scope = await self.scope_resolver.resolve(
            actor_id=actor_id,
            workspace_ids=requested_workspace_ids,
            folder_ids=requested_folder_ids,
            indexing_profile_id=configuration.indexing_profile_id,
        )
        generation_profile = configuration.generation_profile
        history = self._validated_history(
            request=request,
            actor_id=actor_id,
            configuration=configuration,
        )
        bounded_history = history
        if generation_profile is not None:
            bounded_history = generation_profile.context_policy.select(
                history,
                token_counter=configuration.embedding.count_tokens,
            )
        prepared_generation = await self._prepare_generation(
            actor_id=actor_id,
            configuration=configuration,
            workspace_ids=tuple(dict.fromkeys(configuration.workspace_ids)),
            requires_contextualization=bool(bounded_history),
        )
        generation_runtime = (
            prepared_generation.runtime if prepared_generation is not None else None
        )
        if generation_profile is not None and self.turn_signer is None:
            await self._record_audit(
                actor_id=actor_id,
                configuration=configuration,
                policy=prepared_generation.policy if prepared_generation else None,
                evidence_ids=(),
                status="failed",
                safe_error_code="deployment_not_ready",
            )
            raise _safe_generation_error("deployment_not_ready")
        contextualization_execution: ProviderExecutionMetadata | None = None
        if generation_profile is not None:
            assert prepared_generation is not None
            assert generation_runtime is not None
            assert generation_profile.deployment is not None
            try:
                generation_health = await generation_runtime.health()
            except GenerationProviderError as exc:
                await self._record_audit(
                    actor_id=actor_id,
                    configuration=configuration,
                    policy=prepared_generation.policy,
                    evidence_ids=(),
                    status="failed",
                    safe_error_code=_approved_provider_code(exc.code),
                )
                raise _safe_generation_error(_approved_provider_code(exc.code)) from None
            except GenerationRuntimeUnavailableError:
                await self._record_audit(
                    actor_id=actor_id,
                    configuration=configuration,
                    policy=prepared_generation.policy,
                    evidence_ids=(),
                    status="failed",
                    safe_error_code="deployment_not_ready",
                )
                raise _safe_generation_error("deployment_not_ready") from None
            except GenerationRuntimeResponseError:
                await self._record_audit(
                    actor_id=actor_id,
                    configuration=configuration,
                    policy=prepared_generation.policy,
                    evidence_ids=(),
                    status="failed",
                    safe_error_code="provider_invalid_response",
                )
                raise _safe_generation_error("provider_invalid_response") from None
            generation_ready = generation_health.ready
            if not generation_ready:
                await self._record_audit(
                    actor_id=actor_id,
                    configuration=configuration,
                    policy=prepared_generation.policy,
                    evidence_ids=(),
                    status="failed",
                    safe_error_code="deployment_not_ready",
                    provider_execution=generation_health.execution,
                )
                raise _safe_generation_error("deployment_not_ready")
            if (
                not _execution_is_exact(
                    generation_health.execution,
                    generation_profile.deployment,
                )
                or generation_health.observed_provider_model_id
                != generation_profile.deployment.provider_model_id
            ):
                await self._record_audit(
                    actor_id=actor_id,
                    configuration=configuration,
                    policy=prepared_generation.policy,
                    evidence_ids=(),
                    status="failed",
                    safe_error_code="provider_invalid_response",
                    provider_execution=generation_health.execution,
                )
                raise _safe_generation_error("provider_invalid_response")
        resolved_query = request.query.strip()
        if generation_profile is not None and bounded_history:
            assert prepared_generation is not None
            assert generation_runtime is not None
            try:
                contextualization = await generation_runtime.contextualize(
                    ContextualizationRequest(
                        question=request.query.strip(),
                        history=bounded_history,
                        profile=generation_profile,
                    )
                )
                if not _execution_is_exact(
                    contextualization.execution,
                    generation_profile.deployment,
                ):
                    await self._record_audit(
                        actor_id=actor_id,
                        configuration=configuration,
                        policy=prepared_generation.policy,
                        evidence_ids=(),
                        status="failed",
                        safe_error_code="provider_invalid_response",
                    )
                    raise _safe_generation_error("provider_invalid_response")
                resolved_query = contextualization.resolved_query
                contextualization_execution = contextualization.execution
            except GenerationProviderError as exc:
                code = _approved_provider_code(exc.code)
                await self._record_audit(
                    actor_id=actor_id,
                    configuration=configuration,
                    policy=prepared_generation.policy,
                    evidence_ids=(),
                    status="failed",
                    safe_error_code=code,
                )
                raise _safe_generation_error(code) from None
            except GenerationRuntimeUnavailableError:
                await self._record_audit(
                    actor_id=actor_id,
                    configuration=configuration,
                    policy=prepared_generation.policy,
                    evidence_ids=(),
                    status="failed",
                    safe_error_code="deployment_not_ready",
                )
                raise _safe_generation_error("deployment_not_ready") from None
            except GenerationRuntimeResponseError:
                await self._record_audit(
                    actor_id=actor_id,
                    configuration=configuration,
                    policy=prepared_generation.policy,
                    evidence_ids=(),
                    status="failed",
                    safe_error_code="provider_invalid_response",
                )
                raise _safe_generation_error("provider_invalid_response") from None

        try:
            retrieval = HybridRetrievalService(
                scope_resolver=_ResolvedScopeResolver(resolved_scope),
                embedding=configuration.embedding,
                sparse_retriever=self.sparse_retriever,
                dense_retriever=self.dense_retriever,
            )
            hits = await retrieval.search(
                actor_id=actor_id,
                query=resolved_query,
                workspace_ids=requested_workspace_ids,
                folder_ids=requested_folder_ids,
                indexing_profile_id=configuration.indexing_profile_id,
                retrieval_profile=configuration.retrieval_profile,
                index_alias=configuration.active_index_alias,
                result_limit=request.top_k,
                query_max_tokens=configuration.query_max_tokens,
            )
            sources = await self.source_resolver.resolve(
                actor_id=actor_id,
                indexing_profile_id=configuration.indexing_profile_id,
                hits=hits,
            )
            selection = EvidenceSelector(configuration.embedding).select(
                query=resolved_query,
                sources=sources,
                policy=policy,
            )
        except EmbeddingRuntimeUnavailableError:
            error = AppError(
                "evidence_embedding_unavailable",
                "Evidence selection is temporarily unavailable.",
                503,
            )
            if contextualization_execution is not None:
                assert prepared_generation is not None
                await self._record_audit(
                    actor_id=actor_id,
                    configuration=configuration,
                    policy=prepared_generation.policy,
                    evidence_ids=(),
                    status="failed",
                    safe_error_code=error.code,
                    provider_execution=contextualization_execution,
                )
            raise error from None
        except AppError as exc:
            if contextualization_execution is not None:
                assert prepared_generation is not None
                await self._record_audit(
                    actor_id=actor_id,
                    configuration=configuration,
                    policy=prepared_generation.policy,
                    evidence_ids=(),
                    status="failed",
                    safe_error_code=_safe_search_audit_code(exc.code),
                    provider_execution=contextualization_execution,
                )
            raise
        generation = await self._generate(
            actor_id=actor_id,
            original_query=request.query.strip(),
            resolved_query=resolved_query,
            history=bounded_history,
            configuration=configuration,
            selection=selection,
            prepared_generation=prepared_generation,
            contextualization_execution=contextualization_execution,
        )
        return SearchResult(
            selection=selection,
            configuration=configuration,
            related_sources=_related_sources(sources, selection),
            retrieved_evidence_ids=tuple(
                evidence.id
                for source in sources
                for evidence in source.chunk.evidence_units
            ),
            resolved_query=resolved_query,
            generation=generation,
        )

    def _validated_history(
        self,
        *,
        request: SearchRequest,
        actor_id: UUID,
        configuration: ResolvedSearchConfiguration,
    ) -> tuple[ConversationTurn, ...]:
        history: list[ConversationTurn] = []
        for item in request.history:
            try:
                turn = ConversationTurn(
                    role=ConversationRole(item.role),
                    content=item.content,
                    turn_id=item.turn_id,
                    validation_token=item.validation_token,
                )
            except ValueError as exc:
                raise AppError(
                    "conversation_history_invalid",
                    "Conversation history is invalid.",
                    422,
                ) from exc
            if turn.role is ConversationRole.ASSISTANT:
                if self.turn_signer is None or not self.turn_signer.verify(
                    turn,
                    actor_id=actor_id,
                    configuration_version_id=configuration.configuration_version_id,
                ):
                    raise AppError(
                        "conversation_history_invalid",
                        "Conversation history is invalid.",
                        422,
                    )
            elif turn.turn_id is not None or turn.validation_token is not None:
                raise AppError(
                    "conversation_history_invalid",
                    "Conversation history is invalid.",
                    422,
                )
            history.append(turn)
        return tuple(history)

    async def _prepare_generation(
        self,
        *,
        actor_id: UUID,
        configuration: ResolvedSearchConfiguration,
        workspace_ids: tuple[UUID, ...],
        requires_contextualization: bool,
    ) -> PreparedGeneration | None:
        profile = configuration.generation_profile
        if profile is None:
            return None
        deployment = profile.deployment
        if (
            deployment is None
            or self.generation_policy_resolver is None
            or self.generation_audit_repository is None
        ):
            raise _safe_generation_error("deployment_not_ready")
        _validate_registered_prompts(profile)

        policy = await self.generation_policy_resolver.resolve(
            deployment=deployment,
            workspace_ids=workspace_ids,
        )
        if not policy.allowed:
            code = (
                policy.reason_code.value
                if policy.reason_code is not None
                else "provider_not_allowed"
            )
            await self._record_audit(
                actor_id=actor_id,
                configuration=configuration,
                policy=policy,
                evidence_ids=(),
                status="denied",
                safe_error_code=code,
            )
            raise _safe_generation_error(code)

        execution = generation_execution_snapshot(profile)
        if deployment.location is ExecutionLocation.EXTERNAL and not _approval_is_current(
            approval=configuration.external_approval,
            configuration=configuration,
            deployment=deployment,
            policy=policy,
            disclosure_version=execution.disclosure_version,
        ):
            await self._record_audit(
                actor_id=actor_id,
                configuration=configuration,
                policy=policy,
                evidence_ids=(),
                status="denied",
                safe_error_code="deployment_not_ready",
            )
            raise _safe_generation_error("deployment_not_ready")

        required_capabilities = {DeploymentCapability.STRUCTURED_OUTPUT}
        if requires_contextualization:
            required_capabilities.add(DeploymentCapability.CONTEXTUALIZATION)
        if not required_capabilities.issubset(deployment.capabilities):
            await self._record_audit(
                actor_id=actor_id,
                configuration=configuration,
                policy=policy,
                evidence_ids=(),
                status="failed",
                safe_error_code="deployment_not_ready",
            )
            raise _safe_generation_error("deployment_not_ready")

        if configuration.generation_runtime is not None:
            runtime = configuration.generation_runtime
        else:
            if self.generation_runtime_resolver is None:
                await self._record_audit(
                    actor_id=actor_id,
                    configuration=configuration,
                    policy=policy,
                    evidence_ids=(),
                    status="failed",
                    safe_error_code="deployment_not_ready",
                )
                raise _safe_generation_error("deployment_not_ready")
            try:
                resolved = self.generation_runtime_resolver.resolve(deployment, policy)
            except GenerationProviderError as exc:
                code = _approved_provider_code(exc.code)
                await self._record_audit(
                    actor_id=actor_id,
                    configuration=configuration,
                    policy=policy,
                    evidence_ids=(),
                    status="failed",
                    safe_error_code=code,
                )
                raise _safe_generation_error(code) from None
            runtime = resolved.adapter
        return PreparedGeneration(runtime=runtime, policy=policy, execution=execution)

    async def _generate(
        self,
        *,
        actor_id: UUID,
        original_query: str,
        resolved_query: str,
        history: tuple[ConversationTurn, ...],
        configuration: ResolvedSearchConfiguration,
        selection: EvidenceSelection,
        prepared_generation: PreparedGeneration | None,
        contextualization_execution: ProviderExecutionMetadata | None,
    ) -> GenerationOutcome:
        profile = configuration.generation_profile
        if profile is None:
            return GenerationOutcome(status=GenerationStatus.NOT_REQUESTED)
        assert prepared_generation is not None
        if selection.status.value == "insufficient_evidence":
            await self._record_audit(
                actor_id=actor_id,
                configuration=configuration,
                policy=prepared_generation.policy,
                evidence_ids=(),
                status="allowed",
                safe_error_code=None,
                provider_execution=contextualization_execution,
            )
            return GenerationOutcome(
                status=GenerationStatus.INSUFFICIENT_EVIDENCE,
                execution=prepared_generation.execution,
            )
        generation_runtime = prepared_generation.runtime
        assert self.turn_signer is not None
        evidence = _generation_evidence(selection)
        generation_started = perf_counter()
        try:
            generation_result = await generation_runtime.generate(
                GenerationRequest(
                    question=original_query,
                    resolved_query=resolved_query,
                    history=history,
                    evidence=evidence,
                    profile=profile,
                    correlation_id=correlation_id_context.get(),
                )
            )
            if not _execution_is_exact(
                generation_result.execution,
                profile.deployment,
            ):
                await self._record_audit(
                    actor_id=actor_id,
                    configuration=configuration,
                    policy=prepared_generation.policy,
                    evidence_ids=tuple(item.evidence_id for item in evidence),
                    status="failed",
                    safe_error_code="provider_invalid_response",
                    provider_execution=contextualization_execution,
                    latency_ms=_elapsed_ms(generation_started),
                )
                raise _safe_generation_error("provider_invalid_response")
            draft = generation_result.generation
        except GenerationProviderError as exc:
            code = _approved_provider_code(exc.code)
            await self._record_audit(
                actor_id=actor_id,
                configuration=configuration,
                policy=prepared_generation.policy,
                evidence_ids=tuple(item.evidence_id for item in evidence),
                status="failed",
                safe_error_code=code,
                provider_execution=contextualization_execution,
                latency_ms=_elapsed_ms(generation_started),
            )
            raise _safe_generation_error(code) from None
        except GenerationRuntimeUnavailableError:
            await self._record_audit(
                actor_id=actor_id,
                configuration=configuration,
                policy=prepared_generation.policy,
                evidence_ids=tuple(item.evidence_id for item in evidence),
                status="failed",
                safe_error_code="deployment_not_ready",
                provider_execution=contextualization_execution,
                latency_ms=_elapsed_ms(generation_started),
            )
            raise _safe_generation_error("deployment_not_ready") from None
        except GenerationRuntimeResponseError:
            await self._record_audit(
                actor_id=actor_id,
                configuration=configuration,
                policy=prepared_generation.policy,
                evidence_ids=tuple(item.evidence_id for item in evidence),
                status="failed",
                safe_error_code="provider_invalid_response",
                provider_execution=contextualization_execution,
                latency_ms=_elapsed_ms(generation_started),
            )
            raise _safe_generation_error("provider_invalid_response") from None
        outcome = CitationValidator().validate(draft, allowed_evidence=evidence)
        if outcome.status is not GenerationStatus.ANSWERED or outcome.text is None:
            await self._record_audit(
                actor_id=actor_id,
                configuration=configuration,
                policy=prepared_generation.policy,
                evidence_ids=tuple(item.evidence_id for item in evidence),
                status="failed",
                safe_error_code="citation_validation_failed",
                provider_execution=_combine_execution(
                    contextualization_execution,
                    generation_result.execution,
                ),
                latency_ms=_elapsed_ms(generation_started),
            )
            raise _safe_generation_error("citation_validation_failed")
        turn_id = uuid4()
        answered = replace(
            outcome,
            turn_id=turn_id,
            validation_token=self.turn_signer.sign(
                content=outcome.text,
                actor_id=actor_id,
                turn_id=turn_id,
                configuration_version_id=configuration.configuration_version_id,
            ),
            execution=prepared_generation.execution,
        )
        await self._record_audit(
            actor_id=actor_id,
            configuration=configuration,
            policy=prepared_generation.policy,
            evidence_ids=tuple(item.evidence_id for item in evidence),
            status="succeeded",
            safe_error_code=None,
            provider_execution=_combine_execution(
                contextualization_execution,
                generation_result.execution,
            ),
            latency_ms=_elapsed_ms(generation_started),
        )
        return answered

    async def _record_audit(
        self,
        *,
        actor_id: UUID,
        configuration: ResolvedSearchConfiguration,
        policy: PolicyDecision | None,
        evidence_ids: tuple[UUID, ...],
        status: str,
        safe_error_code: str | None,
        provider_execution: ProviderExecutionMetadata | None = None,
        latency_ms: int | None = None,
    ) -> None:
        profile = configuration.generation_profile
        repository = self.generation_audit_repository
        if profile is None:
            return
        deployment = profile.deployment
        if deployment is None or policy is None or repository is None:
            raise _safe_generation_error("deployment_not_ready")
        execution_latency = (
            latency_ms
            if latency_ms is not None
            else provider_execution.latency_ms
            if provider_execution is not None
            else 0
        )
        try:
            audit = GenerationExecutionAudit(
                id=uuid4(),
                actor_id=actor_id,
                configuration_version_id=configuration.configuration_version_id,
                generation_profile_id=profile.profile_id,
                deployment_version_id=deployment.id,
                installation_policy_version_id=policy.installation_policy_version_id,
                workspace_policies=tuple(
                    WorkspacePolicyAuditSnapshot(workspace_id, policy_version_id)
                    for workspace_id, policy_version_id in policy.workspace_policy_snapshots
                ),
                provider=deployment.provider,
                provider_model_id=deployment.provider_model_id,
                location=deployment.location,
                external_transfer=deployment.external_transfer,
                policy_allowed=policy.allowed,
                policy_reason_code=(
                    policy.reason_code.value if policy.reason_code is not None else None
                ),
                prompt_ref=profile.prompt_ref,
                prompt_version=prompt_reference_version(profile.prompt_ref),
                evidence_ids=evidence_ids,
                input_tokens=(
                    provider_execution.input_tokens
                    if provider_execution is not None
                    else None
                ),
                output_tokens=(
                    provider_execution.output_tokens
                    if provider_execution is not None
                    else None
                ),
                latency_ms=execution_latency,
                provider_reported_input_tokens=(
                    provider_execution.input_tokens
                    if provider_execution is not None
                    else None
                ),
                provider_reported_output_tokens=(
                    provider_execution.output_tokens
                    if provider_execution is not None
                    else None
                ),
                cost_basis_version=None,
                estimated_cost_microunits=None,
                status=status,
                safe_error_code=safe_error_code,
                correlation_id=_correlation_uuid(),
                created_at=datetime.now(UTC),
            )
            await repository.add(audit)
            await repository.commit()
        except Exception:
            raise AppError(
                "llm_unavailable",
                "생성 실행 기록을 안전하게 저장할 수 없습니다.",
                503,
            ) from None


class _ResolvedScopeResolver:
    def __init__(self, scope: ResolvedSearchScope) -> None:
        self._scope = scope

    async def resolve(
        self,
        *,
        actor_id: UUID,
        workspace_ids: tuple[UUID, ...],
        folder_ids: tuple[UUID, ...],
        indexing_profile_id: UUID,
    ) -> ResolvedSearchScope:
        del actor_id, indexing_profile_id
        if (
            workspace_ids != self._scope.workspace_ids
            or folder_ids != self._scope.folder_ids
        ):
            raise ValueError("The authorized search scope changed unexpectedly.")
        return self._scope


def _approval_is_current(
    *,
    approval: ResolvedExternalApproval | None,
    configuration: ResolvedSearchConfiguration,
    deployment: ModelDeploymentVersion,
    policy: PolicyDecision,
    disclosure_version: str,
) -> bool:
    if approval is None:
        return False
    expected_workspace_ids = tuple(dict.fromkeys(configuration.workspace_ids))
    current_snapshots = policy.workspace_policy_snapshots
    approval_snapshots = tuple(
        (snapshot.workspace_id, snapshot.policy_version_id)
        for snapshot in approval.workspace_policies
    )
    if len(dict(current_snapshots)) != len(current_snapshots):
        return False
    if len(dict(approval_snapshots)) != len(approval_snapshots):
        return False
    return (
        approval.configuration_version_id == configuration.configuration_version_id
        and approval.deployment_version_id == deployment.id
        and approval.installation_policy_version_id
        == policy.installation_policy_version_id
        and approval.disclosure_version == disclosure_version
        and dict(approval_snapshots) == dict(current_snapshots)
        and set(dict(approval_snapshots)) == set(expected_workspace_ids)
    )


_SAFE_GENERATION_ERRORS: dict[str, tuple[str, int]] = {
    "deployment_not_allowed_in_environment": (
        "현재 환경에서는 선택한 생성 실행을 사용할 수 없습니다.",
        409,
    ),
    "workspace_external_transfer_denied": (
        "선택한 지식 공간의 외부 전송 정책이 생성을 허용하지 않습니다.",
        403,
    ),
    "provider_not_allowed": (
        "현재 데이터 정책이 선택한 외부 생성 서비스를 허용하지 않습니다.",
        403,
    ),
    "deployment_not_ready": (
        "선택한 생성 실행이 준비되지 않았습니다.",
        503,
    ),
    "provider_authentication_failed": (
        "생성 서비스 인증을 확인할 수 없습니다.",
        503,
    ),
    "provider_rate_limited": (
        "생성 서비스 요청 한도에 도달했습니다.",
        503,
    ),
    "provider_timeout": (
        "생성 서비스 응답 시간이 초과되었습니다.",
        504,
    ),
    "provider_invalid_response": (
        "생성 서비스가 유효한 응답을 반환하지 않았습니다.",
        502,
    ),
    "structured_output_invalid": (
        "생성 서비스의 구조화 응답을 검증할 수 없습니다.",
        502,
    ),
    "citation_validation_failed": (
        "생성 답변의 근거 인용을 검증할 수 없습니다.",
        502,
    ),
}

_SAFE_SEARCH_AUDIT_CODES = frozenset(
    {
        "invalid_query",
        "invalid_result_limit",
        "query_tokenizer_unavailable",
        "query_token_limit_exceeded",
        "bm25_search_unavailable",
        "hybrid_search_unavailable",
        "evidence_embedding_unavailable",
    }
)


def _approved_provider_code(code: str) -> str:
    if code in _SAFE_GENERATION_ERRORS:
        return code
    return "provider_invalid_response"


def _safe_search_audit_code(code: str) -> str:
    if code in _SAFE_SEARCH_AUDIT_CODES:
        return code
    return "search_failed"


def _safe_generation_error(code: str) -> AppError:
    safe_code = _approved_provider_code(code)
    message, status_code = _SAFE_GENERATION_ERRORS[safe_code]
    return AppError(safe_code, message, status_code)


def _validate_registered_prompts(profile: GenerationProfile) -> None:
    """Reject corrupt profile metadata before policy/runtime execution begins.

    No execution audit is attempted here: an unregistered prompt has no valid
    immutable prompt version to record, and no provider execution has started.
    """
    try:
        prompt_reference_version(profile.prompt_ref)
        prompt_reference_version(profile.context_prompt_ref)
    except PromptNotFoundError:
        raise _safe_generation_error("deployment_not_ready") from None


def _correlation_uuid() -> UUID:
    try:
        return UUID(correlation_id_context.get())
    except ValueError:
        return uuid4()


def _elapsed_ms(started: float) -> int:
    return max(0, round((perf_counter() - started) * 1000))


def _combine_execution(
    first: ProviderExecutionMetadata | None,
    second: ProviderExecutionMetadata,
) -> ProviderExecutionMetadata:
    if first is None:
        return second
    if (
        first.provider != second.provider
        or first.provider_model_id != second.provider_model_id
        or first.deployment_version_id != second.deployment_version_id
    ):
        raise _safe_generation_error("provider_invalid_response")
    return ProviderExecutionMetadata(
        provider=second.provider,
        provider_model_id=second.provider_model_id,
        deployment_version_id=second.deployment_version_id,
        input_tokens=_sum_optional(first.input_tokens, second.input_tokens),
        output_tokens=_sum_optional(first.output_tokens, second.output_tokens),
        latency_ms=first.latency_ms + second.latency_ms,
    )


def _execution_is_exact(
    execution: ProviderExecutionMetadata,
    deployment: ModelDeploymentVersion | None,
) -> bool:
    return (
        deployment is not None
        and execution.provider is deployment.provider
        and execution.provider_model_id == deployment.provider_model_id
        and execution.deployment_version_id == deployment.id
    )


def _sum_optional(first: int | None, second: int | None) -> int | None:
    if first is None and second is None:
        return None
    return (first or 0) + (second or 0)


def _generation_evidence(
    selection: EvidenceSelection,
) -> tuple[GroundingEvidence, ...]:
    answers = (
        *((selection.answer,) if selection.answer is not None else ()),
        *selection.conflicts,
    )
    return tuple(
        GroundingEvidence(
            evidence_id=answer.evidence.id,
            text=answer.evidence.text,
            document_id=answer.source.document_id,
            asset_version_id=answer.source.chunk.asset_version_id,
            projection_id=answer.evidence.projection_id,
            chunk_id=answer.evidence.chunk_id,
            element_id=answer.evidence.location.element_id,
            page=answer.evidence.location.page,
            char_start=answer.evidence.location.char_start,
            char_end=answer.evidence.location.char_end,
            bbox=answer.evidence.location.bbox,
        )
        for answer in answers
    )


def _related_sources(
    sources: tuple[EvidenceSource, ...],
    selection: EvidenceSelection,
) -> tuple[RelatedSource, ...]:
    selected_version_ids = {
        item.source.chunk.asset_version_id
        for item in (
            *((selection.answer,) if selection.answer is not None else ()),
            *selection.conflicts,
        )
    }
    seen: set[UUID] = set()
    related: list[RelatedSource] = []
    for source in sources:
        version_id = source.chunk.asset_version_id
        if version_id in selected_version_ids or version_id in seen:
            continue
        seen.add(version_id)
        related.append(RelatedSource(source))
    return tuple(related)
