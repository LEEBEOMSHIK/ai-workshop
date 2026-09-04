from collections.abc import Sequence
from dataclasses import fields, replace
from typing import Never
from uuid import UUID

import pytest

from ai_workshop.labs.rag.deployments.domain import (
    DeploymentCapability,
    DeploymentEnvironment,
    ExecutionLocation,
    ModelDeploymentVersion,
    ProviderKind,
)
from ai_workshop.labs.rag.embeddings.contracts import EmbeddingPort
from ai_workshop.labs.rag.generation.audit import GenerationExecutionAudit
from ai_workshop.labs.rag.generation.domain import ContextPolicy, GenerationProfile
from ai_workshop.labs.rag.generation.execution import (
    GenerationProviderError,
    ResolvedGenerationRuntime,
)
from ai_workshop.labs.rag.highlighting.domain import AnswerPolicy, EvidenceSource
from ai_workshop.labs.rag.indexing.contracts import IndexDescriptor
from ai_workshop.labs.rag.models.domain import Profile, ProfileKind
from ai_workshop.labs.rag.policies.domain import PolicyDecision, PolicyReasonCode
from ai_workshop.labs.rag.retrieval.domain import (
    ActiveIndexAlias,
    DenseHit,
    FusedHit,
    ResolvedSearchScope,
    SearchIndexTarget,
    SparseHit,
)
from ai_workshop.labs.rag.search import service as search_service_module
from ai_workshop.labs.rag.search.configuration_port import (
    ResolvedExternalApproval,
    ResolvedSearchConfiguration,
    ResolvedWorkspacePolicyApproval,
)
from ai_workshop.labs.rag.search.schemas import ConversationTurnRequest, SearchRequest
from ai_workshop.labs.rag.search.service import SearchApplicationService
from ai_workshop.shared.errors import AppError

ACTOR_ID = UUID("10000000-0000-0000-0000-000000000001")
WORKSPACE_ID = UUID("20000000-0000-0000-0000-000000000001")
OTHER_WORKSPACE_ID = UUID("20000000-0000-0000-0000-000000000002")
CONFIGURATION_ID = UUID("30000000-0000-0000-0000-000000000001")
CONFIGURATION_VERSION_ID = UUID("30000000-0000-0000-0000-000000000002")
ANSWER_POLICY_ID = UUID("30000000-0000-0000-0000-000000000003")
INSTALLATION_POLICY_ID = UUID("30000000-0000-0000-0000-000000000004")
WORKSPACE_POLICY_ID = UUID("30000000-0000-0000-0000-000000000005")
OTHER_WORKSPACE_POLICY_ID = UUID("30000000-0000-0000-0000-000000000006")
INDEXING_PROFILE_ID = UUID("40000000-0000-0000-0000-000000000001")
DEPLOYMENT_VERSION_ID = UUID("50000000-0000-0000-0000-000000000010")


class StubEmbedding(EmbeddingPort):
    dimension = 2

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def count_query_tokens(self, text: str) -> int:
        return len(text.split())

    def encode_query(self, text: str) -> list[float]:
        return [1.0, 0.0]

    def encode_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


class StubConfigurationResolver:
    def __init__(self, configuration: ResolvedSearchConfiguration) -> None:
        self.configuration = configuration

    async def resolve(
        self, configuration_id: UUID, actor_id: UUID
    ) -> ResolvedSearchConfiguration:
        assert (configuration_id, actor_id) == (CONFIGURATION_ID, ACTOR_ID)
        return self.configuration

    async def resolve_version(
        self, configuration_version_id: UUID, actor_id: UUID
    ) -> ResolvedSearchConfiguration:
        assert (configuration_version_id, actor_id) == (
            CONFIGURATION_VERSION_ID,
            ACTOR_ID,
        )
        return self.configuration


class RecordingScopeResolver:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, ...]] = []

    async def resolve(
        self,
        *,
        actor_id: UUID,
        workspace_ids: tuple[UUID, ...],
        folder_ids: tuple[UUID, ...],
        indexing_profile_id: UUID,
    ) -> ResolvedSearchScope:
        del actor_id, folder_ids, indexing_profile_id
        self.calls.append(workspace_ids)
        return ResolvedSearchScope(workspace_ids, ())


class DenyingPolicyResolver:
    def __init__(self, decision: PolicyDecision) -> None:
        self.decision = decision
        self.calls: list[tuple[UUID, ...]] = []

    async def resolve(
        self,
        *,
        deployment: ModelDeploymentVersion,
        workspace_ids: tuple[UUID, ...],
    ) -> PolicyDecision:
        del deployment
        self.calls.append(workspace_ids)
        return self.decision


class RecordingRuntimeResolver:
    def __init__(self) -> None:
        self.calls: list[tuple[object, object]] = []

        self.failure: GenerationProviderError | None = None

    def resolve(
        self,
        deployment: ModelDeploymentVersion,
        policy: PolicyDecision,
    ) -> ResolvedGenerationRuntime:
        self.calls.append((deployment, policy))
        if self.failure is not None:
            raise self.failure
        raise AssertionError("A denied request must not construct a runtime.")


class RecordingAuditRepository:
    def __init__(self) -> None:
        self.audits: list[GenerationExecutionAudit] = []
        self.commits = 0

    async def add(self, audit: GenerationExecutionAudit) -> GenerationExecutionAudit:
        self.audits.append(audit)
        return audit

    async def commit(self) -> None:
        self.commits += 1


class NeverRetriever:
    async def search_sparse(
        self,
        *,
        index_alias: SearchIndexTarget,
        query: str,
        actor_id: UUID,
        scope: ResolvedSearchScope,
        top_k: int,
    ) -> tuple[SparseHit, ...]:
        del index_alias, query, actor_id, scope, top_k
        raise AssertionError("Sparse retrieval must not run.")

    async def search_dense(
        self,
        *,
        index_alias: SearchIndexTarget,
        query_vector: tuple[float, ...],
        actor_id: UUID,
        scope: ResolvedSearchScope,
        top_k: int,
    ) -> tuple[DenseHit, ...]:
        del index_alias, query_vector, actor_id, scope, top_k
        raise AssertionError("Dense retrieval must not run.")


class NeverSourceResolver:
    async def resolve(
        self,
        *,
        actor_id: UUID,
        indexing_profile_id: UUID,
        hits: tuple[FusedHit, ...],
    ) -> tuple[EvidenceSource, ...]:
        del actor_id, indexing_profile_id, hits
        raise AssertionError("Source resolution must not run.")


def _deployment() -> ModelDeploymentVersion:
    return replace(
        ModelDeploymentVersion.create(
            deployment_id=UUID("50000000-0000-0000-0000-000000000001"),
            version=1,
            display_name="OpenAI synthetic answer",
            description="Synthetic external deployment",
            model_definition_id=UUID("50000000-0000-0000-0000-000000000002"),
            provider=ProviderKind.OPENAI_RESPONSES,
            location=ExecutionLocation.EXTERNAL,
            allowed_environments=(DeploymentEnvironment.DEVELOPMENT,),
            provider_model_id="synthetic/exact-model",
            endpoint_ref="openai-responses",
            secret_ref="openai-primary",
            capabilities=(
                DeploymentCapability.STRUCTURED_OUTPUT,
                DeploymentCapability.CONTEXTUALIZATION,
            ),
            external_transfer=True,
            transmitted_data_categories=("question", "bounded_history", "evidence"),
            data_processing_notice_ref="public-notice-v1",
            timeout_seconds=10.0,
            max_retries=0,
            retry_backoff_seconds=0.0,
            healthcheck_enabled=True,
            development_only=False,
            created_by=ACTOR_ID,
        ),
        id=DEPLOYMENT_VERSION_ID,
    )


def _profile(deployment: ModelDeploymentVersion) -> GenerationProfile:
    return GenerationProfile(
        profile_id=UUID("50000000-0000-0000-0000-000000000003"),
        profile_name="Synthetic generation",
        profile_version=1,
        model_id=deployment.model_definition_id,
        model_name="OpenAI synthetic model",
        model_version=3,
        runtime_model=deployment.provider_model_id,
        prompt_ref="rag-answer-v1",
        context_prompt_ref="rag-contextualize-v1",
        context_policy=ContextPolicy(max_history_turns=4, max_history_tokens=100),
        timeout_seconds=10.0,
        max_output_tokens=100,
        temperature=0.0,
        response_schema_version=1,
        deployment=deployment,
    )


def _configuration(
    *,
    approval: ResolvedExternalApproval | None,
    prompt_ref: str = "rag-answer-v1",
) -> ResolvedSearchConfiguration:
    deployment = _deployment()
    return ResolvedSearchConfiguration(
        configuration_id=CONFIGURATION_ID,
        configuration_version_id=CONFIGURATION_VERSION_ID,
        configuration_version=1,
        indexing_profile_id=INDEXING_PROFILE_ID,
        retrieval_profile=Profile.create(
            kind=ProfileKind.RETRIEVAL,
            name="Synthetic BM25",
            version=1,
            config={"bm25": {"top_k": 10}},
            bindings=(),
        ),
        answer_policy_version_id=ANSWER_POLICY_ID,
        answer_policy=AnswerPolicy(
            min_semantic_score=0.8,
            min_keyword_coverage=1.0,
            require_complete_provenance=True,
            conflict_mode="separate_sources",
        ),
        active_index_alias=ActiveIndexAlias(
            IndexDescriptor(2, "cosine"), "synthetic-rag", INDEXING_PROFILE_ID
        ),
        embedding=StubEmbedding(),
        workspace_ids=(WORKSPACE_ID, OTHER_WORKSPACE_ID),
        experimental=True,
        generation_profile=replace(_profile(deployment), prompt_ref=prompt_ref),
        external_approval=approval,
    )


def _approval(*, extra: bool = False) -> ResolvedExternalApproval:
    snapshots = [
        ResolvedWorkspacePolicyApproval(WORKSPACE_ID, WORKSPACE_POLICY_ID),
        ResolvedWorkspacePolicyApproval(OTHER_WORKSPACE_ID, OTHER_WORKSPACE_POLICY_ID),
    ]
    if extra:
        snapshots.append(
            ResolvedWorkspacePolicyApproval(
                UUID("20000000-0000-0000-0000-000000000099"),
                UUID("30000000-0000-0000-0000-000000000099"),
            )
        )
    return ResolvedExternalApproval(
        configuration_version_id=CONFIGURATION_VERSION_ID,
        deployment_version_id=_deployment().id,
        installation_policy_version_id=INSTALLATION_POLICY_ID,
        disclosure_version="external-generation-v1",
        workspace_policies=tuple(snapshots),
    )


def _service(
    *,
    configuration: ResolvedSearchConfiguration,
    decision: PolicyDecision,
) -> tuple[
    SearchApplicationService,
    RecordingScopeResolver,
    RecordingRuntimeResolver,
    RecordingAuditRepository,
]:
    scope = RecordingScopeResolver()
    runtime = RecordingRuntimeResolver()
    audit = RecordingAuditRepository()
    service = SearchApplicationService(
        configuration_resolver=StubConfigurationResolver(configuration),
        scope_resolver=scope,
        sparse_retriever=NeverRetriever(),
        dense_retriever=NeverRetriever(),
        source_resolver=NeverSourceResolver(),
        generation_policy_resolver=DenyingPolicyResolver(decision),
        generation_runtime_resolver=runtime,
        generation_audit_repository=audit,
    )
    return service, scope, runtime, audit


@pytest.mark.asyncio
async def test_denied_workspace_is_audited_before_any_payload_or_runtime() -> None:
    decision = PolicyDecision(
        False,
        PolicyReasonCode.WORKSPACE_EXTERNAL_TRANSFER_DENIED,
        INSTALLATION_POLICY_ID,
        (WORKSPACE_POLICY_ID,),
        workspace_policy_snapshots=((WORKSPACE_ID, WORKSPACE_POLICY_ID),),
    )
    service, scope, runtime, audit = _service(
        configuration=_configuration(approval=_approval()),
        decision=decision,
    )

    with pytest.raises(AppError) as caught:
        await service.search(
            actor_id=ACTOR_ID,
            request=SearchRequest(
                query="synthetic question",
                configuration_id=CONFIGURATION_ID,
                workspace_ids=[WORKSPACE_ID, OTHER_WORKSPACE_ID],
                experimental=True,
                history=[
                    ConversationTurnRequest(role="user", content="payload canary")
                ],
            ),
        )

    assert caught.value.code == "workspace_external_transfer_denied"
    assert scope.calls == [(WORKSPACE_ID, OTHER_WORKSPACE_ID)]
    assert runtime.calls == []
    assert len(audit.audits) == 1
    assert audit.commits == 1
    recorded = audit.audits[0]
    assert recorded.status == "denied"
    assert recorded.policy_allowed is False
    assert recorded.safe_error_code == "workspace_external_transfer_denied"
    assert recorded.evidence_ids == ()


@pytest.mark.asyncio
async def test_extra_approval_snapshot_fails_closed_before_runtime() -> None:
    decision = PolicyDecision(
        True,
        None,
        INSTALLATION_POLICY_ID,
        (WORKSPACE_POLICY_ID, OTHER_WORKSPACE_POLICY_ID),
        workspace_policy_snapshots=(
            (WORKSPACE_ID, WORKSPACE_POLICY_ID),
            (OTHER_WORKSPACE_ID, OTHER_WORKSPACE_POLICY_ID),
        ),
    )
    service, _scope, runtime, audit = _service(
        configuration=_configuration(approval=_approval(extra=True)),
        decision=decision,
    )

    with pytest.raises(AppError) as caught:
        await service.search(
            actor_id=ACTOR_ID,
            request=SearchRequest(
                query="synthetic question",
                configuration_id=CONFIGURATION_ID,
                workspace_ids=[WORKSPACE_ID, OTHER_WORKSPACE_ID],
                experimental=True,
            ),
        )

    assert caught.value.code == "deployment_not_ready"
    assert runtime.calls == []
    assert len(audit.audits) == 1
    assert audit.audits[0].status == "denied"
    assert audit.audits[0].safe_error_code == "deployment_not_ready"


@pytest.mark.asyncio
async def test_exact_approval_workspace_set_is_independent_of_request_order() -> None:
    decision = PolicyDecision(
        True,
        None,
        INSTALLATION_POLICY_ID,
        (WORKSPACE_POLICY_ID, OTHER_WORKSPACE_POLICY_ID),
        workspace_policy_snapshots=(
            (WORKSPACE_ID, WORKSPACE_POLICY_ID),
            (OTHER_WORKSPACE_ID, OTHER_WORKSPACE_POLICY_ID),
        ),
    )
    service, _scope, runtime, audit = _service(
        configuration=_configuration(approval=_approval()),
        decision=decision,
    )

    with pytest.raises(AssertionError, match="must not construct a runtime"):
        await service.search(
            actor_id=ACTOR_ID,
            request=SearchRequest(
                query="synthetic question",
                configuration_id=CONFIGURATION_ID,
                workspace_ids=[OTHER_WORKSPACE_ID, WORKSPACE_ID],
                experimental=True,
            ),
        )

    assert len(runtime.calls) == 1
    assert audit.audits == []


@pytest.mark.asyncio
async def test_authorized_subset_uses_full_configuration_policy_snapshot() -> None:
    decision = PolicyDecision(
        True,
        None,
        INSTALLATION_POLICY_ID,
        (WORKSPACE_POLICY_ID, OTHER_WORKSPACE_POLICY_ID),
        workspace_policy_snapshots=(
            (WORKSPACE_ID, WORKSPACE_POLICY_ID),
            (OTHER_WORKSPACE_ID, OTHER_WORKSPACE_POLICY_ID),
        ),
    )
    service, scope, runtime, audit = _service(
        configuration=_configuration(approval=_approval()),
        decision=decision,
    )

    with pytest.raises(AssertionError, match="must not construct a runtime"):
        await service.search(
            actor_id=ACTOR_ID,
            request=SearchRequest(
                query="synthetic question",
                configuration_id=CONFIGURATION_ID,
                workspace_ids=[WORKSPACE_ID],
                experimental=True,
            ),
        )

    policy_resolver = service.generation_policy_resolver
    assert isinstance(policy_resolver, DenyingPolicyResolver)
    assert policy_resolver.calls == [(WORKSPACE_ID, OTHER_WORKSPACE_ID)]
    assert scope.calls == [(WORKSPACE_ID,)]
    assert len(runtime.calls) == 1
    assert audit.audits == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("capabilities", "history"),
    [
        ((DeploymentCapability.CONTEXTUALIZATION,), []),
        (
            (DeploymentCapability.STRUCTURED_OUTPUT,),
            [ConversationTurnRequest(role="user", content="bounded history")],
        ),
    ],
)
async def test_required_capabilities_fail_before_runtime_construction(
    capabilities: tuple[DeploymentCapability, ...],
    history: list[ConversationTurnRequest],
) -> None:
    deployment = replace(_deployment(), capabilities=frozenset(capabilities))
    configuration = _configuration(approval=_approval())
    assert configuration.generation_profile is not None
    configuration = replace(
        configuration,
        generation_profile=replace(
            configuration.generation_profile,
            deployment=deployment,
        ),
    )
    decision = PolicyDecision(
        True,
        None,
        INSTALLATION_POLICY_ID,
        (WORKSPACE_POLICY_ID, OTHER_WORKSPACE_POLICY_ID),
        workspace_policy_snapshots=(
            (WORKSPACE_ID, WORKSPACE_POLICY_ID),
            (OTHER_WORKSPACE_ID, OTHER_WORKSPACE_POLICY_ID),
        ),
    )
    service, _scope, runtime, audit = _service(
        configuration=configuration,
        decision=decision,
    )

    with pytest.raises(AppError) as caught:
        await service.search(
            actor_id=ACTOR_ID,
            request=SearchRequest(
                query="synthetic question",
                configuration_id=CONFIGURATION_ID,
                workspace_ids=[WORKSPACE_ID, OTHER_WORKSPACE_ID],
                experimental=True,
                history=history,
            ),
        )

    assert caught.value.code == "deployment_not_ready"
    assert runtime.calls == []
    assert len(audit.audits) == 1
    assert audit.audits[0].status == "failed"
    assert audit.audits[0].safe_error_code == "deployment_not_ready"


@pytest.mark.asyncio
@pytest.mark.parametrize("policy_allowed", [False, True], ids=["denied", "provider-failure"])
async def test_unknown_prompt_fails_before_policy_runtime_or_payload(
    policy_allowed: bool,
) -> None:
    decision = PolicyDecision(
        policy_allowed,
        None if policy_allowed else PolicyReasonCode.PROVIDER_NOT_ALLOWED,
        INSTALLATION_POLICY_ID,
        (WORKSPACE_POLICY_ID, OTHER_WORKSPACE_POLICY_ID),
        workspace_policy_snapshots=(
            (WORKSPACE_ID, WORKSPACE_POLICY_ID),
            (OTHER_WORKSPACE_ID, OTHER_WORKSPACE_POLICY_ID),
        ),
    )
    service, _scope, runtime, audit = _service(
        configuration=_configuration(
            approval=_approval(),
            prompt_ref="unregistered-answer-prompt",
        ),
        decision=decision,
    )
    runtime.failure = GenerationProviderError(
        "provider_authentication_failed",
        retryable=False,
    )

    with pytest.raises(AppError) as caught:
        await service.search(
            actor_id=ACTOR_ID,
            request=SearchRequest(
                query="synthetic question",
                configuration_id=CONFIGURATION_ID,
                workspace_ids=[WORKSPACE_ID, OTHER_WORKSPACE_ID],
                experimental=True,
            ),
        )

    assert caught.value.code == "deployment_not_ready"
    assert "unregistered-answer-prompt" not in caught.value.message
    policy_resolver = service.generation_policy_resolver
    assert isinstance(policy_resolver, DenyingPolicyResolver)
    assert policy_resolver.calls == []
    assert runtime.calls == []
    assert audit.audits == []
    assert audit.commits == 0


@pytest.mark.asyncio
async def test_audit_construction_failure_is_safe_and_not_recursive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decision = PolicyDecision(
        False,
        PolicyReasonCode.PROVIDER_NOT_ALLOWED,
        INSTALLATION_POLICY_ID,
        (WORKSPACE_POLICY_ID, OTHER_WORKSPACE_POLICY_ID),
        workspace_policy_snapshots=(
            (WORKSPACE_ID, WORKSPACE_POLICY_ID),
            (OTHER_WORKSPACE_ID, OTHER_WORKSPACE_POLICY_ID),
        ),
    )
    service, _scope, runtime, audit = _service(
        configuration=_configuration(approval=_approval()),
        decision=decision,
    )

    def fail_audit_construction(**_values: object) -> Never:
        raise RuntimeError("raw audit construction canary")

    monkeypatch.setattr(
        search_service_module,
        "GenerationExecutionAudit",
        fail_audit_construction,
    )

    with pytest.raises(AppError) as caught:
        await service.search(
            actor_id=ACTOR_ID,
            request=SearchRequest(
                query="synthetic question",
                configuration_id=CONFIGURATION_ID,
                workspace_ids=[WORKSPACE_ID, OTHER_WORKSPACE_ID],
                experimental=True,
            ),
        )

    assert caught.value.code == "llm_unavailable"
    assert "raw audit construction canary" not in caught.value.message
    assert runtime.calls == []
    assert audit.audits == []
    assert audit.commits == 0


def test_audit_contract_has_no_payload_or_secret_fields() -> None:
    names = {field.name for field in fields(GenerationExecutionAudit)}
    assert not names.intersection(
        {
            "question",
            "history",
            "evidence_text",
            "document_text",
            "answer",
            "provider_body",
            "secret",
            "secret_ref",
            "endpoint",
            "endpoint_ref",
            "url",
        }
    )
