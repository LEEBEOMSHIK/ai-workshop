"""Independent frozen-adapter to real-pipeline lifetime and authority checks."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.evaluation.generative_adapter import FrozenGenerativeAdapter
from ai_workshop.labs.rag.indexing.contracts import IndexDescriptor
from ai_workshop.labs.rag.retrieval.domain import FrozenIndexIdentity, FrozenIndexTarget
from tests.unit.labs.rag.highlighting.test_evidence_selector import _source
from tests.unit.labs.rag.search.test_request_embedding_lifetime import (
    ACTOR_ID,
    WORKSPACE_ID,
    harness,
)


async def prepared_harness(tmp_path, *, owned=True):
    service, _, configuration, factory, runtime = harness(tmp_path, owned=owned)
    source = _source(1, "synthetic fact")
    chunk = source.chunk
    descriptor = IndexDescriptor(2, "cosine")
    target = FrozenIndexTarget(
        descriptor=descriptor, index_prefix="synthetic",
        indexing_profile_id=configuration.indexing_profile_id,
        identities=(FrozenIndexIdentity(
            descriptor.concrete_index_name(
                "synthetic", configuration.indexing_profile_id, chunk.index_build_id,
            ),
            "synthetic-index-uuid", chunk.index_build_id, chunk.projection_id,
            configuration.indexing_profile_id, 2, descriptor.mapping_version,
        ),),
        asset_version_ids=(chunk.asset_version_id,),
    )
    snapshot = {
        "sources": [{
            "chunk_id": str(chunk.chunk_id), "document_id": str(source.document_id),
            "asset_version_id": str(chunk.asset_version_id),
            "projection_id": str(chunk.projection_id), "index_build_id": str(chunk.index_build_id),
            "indexing_profile_id": str(configuration.indexing_profile_id),
            "asset_version_number": source.asset_version_number, "media_type": source.media_type,
            "workspace": {"id": str(WORKSPACE_ID)}, "title": chunk.title,
            "section_path": list(chunk.section_path), "chunk_text": chunk.text,
            "evidence_units": [{
                "id": str(unit.id), "ordinal": unit.ordinal, "text": unit.text,
                "element_id": str(unit.location.element_id), "page": unit.location.page,
                "char_start": unit.location.char_start, "char_end": unit.location.char_end,
                "bbox": unit.location.bbox,
            } for unit in chunk.evidence_units],
        }],
    }
    candidate = SimpleNamespace(
        configuration_version_id=configuration.configuration_version_id,
        configuration_id=configuration.configuration_id, retrieval_k=3,
        component_snapshot={"profiles": [{
            "id": str(configuration.generation_profile.profile_id),
            "version": configuration.generation_profile.profile_version,
        }]},
        execution_snapshot=snapshot,
    )

    def forbidden_factory():
        raise AssertionError("Current resolver runtime must never replace the frozen runtime")

    validations = []

    async def validate(actor, identities, workspace_ids, folder_ids, resolved):
        assert actor == ACTOR_ID and workspace_ids == (WORKSPACE_ID,) and folder_ids == ()
        assert identities
        assert all(identity.asset_version_id == chunk.asset_version_id for identity in identities)
        assert resolved.embedding is configuration.embedding
        validations.append(identities)

    adapter = FrozenGenerativeAdapter(
        SimpleNamespace(
            prepare_target=AsyncMock(return_value=target),
            _resolve_configuration=lambda *_: configuration,
            _resolve_scope=lambda *_: SimpleNamespace(workspace_ids=(WORKSPACE_ID,), folder_ids=()),
        ),
        SimpleNamespace(resolve_version=AsyncMock(return_value=replace(
            configuration, request_owned_embedding_factory=forbidden_factory,
        ))),
        SimpleNamespace(validate=validate),
    )
    prepared = await adapter.prepare(
        ACTOR_ID, candidate, SimpleNamespace(id=uuid4(), query="synthetic fact"),
    )
    return service, prepared, factory, runtime, validations


@pytest.mark.parametrize("owned", [False, True])
async def test_frozen_adapter_to_pipeline_releases_only_owned_and_preserves_results(
    tmp_path, owned,
):
    service, prepared, factory, runtime, validations = await prepared_harness(tmp_path, owned=owned)
    first = await service.execute(prepared)
    first_validations = len(validations)
    assert first_validations > 1
    second = await service.execute(prepared)
    assert len(validations) == first_validations * 2
    assert first.configuration is second.configuration is prepared.configuration
    assert first.grounding_evidence == second.grounding_evidence
    assert first.generation.text == second.generation.text == "synthetic fact"
    assert first.generation.citations == second.generation.citations
    assert len(runtime.requests) == 2
    assert all((reference() is None) is owned for reference in factory.models)
    assert len(factory.models) == (2 if owned else 1)
    if owned:
        assert len(factory.adapters) == 2
        assert factory.adapters[0] is not factory.adapters[1]
        assert prepared.configuration.embedding._model is None
        assert not prepared.configuration.embedding._closed


@pytest.mark.parametrize("cancel", [False, True])
async def test_frozen_adapter_releases_owned_model_on_source_failure_or_cancel(tmp_path, cancel):
    service, prepared, factory, runtime, validations = await prepared_harness(tmp_path)
    entered, never = asyncio.Event(), asyncio.Event()

    async def fail(**kwargs):
        assert factory.models[0]() is not None
        entered.set()
        if cancel:
            await never.wait()
        raise RuntimeError("synthetic frozen source failure")

    prepared = replace(prepared, source_resolver=SimpleNamespace(resolve=fail))
    task = asyncio.create_task(service.execute(prepared))
    if cancel:
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
        await task
    assert validations
    assert runtime.requests == []
    assert factory.models[0]() is None
