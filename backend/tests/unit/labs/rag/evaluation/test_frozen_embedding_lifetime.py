"""Frozen-model ownership must reach the real pipeline's release boundary."""

from dataclasses import asdict, replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from ai_workshop.labs.rag.evaluation import tasks
from ai_workshop.labs.rag.search.pipeline import PipelineInput
from tests.unit.labs.rag.embeddings.test_sentence_transformer_adapter import config
from tests.unit.labs.rag.search.test_request_embedding_lifetime import ACTOR_ID, harness


def frozen_candidate(device="cpu"):
    indexing_id, retrieval_id, model_id, version_id, policy_id = (
        UUID(int=n) for n in range(100, 105)
    )
    model_config = asdict(config(dimension=2))
    model_config["device"] = device
    batch_size = model_config.pop("batch_size")
    snapshot = {
        "configuration": {"version_id": str(version_id)},
        "profiles": [
            {"id": str(indexing_id), "kind": "indexing",
             "config": {"embedding": {"batch_size": batch_size}}},
            {"id": str(retrieval_id), "kind": "retrieval", "name": "synthetic",
             "version": 1, "config": {"indexing_profile_id": str(indexing_id)}},
        ],
        "bindings": [{"profile_id": str(indexing_id), "role": "embedding",
                      "model_id": str(model_id)}],
        "models": [{"id": str(model_id), "kind": "embedding", "name": "synthetic",
                    "version": 1, "config": model_config}],
        "answer_policy": {"id": str(policy_id), "min_semantic_score": 0.5,
                          "min_keyword_coverage": 0.5, "require_complete_provenance": True,
                          "conflict_mode": "separate_sources"},
    }
    candidate = SimpleNamespace(
        configuration_version_id=version_id, component_snapshot=snapshot,
        execution_snapshot={"candidates": [
            {"configuration_version_id": str(version_id), "component_snapshot": snapshot}
        ]},
    )
    target = SimpleNamespace(
        indexing_profile_id=indexing_id, descriptor=SimpleNamespace(vector_dimension=2)
    )
    return candidate, target


@pytest.mark.parametrize("injected", [False, True])
@pytest.mark.parametrize("device", ["cpu", "cuda"])
async def test_frozen_default_owns_fresh_pinned_models_but_injected_runtime_is_borrowed(
    monkeypatch, tmp_path, injected, device,
):
    service, request, configuration, factory, runtime = harness(tmp_path)
    candidate, target = frozen_candidate(device)
    client = SimpleNamespace(close=AsyncMock())
    monkeypatch.setattr(tasks, "create_elasticsearch", lambda settings: client)
    configs = []

    def build(model_config, *, cache_folder):
        configs.append(model_config)
        assert cache_folder == tmp_path
        return factory()

    monkeypatch.setattr(tasks, "SentenceTransformerEmbedding", build)
    borrowed = configuration.embedding
    search = tasks.ProductionEvaluationSearch(
        SimpleNamespace(model_cache_root=tmp_path),
        embedding_factory=(lambda model_config: borrowed) if injected else None,
    )
    try:
        frozen = search._resolve_configuration(candidate, target)
        owned_factory = frozen.request_owned_embedding_factory
        if injected or device != "cpu":
            assert owned_factory is None
            if injected:
                assert frozen.embedding is borrowed
            assert frozen.embedding.encode_query("synthetic fact") == [1.0, 0.0]
            return
        assert owned_factory is not None
        configuration = replace(
            configuration, embedding=frozen.embedding,
            request_owned_embedding_factory=owned_factory,
        )
        first = await service.execute(PipelineInput(ACTOR_ID, request, configuration))
        second = await service.execute(PipelineInput(ACTOR_ID, request, first.configuration))
        assert first.grounding_evidence == second.grounding_evidence
        assert first.generation.citations == second.generation.citations
        assert first.generation.text == second.generation.text == "synthetic fact"
        assert len(runtime.requests) == 2
        assert len(factory.models) == 2
        assert all(model() is None for model in factory.models)
        assert all(item == config(dimension=2) for item in configs)
        assert len(configs) == 3  # Lazy placeholder, then two independent executions.
        assert frozen.embedding._model is None and not frozen.embedding._closed
    finally:
        await search.close()
