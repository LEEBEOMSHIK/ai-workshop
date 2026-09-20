from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.configurations.repository import SqlAlchemySearchConfigurationResolver
from ai_workshop.labs.rag.embeddings.contracts import EmbeddingModelConfig
from ai_workshop.labs.rag.models.domain import ProfileKind
from ai_workshop.labs.rag.retrieval.domain import FrozenIndexIdentity, FrozenIndexTarget
from ai_workshop.labs.rag.search.schemas import SearchRequest
from tests.unit.labs.rag.search.test_selected_scope_history import (
    ACTOR_ID,
    CONFIGURATION_ID,
    DOCUMENT_ID,
    PROCESSING_PROFILE_ID,
    WORKSPACE_ID,
    StubEmbedding,
    _configuration,
    _identity,
    _scope,
    _service,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("frozen", [False, True])
async def test_semantic_processing_profile_reaches_selected_scope_for_legacy_target(frozen):
    identity = _identity(lifecycle=1)
    service, resolver, retriever = _service(identity=identity, fingerprint="a" * 64)
    configuration = _configuration()
    target = replace(configuration.active_index_alias, document_processing_profile_id=None)
    if frozen:
        target = FrozenIndexTarget(
            target.descriptor,
            target.index_prefix,
            target.indexing_profile_id,
            (
                FrozenIndexIdentity(
                    target.descriptor.concrete_index_name(
                        target.index_prefix, target.indexing_profile_id, identity.index_build_id
                    ),
                    "synthetic-index-uuid",
                    identity.index_build_id,
                    identity.projection_id,
                    target.indexing_profile_id,
                    target.descriptor.vector_dimension,
                    target.descriptor.mapping_version,
                ),
            ),
            (identity.asset_version_id,),
        )
    configuration = replace(
        configuration,
        active_index_alias=target,
        document_processing_profile_id=PROCESSING_PROFILE_ID,
    )
    result = await service.search_resolved(
        actor_id=ACTOR_ID,
        request=SearchRequest(
            query="synthetic",
            configuration_id=CONFIGURATION_ID,
            workspace_ids=[WORKSPACE_ID],
            document_ids=[DOCUMENT_ID],
        ),
        configuration=configuration,
        conversation_scope=_scope(fingerprint="a" * 64),
    )
    assert resolver.calls == [((DOCUMENT_ID,), PROCESSING_PROFILE_ID)] * 3
    assert len(retriever.scopes) == 1 and result.selected_scope is not None
    assert configuration.active_index_alias is target
    assert target.document_processing_profile_id is None


@pytest.mark.asyncio
async def test_existing_configuration_stub_can_use_processing_named_alias():
    service, resolver, _ = _service(identity=_identity(lifecycle=1), fingerprint="a" * 64)
    configuration = _configuration()
    assert configuration.document_processing_profile_id is None
    await service.search_resolved(
        actor_id=ACTOR_ID,
        request=SearchRequest(
            query="synthetic",
            configuration_id=CONFIGURATION_ID,
            workspace_ids=[WORKSPACE_ID],
            document_ids=[DOCUMENT_ID],
        ),
        configuration=configuration,
        conversation_scope=_scope(fingerprint="a" * 64),
    )
    assert resolver.calls == [((DOCUMENT_ID,), PROCESSING_PROFILE_ID)] * 3


@pytest.mark.asyncio
@pytest.mark.parametrize("frozen", [False, True])
async def test_production_resolver_retains_saved_semantic_profile_for_legacy_names(
    monkeypatch, frozen
):
    base = _configuration()
    target = replace(base.active_index_alias, document_processing_profile_id=None)
    identity = _identity(lifecycle=1)
    physical_name = target.descriptor.concrete_index_name(
        target.index_prefix, target.indexing_profile_id, identity.index_build_id
    )
    frozen_target = (
        FrozenIndexTarget(
            target.descriptor,
            target.index_prefix,
            target.indexing_profile_id,
            (
                FrozenIndexIdentity(
                    physical_name,
                    "synthetic-index-uuid",
                    identity.index_build_id,
                    identity.projection_id,
                    target.indexing_profile_id,
                    2,
                    target.descriptor.mapping_version,
                ),
            ),
            (identity.asset_version_id,),
        )
        if frozen
        else None
    )
    indexing = SimpleNamespace(
        kind=ProfileKind.INDEXING,
        config={"embedding": {}},
        id=base.indexing_profile_id,
    )
    retrieval = replace(base.retrieval_profile, config={"indexing_profile_id": str(indexing.id)})
    session = SimpleNamespace(
        scalars=AsyncMock(
            side_effect=[
                [SimpleNamespace(model_id=uuid4())],
                [SimpleNamespace(vector_dimension=2, index_name=physical_name)],
            ]
        ),
        get=AsyncMock(return_value=object()),
    )
    resolver = SqlAlchemySearchConfigurationResolver(
        session,
        SimpleNamespace(elasticsearch_index_prefix=target.index_prefix),
        lambda _: StubEmbedding(),
    )
    resolver.repository = SimpleNamespace(find_profile=AsyncMock(side_effect=[indexing, retrieval]))
    monkeypatch.setattr(
        "ai_workshop.labs.rag.configurations.repository._model_to_domain", lambda _: object()
    )
    monkeypatch.setattr(
        EmbeddingModelConfig,
        "from_definition",
        lambda *args, **kwargs: SimpleNamespace(dimension=2, max_tokens=512),
    )
    saved = SimpleNamespace(
        id=base.configuration_id,
        version_id=base.configuration_version_id,
        version=1,
        indexing_profile_id=indexing.id,
        retrieval_profile_id=retrieval.id,
        generation_profile_id=None,
        document_processing_profile_id=PROCESSING_PROFILE_ID,
        answer_policy_version_id=base.answer_policy_version_id,
        answer_policy_version=SimpleNamespace(to_answer_policy=lambda: base.answer_policy),
        workspace_ids=base.workspace_ids,
        is_system=False,
        experimental=False,
    )
    resolved = await resolver._resolve(saved, ACTOR_ID, frozen_target=frozen_target)
    assert resolved.document_processing_profile_id == PROCESSING_PROFILE_ID
    assert resolved.active_index_alias.document_processing_profile_id is None
    if frozen_target is not None:
        assert resolved.active_index_alias is frozen_target
    else:
        assert resolved.active_index_alias.name == target.name
