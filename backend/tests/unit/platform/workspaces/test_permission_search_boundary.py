"""Prepared scopes must not outlive the actor's current read grants."""

from dataclasses import replace
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.retrieval.domain import ResolvedSearchScope
from ai_workshop.labs.rag.retrieval.service import HybridRetrievalService
from ai_workshop.labs.rag.search.schemas import SearchRequest
from ai_workshop.labs.rag.search.service import SearchApplicationService
from ai_workshop.shared.errors import AppError
from tests.unit.labs.rag.retrieval.test_service import (
    INDEXING_PROFILE_ID,
    RecordingDenseRetriever,
    RecordingEmbedding,
    RecordingSparseRetriever,
    _active_alias,
    _hybrid_profile,
)
from tests.unit.labs.rag.retrieval.test_service import (
    RecordingScopeResolver as RetrievalScopeResolver,
)
from tests.unit.labs.rag.search.test_generation_policy_gate import (
    ACTOR_ID,
    CONFIGURATION_ID,
    WORKSPACE_ID,
    NeverRetriever,
    NeverSourceResolver,
    RecordingScopeResolver,
    StubConfigurationResolver,
    _configuration,
)


class RevokedAfterPreparation(RecordingScopeResolver):
    async def resolve(self, **kwargs):
        if self.calls:
            raise AppError("not_found", "Revoked.", 404)
        return await super().resolve(**kwargs)


@pytest.mark.asyncio
async def test_revocation_after_preparation_aborts_before_retrieval() -> None:
    service = SearchApplicationService(
        configuration_resolver=StubConfigurationResolver(
            replace(
                _configuration(approval=None),
                generation_profile=None,
                experimental=False,
            )
        ),
        scope_resolver=RevokedAfterPreparation(),
        sparse_retriever=NeverRetriever(),
        dense_retriever=NeverRetriever(),
        source_resolver=NeverSourceResolver(),
    )
    with pytest.raises(AppError) as denied:
        await service.search(
            actor_id=ACTOR_ID,
            request=SearchRequest(
                configuration_id=CONFIGURATION_ID,
                workspace_ids=[WORKSPACE_ID],
                query="synthetic",
            ),
        )
    assert denied.value.status_code == 404


@pytest.mark.asyncio
async def test_revocation_during_query_encoding_aborts_both_candidate_branches() -> None:
    events: list[str] = []
    revoked = False
    scope = ResolvedSearchScope(
        (uuid4(),), (), asset_version_ids=(uuid4(),), index_build_ids=(uuid4(),)
    )

    class CurrentScope(RetrievalScopeResolver):
        async def resolve(self, **kwargs):
            if revoked:
                raise AppError("not_found", "Revoked.", 404)
            return await super().resolve(**kwargs)

    class RevokingEmbedding(RecordingEmbedding):
        def encode_query(self, text: str) -> list[float]:
            nonlocal revoked
            result = super().encode_query(text)
            revoked = True
            return result

    sparse = RecordingSparseRetriever(events, ())
    dense = RecordingDenseRetriever(events, ())
    service = HybridRetrievalService(
        scope_resolver=CurrentScope(events, scope),
        embedding=RevokingEmbedding(events),
        sparse_retriever=sparse,
        dense_retriever=dense,
    )
    with pytest.raises(AppError) as denied:
        await service.search(
            actor_id=uuid4(),
            query="query",
            workspace_ids=scope.workspace_ids,
            folder_ids=(),
            indexing_profile_id=INDEXING_PROFILE_ID,
            retrieval_profile=_hybrid_profile(),
            index_alias=_active_alias(),
            result_limit=10,
        )
    assert denied.value.status_code == 404
    assert sparse.calls == dense.calls == 0
