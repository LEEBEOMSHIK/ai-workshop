from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from ai_workshop.labs.rag.evaluation.generative_adapter import FrozenGenerativeAdapter
from tests.unit.labs.rag.highlighting.test_evidence_selector import _source
from tests.unit.labs.rag.search.test_generation_policy_gate import (
    ACTOR_ID,
    WORKSPACE_ID,
    StubEmbedding,
    _configuration,
)


async def test_frozen_evaluation_clears_resolver_ownership_when_replacing_embedding():
    def forbidden_factory():
        raise AssertionError("Frozen evaluation must not acquire a current search embedding.")

    configuration = replace(
        _configuration(approval=None), request_owned_embedding_factory=forbidden_factory
    )
    frozen_embedding = StubEmbedding()
    frozen = replace(configuration, embedding=frozen_embedding)
    source = _source(1, "synthetic fact")
    chunk = source.chunk
    target = SimpleNamespace(
        index_build_ids=(chunk.index_build_id,), asset_version_ids=(chunk.asset_version_id,)
    )
    candidate = SimpleNamespace(
        configuration_version_id=configuration.configuration_version_id,
        configuration_id=configuration.configuration_id,
        retrieval_k=3,
        component_snapshot={
            "profiles": [
                {
                    "id": str(configuration.generation_profile.profile_id),
                    "version": configuration.generation_profile.profile_version,
                }
            ]
        },
        execution_snapshot={
            "sources": [
                {
                    "chunk_id": str(chunk.chunk_id),
                    "document_id": str(source.document_id),
                    "asset_version_id": str(chunk.asset_version_id),
                    "projection_id": str(chunk.projection_id),
                    "index_build_id": str(chunk.index_build_id),
                    "workspace": {"id": str(WORKSPACE_ID)},
                }
            ]
        },
    )
    adapter = FrozenGenerativeAdapter(
        SimpleNamespace(
            prepare_target=AsyncMock(return_value=target),
            _resolve_configuration=lambda *args: frozen,
            _resolve_scope=lambda *args: SimpleNamespace(
                workspace_ids=(WORKSPACE_ID,), folder_ids=()
            ),
        ),
        SimpleNamespace(resolve_version=AsyncMock(return_value=configuration)),
        SimpleNamespace(validate=AsyncMock()),
    )
    prepared = await adapter.prepare(
        ACTOR_ID, candidate, SimpleNamespace(id=uuid4(), query="synthetic fact")
    )
    assert prepared.configuration.embedding is frozen_embedding
    assert prepared.configuration.request_owned_embedding_factory is None
    assert configuration.request_owned_embedding_factory is forbidden_factory
    assert prepared.configuration.embedding.encode_query("synthetic") == [1.0, 0.0]
