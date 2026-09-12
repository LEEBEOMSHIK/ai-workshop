from collections.abc import Sequence
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from ai_workshop.labs.rag.deployments.domain import (
    DeploymentCapability,
    DeploymentEnvironment,
    ExecutionLocation,
    ModelDeploymentVersion,
    ProviderKind,
)
from ai_workshop.labs.rag.documents.domain import EvidenceUnit, SourceLocation
from ai_workshop.labs.rag.embeddings.contracts import EmbeddingPort
from ai_workshop.labs.rag.generation.domain import (
    ContextPolicy,
    ContextualizationRequest,
    ConversationRole,
    ConversationTurn,
    GeneratedClaim,
    GenerationProfile,
    GenerationRequest,
    StructuredGeneration,
)
from ai_workshop.labs.rag.generation.execution import (
    ProviderContextualizationResult,
    ProviderExecutionMetadata,
    ProviderGenerationResult,
    ProviderHealthResult,
)
from ai_workshop.labs.rag.generation.integrity import (
    ConversationScopeBinding,
    ConversationTurnSigner,
)
from ai_workshop.labs.rag.highlighting.domain import AnswerPolicy, EvidenceSource
from ai_workshop.labs.rag.indexing.contracts import IndexDescriptor
from ai_workshop.labs.rag.models.domain import Profile, ProfileKind
from ai_workshop.labs.rag.policies.domain import PolicyDecision
from ai_workshop.labs.rag.retrieval.domain import (
    ActiveIndexAlias,
    DenseHit,
    FusedHit,
    ResolvedSearchScope,
    RetrievedChunk,
    SearchIndexTarget,
    SelectedDocumentIdentity,
    SparseHit,
)
from ai_workshop.labs.rag.search.configuration_port import ResolvedSearchConfiguration
from ai_workshop.labs.rag.search.schemas import (
    ConversationTurnRequest,
    SearchRequest,
    SearchResponse,
)
from ai_workshop.labs.rag.search.service import SearchApplicationService
from ai_workshop.shared.errors import AppError

ACTOR_ID = UUID("10000000-0000-0000-0000-000000000001")
DOMAIN_ID = UUID("20000000-0000-0000-0000-000000000001")
CONNECTION_ID = UUID("20000000-0000-0000-0000-000000000002")
WORKSPACE_ID = UUID("20000000-0000-0000-0000-000000000003")
CONFIGURATION_ID = UUID("30000000-0000-0000-0000-000000000001")
CONFIGURATION_VERSION_ID = UUID("30000000-0000-0000-0000-000000000002")
INDEXING_PROFILE_ID = UUID("40000000-0000-0000-0000-000000000001")
PROCESSING_PROFILE_ID = UUID("40000000-0000-0000-0000-000000000002")
DOCUMENT_ID = UUID("50000000-0000-0000-0000-000000000001")
DOCUMENT_B_ID = UUID("50000000-0000-0000-0000-000000000002")
FOREIGN_DOCUMENT_ID = UUID("50000000-0000-0000-0000-000000000003")
PROCESSING_DOCUMENT_ID = UUID("50000000-0000-0000-0000-000000000004")
TURN_ID = UUID("60000000-0000-0000-0000-000000000001")
EVIDENCE_A_ID = UUID("55000000-0000-0000-0000-000000000001")
EVIDENCE_B_ID = UUID("55000000-0000-0000-0000-000000000002")
DEPLOYMENT_VERSION_ID = UUID("70000000-0000-0000-0000-000000000010")
INSTALLATION_POLICY_ID = UUID("70000000-0000-0000-0000-000000000011")
WORKSPACE_POLICY_ID = UUID("70000000-0000-0000-0000-000000000012")
A_TEXT = "환매 수수료는 1%입니다."
B_TEXT = "환매 수수료는 2%입니다."


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


class SelectedScopeResolver:
    def __init__(self, identity: SelectedDocumentIdentity, fingerprint: str) -> None:
        self.identity = identity
        self.fingerprint = fingerprint
        self.calls: list[tuple[tuple[UUID, ...] | None, UUID | None]] = []

    async def resolve(
        self,
        *,
        actor_id: UUID,
        workspace_ids: tuple[UUID, ...],
        folder_ids: tuple[UUID, ...],
        indexing_profile_id: UUID,
        document_ids: tuple[UUID, ...] | None = None,
        document_processing_profile_id: UUID | None = None,
    ) -> ResolvedSearchScope:
        assert (actor_id, indexing_profile_id) == (ACTOR_ID, INDEXING_PROFILE_ID)
        self.calls.append((document_ids, document_processing_profile_id))
        return ResolvedSearchScope(
            workspace_ids=workspace_ids,
            folder_ids=folder_ids,
            asset_version_ids=(self.identity.asset_version_id,),
            index_build_ids=(self.identity.index_build_id,),
            document_ids=(self.identity.document_id,),
            selected_documents=(self.identity,),
            scope_fingerprint=self.fingerprint,
        )


class EmptyRetriever:
    def __init__(self) -> None:
        self.scopes: list[ResolvedSearchScope] = []

    async def search_sparse(
        self,
        *,
        index_alias: SearchIndexTarget,
        query: str,
        actor_id: UUID,
        scope: ResolvedSearchScope,
        top_k: int,
    ) -> tuple[SparseHit, ...]:
        del index_alias, query, actor_id, top_k
        self.scopes.append(scope)
        return ()

    async def search_dense(
        self,
        *,
        index_alias: SearchIndexTarget,
        query_vector: tuple[float, ...],
        actor_id: UUID,
        scope: ResolvedSearchScope,
        top_k: int,
    ) -> tuple[DenseHit, ...]:
        del index_alias, query_vector, actor_id, top_k
        self.scopes.append(scope)
        return ()


class EmptySourceResolver:
    async def resolve(
        self,
        *,
        actor_id: UUID,
        indexing_profile_id: UUID,
        hits: tuple[FusedHit, ...],
    ) -> tuple[EvidenceSource, ...]:
        del actor_id, indexing_profile_id, hits
        return ()


class RecordingGenerationRuntime:
    def __init__(self) -> None:
        self.health_calls = 0
        self.contextualize_calls = 0
        self.generate_calls = 0

    async def health(self) -> ProviderHealthResult:
        self.health_calls += 1
        raise AssertionError("Scope validation must run before generation health.")

    async def contextualize(
        self,
        request: ContextualizationRequest,
    ) -> ProviderContextualizationResult:
        del request
        self.contextualize_calls += 1
        raise AssertionError("Scope validation must run before contextualization.")

    async def generate(self, request: GenerationRequest) -> ProviderGenerationResult:
        del request
        self.generate_calls += 1
        raise AssertionError("Scope validation must run before generation.")


class StatefulSelectedScopeResolver:
    def __init__(self) -> None:
        self.identities = {
            DOCUMENT_ID: _selected_identity(DOCUMENT_ID, lifecycle=1),
            DOCUMENT_B_ID: _selected_identity(DOCUMENT_B_ID, lifecycle=1),
        }
        self.fingerprints = {
            (DOCUMENT_ID,): "a" * 64,
            (DOCUMENT_ID, DOCUMENT_B_ID): "b" * 64,
        }
        self.failures: dict[UUID, tuple[str, int]] = {}
        self.calls: list[tuple[tuple[UUID, ...] | None, UUID | None]] = []

    def switch_a_version(self) -> None:
        self.identities[DOCUMENT_ID] = _selected_identity(DOCUMENT_ID, lifecycle=2)
        self.fingerprints[(DOCUMENT_ID,)] = "c" * 64
        self.fingerprints[(DOCUMENT_ID, DOCUMENT_B_ID)] = "d" * 64

    def reject(self, document_id: UUID, *, code: str, status_code: int) -> None:
        self.failures[document_id] = (code, status_code)

    async def resolve(
        self,
        *,
        actor_id: UUID,
        workspace_ids: tuple[UUID, ...],
        folder_ids: tuple[UUID, ...],
        indexing_profile_id: UUID,
        document_ids: tuple[UUID, ...] | None = None,
        document_processing_profile_id: UUID | None = None,
    ) -> ResolvedSearchScope:
        assert (actor_id, indexing_profile_id) == (ACTOR_ID, INDEXING_PROFILE_ID)
        self.calls.append((document_ids, document_processing_profile_id))
        assert document_ids is not None
        normalized_ids = tuple(sorted(dict.fromkeys(document_ids), key=lambda item: item.hex))
        for document_id in normalized_ids:
            failure = self.failures.get(document_id)
            if failure is not None:
                code, status_code = failure
                message = (
                    "The requested resource was not found."
                    if status_code == 404
                    else "Selected documents are not ready."
                )
                raise AppError(code, message, status_code)
        identities = tuple(self.identities[document_id] for document_id in normalized_ids)
        return ResolvedSearchScope(
            workspace_ids=workspace_ids,
            folder_ids=folder_ids,
            asset_version_ids=tuple(item.asset_version_id for item in identities),
            index_build_ids=tuple(item.index_build_id for item in identities),
            document_ids=normalized_ids,
            selected_documents=identities,
            scope_fingerprint=self.fingerprints[normalized_ids],
        )


class SelectedScopeRetriever:
    def __init__(self, sources: tuple[EvidenceSource, ...]) -> None:
        self.sources = sources
        self.sparse_scopes: list[ResolvedSearchScope] = []
        self.dense_scopes: list[ResolvedSearchScope] = []

    async def search_sparse(
        self,
        *,
        index_alias: SearchIndexTarget,
        query: str,
        actor_id: UUID,
        scope: ResolvedSearchScope,
        top_k: int,
    ) -> tuple[SparseHit, ...]:
        del index_alias, query, actor_id, top_k
        self.sparse_scopes.append(scope)
        return tuple(
            SparseHit(source.chunk, rank=rank, score=1.0 / rank)
            for rank, source in enumerate(self.sources, start=1)
            if source.chunk.asset_version_id in scope.asset_version_ids
            and source.chunk.index_build_id in scope.index_build_ids
        )

    async def search_dense(
        self,
        *,
        index_alias: SearchIndexTarget,
        query_vector: tuple[float, ...],
        actor_id: UUID,
        scope: ResolvedSearchScope,
        top_k: int,
    ) -> tuple[DenseHit, ...]:
        del index_alias, query_vector, actor_id, top_k
        self.dense_scopes.append(scope)
        return ()


class SelectedSourceResolver:
    def __init__(self, sources: tuple[EvidenceSource, ...]) -> None:
        self.sources = {source.chunk.chunk_id: source for source in sources}
        self.calls: list[tuple[UUID, ...]] = []

    async def resolve(
        self,
        *,
        actor_id: UUID,
        indexing_profile_id: UUID,
        hits: tuple[FusedHit, ...],
    ) -> tuple[EvidenceSource, ...]:
        assert (actor_id, indexing_profile_id) == (ACTOR_ID, INDEXING_PROFILE_ID)
        chunk_ids = tuple(hit.chunk_id for hit in hits)
        assert all(isinstance(item, UUID) for item in chunk_ids)
        exact_ids = tuple(item for item in chunk_ids if isinstance(item, UUID))
        self.calls.append(exact_ids)
        return tuple(self.sources[item] for item in exact_ids)


class RecordingAnswerRuntime:
    def __init__(self) -> None:
        self.health_calls: list[None] = []
        self.contextualize_requests: list[ContextualizationRequest] = []
        self.generation_requests: list[GenerationRequest] = []

    async def health(self) -> ProviderHealthResult:
        self.health_calls.append(None)
        return ProviderHealthResult(
            ready=True,
            observed_provider_model_id=_deployment().provider_model_id,
            execution=_provider_execution(),
        )

    async def contextualize(
        self,
        request: ContextualizationRequest,
    ) -> ProviderContextualizationResult:
        self.contextualize_requests.append(request)
        return ProviderContextualizationResult(request.question, _provider_execution())

    async def generate(self, request: GenerationRequest) -> ProviderGenerationResult:
        self.generation_requests.append(request)
        return ProviderGenerationResult(
            StructuredGeneration(
                schema_version=1,
                claims=tuple(
                    GeneratedClaim(item.text, (item.evidence_id,)) for item in request.evidence
                ),
            ),
            _provider_execution(),
        )


def _identity(*, lifecycle: int) -> SelectedDocumentIdentity:
    return SelectedDocumentIdentity(
        document_id=DOCUMENT_ID,
        asset_version_id=UUID(f"50000000-0000-0000-0000-{lifecycle:012d}"),
        projection_id=UUID(f"50000000-0000-0000-0001-{lifecycle:012d}"),
        index_build_id=UUID(f"50000000-0000-0000-0002-{lifecycle:012d}"),
    )


def _selected_identity(
    document_id: UUID,
    *,
    lifecycle: int,
) -> SelectedDocumentIdentity:
    document_number = 1 if document_id == DOCUMENT_ID else 2
    value = (document_number * 10) + lifecycle
    return SelectedDocumentIdentity(
        document_id=document_id,
        asset_version_id=UUID(f"51000000-0000-0000-0000-{value:012d}"),
        projection_id=UUID(f"52000000-0000-0000-0000-{value:012d}"),
        index_build_id=UUID(f"53000000-0000-0000-0000-{value:012d}"),
    )


def _source(
    identity: SelectedDocumentIdentity,
    *,
    value: int,
    text: str,
) -> EvidenceSource:
    chunk_id = UUID(f"54000000-0000-0000-0000-{value:012d}")
    evidence = EvidenceUnit(
        id=UUID(f"55000000-0000-0000-0000-{value:012d}"),
        chunk_id=chunk_id,
        projection_id=identity.projection_id,
        ordinal=0,
        text=text,
        location=SourceLocation(
            element_id=UUID(f"56000000-0000-0000-0000-{value:012d}"),
            page=None,
            char_start=0,
            char_end=len(text),
            bbox=None,
        ),
    )
    return EvidenceSource(
        document_id=identity.document_id,
        asset_version_number=value,
        media_type="text/plain",
        chunk=RetrievedChunk(
            chunk_id=chunk_id,
            projection_id=identity.projection_id,
            asset_version_id=identity.asset_version_id,
            workspace_id=WORKSPACE_ID,
            folder_id=None,
            index_build_id=identity.index_build_id,
            title=f"document-{value}.txt",
            section_path=("환매",),
            text=text,
            evidence_units=(evidence,),
        ),
        fused_score=1.0 / value,
    )


def _deployment() -> ModelDeploymentVersion:
    return replace(
        ModelDeploymentVersion.create(
            deployment_id=UUID("70000000-0000-0000-0000-000000000020"),
            version=1,
            display_name="Synthetic local answer",
            description="Offline selected-scope acceptance runtime",
            model_definition_id=UUID("70000000-0000-0000-0000-000000000021"),
            provider=ProviderKind.LOCAL_OPENAI_COMPATIBLE,
            location=ExecutionLocation.LOCAL,
            allowed_environments=(DeploymentEnvironment.DEVELOPMENT,),
            provider_model_id="synthetic-local-model",
            endpoint_ref="synthetic-local-endpoint",
            secret_ref=None,
            capabilities=(
                DeploymentCapability.STRUCTURED_OUTPUT,
                DeploymentCapability.CONTEXTUALIZATION,
            ),
            external_transfer=False,
            transmitted_data_categories=(),
            data_processing_notice_ref=None,
            timeout_seconds=1.0,
            max_retries=0,
            retry_backoff_seconds=0.0,
            healthcheck_enabled=True,
            development_only=True,
            created_by=ACTOR_ID,
        ),
        id=DEPLOYMENT_VERSION_ID,
    )


def _provider_execution() -> ProviderExecutionMetadata:
    deployment = _deployment()
    return ProviderExecutionMetadata(
        provider=deployment.provider,
        provider_model_id=deployment.provider_model_id,
        deployment_version_id=deployment.id,
        input_tokens=1,
        output_tokens=1,
        latency_ms=1,
    )


def _scope(*, fingerprint: str) -> ConversationScopeBinding:
    return ConversationScopeBinding(
        domain_id=DOMAIN_ID,
        connection_version_id=CONNECTION_ID,
        workspace_ids=(WORKSPACE_ID,),
        folder_ids=(),
        document_ids=(DOCUMENT_ID,),
        scope_fingerprint=fingerprint,
    )


def _configuration(
    *,
    generation_runtime: RecordingGenerationRuntime | None = None,
) -> ResolvedSearchConfiguration:
    generation_profile = (
        GenerationProfile(
            profile_id=UUID("70000000-0000-0000-0000-000000000001"),
            profile_name="Synthetic selected history",
            profile_version=1,
            model_id=UUID("70000000-0000-0000-0000-000000000002"),
            model_name="Synthetic model",
            model_version=1,
            runtime_model="synthetic-model",
            prompt_ref="rag-answer-v1",
            context_prompt_ref="rag-contextualize-v1",
            context_policy=ContextPolicy(max_history_turns=4, max_history_tokens=100),
            timeout_seconds=1.0,
            max_output_tokens=100,
            temperature=0.0,
            response_schema_version=1,
        )
        if generation_runtime is not None
        else None
    )
    return ResolvedSearchConfiguration(
        configuration_id=CONFIGURATION_ID,
        configuration_version_id=CONFIGURATION_VERSION_ID,
        configuration_version=1,
        indexing_profile_id=INDEXING_PROFILE_ID,
        retrieval_profile=Profile.create(
            kind=ProfileKind.RETRIEVAL,
            name="Synthetic selected scope",
            version=1,
            config={"bm25": {"top_k": 10}},
            bindings=(),
        ),
        answer_policy_version_id=UUID("30000000-0000-0000-0000-000000000003"),
        answer_policy=AnswerPolicy(
            min_semantic_score=0.8,
            min_keyword_coverage=1.0,
        ),
        active_index_alias=ActiveIndexAlias(
            IndexDescriptor(2, "cosine"),
            "synthetic-selected-scope",
            INDEXING_PROFILE_ID,
            PROCESSING_PROFILE_ID,
        ),
        embedding=StubEmbedding(),
        workspace_ids=(WORKSPACE_ID,),
        experimental=False,
        generation_profile=generation_profile,
        generation_runtime=generation_runtime,
    )


def _acceptance_configuration(
    runtime: RecordingAnswerRuntime,
) -> ResolvedSearchConfiguration:
    deployment = _deployment()
    return replace(
        _configuration(),
        retrieval_profile=Profile.create(
            kind=ProfileKind.RETRIEVAL,
            name="Synthetic hybrid selected scope",
            version=1,
            config={
                "bm25": {"top_k": 10},
                "dense": {"top_k": 10},
                "rrf": {"k": 60},
                "indexing_profile_id": str(INDEXING_PROFILE_ID),
            },
            bindings=(),
        ),
        generation_profile=GenerationProfile(
            profile_id=UUID("70000000-0000-0000-0000-000000000001"),
            profile_name="Synthetic selected-scope acceptance",
            profile_version=1,
            model_id=deployment.model_definition_id,
            model_name="Synthetic local model",
            model_version=1,
            runtime_model=deployment.provider_model_id,
            prompt_ref="rag-answer-v1",
            context_prompt_ref="rag-contextualize-v1",
            context_policy=ContextPolicy(max_history_turns=4, max_history_tokens=100),
            timeout_seconds=1.0,
            max_output_tokens=100,
            temperature=0.0,
            response_schema_version=1,
            deployment=deployment,
        ),
        generation_runtime=runtime,
    )


def _acceptance_harness() -> tuple[
    SearchApplicationService,
    ResolvedSearchConfiguration,
    StatefulSelectedScopeResolver,
    SelectedScopeRetriever,
    SelectedSourceResolver,
    RecordingAnswerRuntime,
    AsyncMock,
]:
    scope = StatefulSelectedScopeResolver()
    sources = (
        _source(scope.identities[DOCUMENT_ID], value=1, text=A_TEXT),
        _source(scope.identities[DOCUMENT_B_ID], value=2, text=B_TEXT),
    )
    retriever = SelectedScopeRetriever(sources)
    source_resolver = SelectedSourceResolver(sources)
    runtime = RecordingAnswerRuntime()
    decision = PolicyDecision(
        True,
        None,
        INSTALLATION_POLICY_ID,
        (WORKSPACE_POLICY_ID,),
        workspace_policy_snapshots=((WORKSPACE_ID, WORKSPACE_POLICY_ID),),
    )
    policy_resolver = SimpleNamespace(resolve=AsyncMock(return_value=decision))
    audit_add = AsyncMock()
    audit = SimpleNamespace(add=audit_add, commit=AsyncMock())
    service = SearchApplicationService(
        configuration_resolver=object(),  # type: ignore[arg-type]
        scope_resolver=scope,
        sparse_retriever=retriever,
        dense_retriever=retriever,
        source_resolver=source_resolver,
        turn_signer=ConversationTurnSigner(b"s" * 32),
        generation_policy_resolver=policy_resolver,
        generation_audit_repository=audit,
    )
    return (
        service,
        _acceptance_configuration(runtime),
        scope,
        retriever,
        source_resolver,
        runtime,
        audit_add,
    )


def _selected_request(
    document_ids: list[UUID],
    *,
    history: list[ConversationTurnRequest] | None = None,
) -> SearchRequest:
    return SearchRequest(
        query="환매 수수료",
        configuration_id=CONFIGURATION_ID,
        workspace_ids=[WORKSPACE_ID],
        document_ids=document_ids,
        history=history or [],
    )


def _domain_scope() -> ConversationScopeBinding:
    return ConversationScopeBinding(
        domain_id=DOMAIN_ID,
        connection_version_id=CONNECTION_ID,
        workspace_ids=(WORKSPACE_ID,),
        folder_ids=(),
    )


def _request(token: str) -> SearchRequest:
    return SearchRequest(
        query="후속 질문",
        configuration_id=CONFIGURATION_ID,
        workspace_ids=[WORKSPACE_ID],
        document_ids=[DOCUMENT_ID],
        history=[
            ConversationTurnRequest(
                role="assistant",
                content="이전 답변",
                turn_id=TURN_ID,
                validation_token=token,
            )
        ],
    )


def _user_history_request() -> SearchRequest:
    return SearchRequest(
        query="후속 질문",
        configuration_id=CONFIGURATION_ID,
        workspace_ids=[WORKSPACE_ID],
        document_ids=[DOCUMENT_ID],
        history=[ConversationTurnRequest(role="user", content="사용자 제공 문맥")],
    )


def _service(
    *,
    identity: SelectedDocumentIdentity,
    fingerprint: str,
) -> tuple[SearchApplicationService, SelectedScopeResolver, EmptyRetriever]:
    scope = SelectedScopeResolver(identity, fingerprint)
    retriever = EmptyRetriever()
    return (
        SearchApplicationService(
            configuration_resolver=object(),  # type: ignore[arg-type]
            scope_resolver=scope,
            sparse_retriever=retriever,
            dense_retriever=retriever,
            source_resolver=EmptySourceResolver(),
            turn_signer=ConversationTurnSigner(b"s" * 32),
        ),
        scope,
        retriever,
    )


@pytest.mark.asyncio
async def test_same_selected_scope_history_continues_and_returns_server_scope() -> None:
    fingerprint = "a" * 64
    identity = _identity(lifecycle=1)
    service, resolver, retriever = _service(
        identity=identity,
        fingerprint=fingerprint,
    )
    assert service.turn_signer is not None
    token = service.turn_signer.sign_scoped(
        content="이전 답변",
        actor_id=ACTOR_ID,
        turn_id=TURN_ID,
        configuration_version_id=CONFIGURATION_VERSION_ID,
        scope=_scope(fingerprint=fingerprint),
    )

    result = await service.search_resolved(
        actor_id=ACTOR_ID,
        request=_request(token),
        configuration=_configuration(),
        conversation_scope=ConversationScopeBinding(
            domain_id=DOMAIN_ID,
            connection_version_id=CONNECTION_ID,
            workspace_ids=(WORKSPACE_ID,),
            folder_ids=(),
        ),
    )

    assert resolver.calls == [((DOCUMENT_ID,), PROCESSING_PROFILE_ID)] * 3
    assert len(retriever.scopes) == 1
    assert retriever.scopes[0].document_ids == (DOCUMENT_ID,)
    assert result.selected_scope is not None
    assert result.selected_scope.identities == (identity,)
    assert result.selected_scope.fingerprint == fingerprint
    response = SearchResponse.from_domain(result)
    assert response.selected_scope is not None
    assert response.selected_scope.model_dump(mode="json") == {
        "identities": [
            {
                "document_id": str(identity.document_id),
                "asset_version_id": str(identity.asset_version_id),
                "projection_id": str(identity.projection_id),
                "index_build_id": str(identity.index_build_id),
            }
        ],
        "fingerprint": fingerprint,
    }


@pytest.mark.asyncio
async def test_selected_domain_keeps_user_history_as_untrusted_input() -> None:
    fingerprint = "a" * 64
    service, resolver, retriever = _service(
        identity=_identity(lifecycle=1),
        fingerprint=fingerprint,
    )

    result = await service.search_resolved(
        actor_id=ACTOR_ID,
        request=_user_history_request(),
        configuration=_configuration(),
        conversation_scope=ConversationScopeBinding(
            domain_id=DOMAIN_ID,
            connection_version_id=CONNECTION_ID,
            workspace_ids=(WORKSPACE_ID,),
            folder_ids=(),
        ),
    )

    assert resolver.calls == [((DOCUMENT_ID,), PROCESSING_PROFILE_ID)] * 3
    assert len(retriever.scopes) == 1
    assert result.selected_scope is not None


@pytest.mark.asyncio
async def test_selected_a_excludes_b_from_retrieval_generation_and_response_scope() -> None:
    service, configuration, resolver, retriever, source_resolver, runtime, _audit = (
        _acceptance_harness()
    )

    result = await service.search_resolved(
        actor_id=ACTOR_ID,
        request=_selected_request([DOCUMENT_ID]),
        configuration=configuration,
        conversation_scope=_domain_scope(),
    )

    assert resolver.calls == [((DOCUMENT_ID,), PROCESSING_PROFILE_ID)] * 4
    expected_identity = resolver.identities[DOCUMENT_ID]
    assert len(retriever.sparse_scopes) == len(retriever.dense_scopes) == 1
    for scope in (*retriever.sparse_scopes, *retriever.dense_scopes):
        assert scope.document_ids == (DOCUMENT_ID,)
        assert scope.asset_version_ids == (expected_identity.asset_version_id,)
        assert scope.index_build_ids == (expected_identity.index_build_id,)
    assert source_resolver.calls == [(UUID("54000000-0000-0000-0000-000000000001"),)]
    assert len(runtime.generation_requests) == 1
    evidence = runtime.generation_requests[0].evidence
    assert tuple(item.evidence_id for item in evidence) == (EVIDENCE_A_ID,)
    assert tuple(item.document_id for item in evidence) == (DOCUMENT_ID,)
    assert tuple(item.text for item in evidence) == (A_TEXT,)
    assert B_TEXT not in runtime.generation_requests[0].evidence[0].text
    assert result.retrieved_evidence_ids == (EVIDENCE_A_ID,)
    assert tuple(
        evidence_id
        for citation in result.generation.citations
        for evidence_id in citation.evidence_ids
    ) == (EVIDENCE_A_ID,)
    assert result.selected_scope is not None
    assert result.selected_scope.identities == (expected_identity,)
    assert result.selected_scope.fingerprint == "a" * 64
    response = SearchResponse.from_domain(result)
    assert response.selected_scope is not None
    assert [item.document_id for item in response.selected_scope.identities] == [DOCUMENT_ID]
    assert response.selected_scope.fingerprint == "a" * 64
    assert [item.evidence_ids for item in response.generation.citations] == [[EVIDENCE_A_ID]]


@pytest.mark.asyncio
async def test_adding_b_rejects_old_history_then_succeeds_with_new_context() -> None:
    service, configuration, resolver, _retriever, _sources, runtime, _audit = _acceptance_harness()
    first = await service.search_resolved(
        actor_id=ACTOR_ID,
        request=_selected_request([DOCUMENT_ID]),
        configuration=configuration,
        conversation_scope=_domain_scope(),
    )
    assert first.generation.text is not None
    assert first.generation.turn_id is not None
    assert first.generation.validation_token is not None
    assert first.generation.validation_token.startswith("v3.")
    old_history = [
        ConversationTurnRequest(
            role="assistant",
            content=first.generation.text,
            turn_id=first.generation.turn_id,
            validation_token=first.generation.validation_token,
        )
    ]
    before_model_calls = (
        len(runtime.health_calls),
        len(runtime.contextualize_requests),
        len(runtime.generation_requests),
    )

    with pytest.raises(AppError) as caught:
        await service.search_resolved(
            actor_id=ACTOR_ID,
            request=_selected_request(
                [DOCUMENT_ID, DOCUMENT_B_ID],
                history=old_history,
            ),
            configuration=configuration,
            conversation_scope=_domain_scope(),
        )

    assert (caught.value.code, caught.value.status_code) == (
        "conversation_scope_changed",
        409,
    )
    assert (
        len(runtime.health_calls),
        len(runtime.contextualize_requests),
        len(runtime.generation_requests),
    ) == before_model_calls

    fresh = await service.search_resolved(
        actor_id=ACTOR_ID,
        request=_selected_request([DOCUMENT_ID, DOCUMENT_B_ID]),
        configuration=configuration,
        conversation_scope=_domain_scope(),
    )

    assert resolver.calls == [
        ((DOCUMENT_ID,), PROCESSING_PROFILE_ID),
        ((DOCUMENT_ID,), PROCESSING_PROFILE_ID),
        ((DOCUMENT_ID,), PROCESSING_PROFILE_ID),
        ((DOCUMENT_ID,), PROCESSING_PROFILE_ID),
        ((DOCUMENT_ID, DOCUMENT_B_ID), PROCESSING_PROFILE_ID),
        ((DOCUMENT_ID, DOCUMENT_B_ID), PROCESSING_PROFILE_ID),
        ((DOCUMENT_ID, DOCUMENT_B_ID), PROCESSING_PROFILE_ID),
        ((DOCUMENT_ID, DOCUMENT_B_ID), PROCESSING_PROFILE_ID),
        ((DOCUMENT_ID, DOCUMENT_B_ID), PROCESSING_PROFILE_ID),
    ]
    assert tuple(item.evidence_id for item in runtime.generation_requests[-1].evidence) == (
        EVIDENCE_A_ID,
        EVIDENCE_B_ID,
    )
    assert fresh.selected_scope is not None
    assert fresh.selected_scope.identities == (
        resolver.identities[DOCUMENT_ID],
        resolver.identities[DOCUMENT_B_ID],
    )
    assert fresh.selected_scope.fingerprint == "b" * 64
    assert first.selected_scope is not None
    assert fresh.selected_scope.fingerprint != first.selected_scope.fingerprint


@pytest.mark.asyncio
async def test_active_version_switch_rejects_old_selected_scope_signature_before_model() -> None:
    service, configuration, resolver, retriever, sources, runtime, _audit = _acceptance_harness()
    first = await service.search_resolved(
        actor_id=ACTOR_ID,
        request=_selected_request([DOCUMENT_ID]),
        configuration=configuration,
        conversation_scope=_domain_scope(),
    )
    assert first.generation.text is not None
    assert first.generation.turn_id is not None
    assert first.generation.validation_token is not None
    old_identity = resolver.identities[DOCUMENT_ID]
    resolver.switch_a_version()
    before_calls = (
        len(retriever.sparse_scopes),
        len(retriever.dense_scopes),
        len(sources.calls),
        len(runtime.health_calls),
        len(runtime.contextualize_requests),
        len(runtime.generation_requests),
    )

    with pytest.raises(AppError) as caught:
        await service.search_resolved(
            actor_id=ACTOR_ID,
            request=_selected_request(
                [DOCUMENT_ID],
                history=[
                    ConversationTurnRequest(
                        role="assistant",
                        content=first.generation.text,
                        turn_id=first.generation.turn_id,
                        validation_token=first.generation.validation_token,
                    )
                ],
            ),
            configuration=configuration,
            conversation_scope=_domain_scope(),
        )

    assert (caught.value.code, caught.value.status_code) == (
        "conversation_scope_changed",
        409,
    )
    current_identity = resolver.identities[DOCUMENT_ID]
    assert current_identity.document_id == old_identity.document_id
    assert current_identity.asset_version_id != old_identity.asset_version_id
    assert current_identity.projection_id != old_identity.projection_id
    assert current_identity.index_build_id != old_identity.index_build_id
    for private_value in (
        str(DOCUMENT_ID),
        str(old_identity.asset_version_id),
        str(old_identity.projection_id),
        str(old_identity.index_build_id),
        str(current_identity.asset_version_id),
        str(current_identity.projection_id),
        str(current_identity.index_build_id),
        "a" * 64,
        "c" * 64,
    ):
        assert private_value not in caught.value.message
    assert (
        len(retriever.sparse_scopes),
        len(retriever.dense_scopes),
        len(sources.calls),
        len(runtime.health_calls),
        len(runtime.contextualize_requests),
        len(runtime.generation_requests),
    ) == before_calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("invalid_document_id", "code", "status_code"),
    [
        (FOREIGN_DOCUMENT_ID, "not_found", 404),
        (PROCESSING_DOCUMENT_ID, "selected_documents_not_ready", 409),
    ],
    ids=["foreign", "not-ready"],
)
async def test_invalid_selected_document_aborts_whole_request_before_model(
    invalid_document_id: UUID,
    code: str,
    status_code: int,
) -> None:
    service, configuration, resolver, retriever, sources, runtime, audit_add = _acceptance_harness()
    resolver.reject(invalid_document_id, code=code, status_code=status_code)

    with pytest.raises(AppError) as caught:
        await service.search_resolved(
            actor_id=ACTOR_ID,
            request=_selected_request([DOCUMENT_ID, invalid_document_id]),
            configuration=configuration,
            conversation_scope=_domain_scope(),
        )

    assert (caught.value.code, caught.value.status_code) == (code, status_code)
    assert str(invalid_document_id) not in caught.value.message
    assert resolver.calls == [((DOCUMENT_ID, invalid_document_id), PROCESSING_PROFILE_ID)]
    assert retriever.sparse_scopes == retriever.dense_scopes == []
    assert sources.calls == []
    assert runtime.health_calls == []
    assert runtime.contextualize_requests == []
    assert runtime.generation_requests == []
    assert audit_add.await_count == 0


@pytest.mark.asyncio
async def test_tampered_selected_scope_token_is_invalid_history_not_scope_change() -> None:
    fingerprint = "a" * 64
    service, resolver, retriever = _service(
        identity=_identity(lifecycle=1),
        fingerprint=fingerprint,
    )
    assert service.turn_signer is not None
    token = service.turn_signer.sign_scoped(
        content="이전 답변",
        actor_id=ACTOR_ID,
        turn_id=TURN_ID,
        configuration_version_id=CONFIGURATION_VERSION_ID,
        scope=_scope(fingerprint=fingerprint),
    )
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")

    with pytest.raises(AppError) as caught:
        await service.search_resolved(
            actor_id=ACTOR_ID,
            request=_request(tampered),
            configuration=_configuration(),
            conversation_scope=ConversationScopeBinding(
                domain_id=DOMAIN_ID,
                connection_version_id=CONNECTION_ID,
                workspace_ids=(WORKSPACE_ID,),
                folder_ids=(),
            ),
        )

    assert (caught.value.code, caught.value.status_code) == (
        "conversation_history_invalid",
        422,
    )
    assert resolver.calls == [((DOCUMENT_ID,), PROCESSING_PROFILE_ID)]
    assert retriever.scopes == []


def test_selected_scope_v3_token_fits_history_schema_limit() -> None:
    token = ConversationTurnSigner(b"s" * 32).sign_scoped(
        content="이전 답변",
        actor_id=ACTOR_ID,
        turn_id=TURN_ID,
        configuration_version_id=CONFIGURATION_VERSION_ID,
        scope=_scope(fingerprint="a" * 64),
    )

    assert len(token) <= 256
    assert (
        ConversationTurn(
            role=ConversationRole.ASSISTANT,
            content="이전 답변",
            turn_id=TURN_ID,
            validation_token=token,
        ).validation_token
        == token
    )
