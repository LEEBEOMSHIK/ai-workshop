from dataclasses import replace
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.retrieval.domain import ResolvedSearchScope
from ai_workshop.labs.rag.search.schemas import ConversationTurnRequest
from ai_workshop.shared.errors import AppError
from tests.unit.labs.rag.search.test_selected_scope_history import (
    ACTOR_ID,
    DOCUMENT_B_ID,
    DOCUMENT_ID,
    WORKSPACE_ID,
    _acceptance_harness,
    _domain_scope,
    _selected_request,
)


@pytest.mark.asyncio
async def test_prepared_source_version_change_aborts_before_generation(monkeypatch) -> None:
    service, configuration, scope, _, sources, runtime, _ = _acceptance_harness()
    original_resolve = sources.resolve

    async def resolve_then_change(**kwargs):
        prepared = await original_resolve(**kwargs)
        scope.switch_a_version()
        return prepared

    monkeypatch.setattr(sources, "resolve", resolve_then_change)
    with pytest.raises(AppError) as error:
        await service.search_resolved(
            actor_id=ACTOR_ID,
            request=_selected_request([DOCUMENT_ID]),
            configuration=configuration,
            conversation_scope=_domain_scope(),
        )
    assert (error.value.code, error.value.status_code) == ("conversation_scope_changed", 409)
    assert runtime.generation_requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["folder_exit", "related_exit", "related_stays", "unrelated_exit", "document_move"]
)
async def test_final_scope_validates_used_sources_without_widening(monkeypatch, change) -> None:
    service, configuration, original, retriever, sources, runtime, _ = _acceptance_harness()
    first, other = original.identities[DOCUMENT_ID], original.identities[DOCUMENT_B_ID]
    folder = uuid4()
    current = [first, other]
    explicit = change == "document_move"
    if change not in {"related_exit", "related_stays"}:
        retriever.sources = (retriever.sources[0],)
    else:
        related = retriever.sources[1]
        sources.sources[related.chunk.chunk_id] = replace(
            related,
            chunk=replace(related.chunk, evidence_units=()),
        )

    async def resolve_scope(**kwargs):
        return ResolvedSearchScope(
            (WORKSPACE_ID,),
            (() if explicit else (folder,)),
            asset_version_ids=tuple(item.asset_version_id for item in current),
            index_build_ids=tuple(item.index_build_id for item in current),
            document_ids=((DOCUMENT_ID,) if explicit else None),
            selected_documents=((first,) if explicit else ()),
            scope_fingerprint=("a" * 64 if explicit else None),
            authorized_documents=tuple(current),
        )

    monkeypatch.setattr(original, "resolve", resolve_scope)
    hydrate = sources.resolve

    async def hydrate_then_move(**kwargs):
        prepared = await hydrate(**kwargs)
        if change == "folder_exit":
            current.remove(first)
        elif change in {"related_exit", "unrelated_exit"}:
            current.remove(other)
        return prepared

    monkeypatch.setattr(sources, "resolve", hydrate_then_move)
    request = _selected_request([DOCUMENT_ID]).model_copy(
        update={
            "document_ids": [DOCUMENT_ID] if explicit else None,
            "folder_ids": [] if explicit else [folder],
        }
    )
    domain = replace(_domain_scope(), folder_ids=() if explicit else (folder,))
    if change in {"folder_exit", "related_exit"}:
        with pytest.raises(AppError) as error:
            await service.search_resolved(
                actor_id=ACTOR_ID,
                request=request,
                configuration=configuration,
                conversation_scope=domain,
            )
        assert (error.value.code, error.value.status_code) == ("conversation_scope_changed", 409)
        assert runtime.generation_requests == []
    else:
        result = await service.search_resolved(
            actor_id=ACTOR_ID,
            request=request,
            configuration=configuration,
            conversation_scope=domain,
        )
        assert len(runtime.generation_requests) == 1
        if change == "related_stays":
            assert tuple(item.source.document_id for item in result.related_sources) == (
                DOCUMENT_B_ID,
            )
        if explicit:
            assert result.selected_scope is not None
            assert result.selected_scope.fingerprint == "a" * 64


@pytest.mark.asyncio
async def test_candidate_removed_during_source_hydration_aborts(monkeypatch) -> None:
    service, configuration, _, _, sources, runtime, _ = _acceptance_harness()

    async def removed_source(**kwargs):
        return ()

    monkeypatch.setattr(sources, "resolve", removed_source)
    with pytest.raises(AppError) as error:
        await service.search_resolved(
            actor_id=ACTOR_ID,
            request=_selected_request([DOCUMENT_ID]),
            configuration=configuration,
            conversation_scope=_domain_scope(),
        )
    assert (error.value.code, error.value.status_code) == ("conversation_scope_changed", 409)
    assert runtime.generation_requests == []


@pytest.mark.asyncio
async def test_scope_failure_after_contextualization_keeps_sanitized_audit(monkeypatch) -> None:
    service, configuration, scope, _, sources, runtime, audit = _acceptance_harness()
    hydrate = sources.resolve

    async def hydrate_then_switch(**kwargs):
        prepared = await hydrate(**kwargs)
        scope.switch_a_version()
        return prepared

    monkeypatch.setattr(sources, "resolve", hydrate_then_switch)
    with pytest.raises(AppError) as error:
        await service.search_resolved(
            actor_id=ACTOR_ID,
            request=_selected_request(
                [DOCUMENT_ID],
                history=[
                    ConversationTurnRequest(role="user", content="Synthetic earlier question"),
                ],
            ),
            configuration=configuration,
            conversation_scope=_domain_scope(),
        )
    assert error.value.code == "conversation_scope_changed"
    assert len(runtime.contextualize_requests) == 1
    assert runtime.generation_requests == []
    recorded = audit.call_args.args[0]
    assert recorded.status == "failed"
    assert recorded.safe_error_code == "search_failed"
    assert recorded.evidence_ids == ()


@pytest.mark.asyncio
async def test_prepared_source_cross_paired_projection_aborts_before_generation(
    monkeypatch,
) -> None:
    service, configuration, scope, _, sources, runtime, _ = _acceptance_harness()
    original_resolve = sources.resolve

    async def resolve_with_cross_pair(**kwargs):
        prepared = await original_resolve(**kwargs)
        scope.switch_a_version()
        changed = scope.identities[DOCUMENT_ID]
        return tuple(
            replace(
                source,
                chunk=replace(
                    source.chunk,
                    asset_version_id=changed.asset_version_id,
                    index_build_id=changed.index_build_id,
                ),
            )
            for source in prepared
        )

    monkeypatch.setattr(sources, "resolve", resolve_with_cross_pair)
    with pytest.raises(AppError) as error:
        await service.search_resolved(
            actor_id=ACTOR_ID,
            request=_selected_request([DOCUMENT_ID]),
            configuration=configuration,
            conversation_scope=_domain_scope(),
        )
    assert (error.value.code, error.value.status_code) == ("conversation_scope_changed", 409)
    assert runtime.generation_requests == []
