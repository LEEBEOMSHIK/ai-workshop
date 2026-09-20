from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from ai_workshop.labs.rag.evaluation import tasks
from ai_workshop.labs.rag.evaluation.metrics import count_access_leaks, reciprocal_rank
from ai_workshop.labs.rag.evaluation.repository import _observation_json
from ai_workshop.labs.rag.highlighting.domain import AnswerStatus
from ai_workshop.labs.rag.indexing.contracts import IndexDescriptor


@pytest.mark.asyncio
@pytest.mark.parametrize("k", [1, 3, 8])
async def test_expanded_evidence_ranks_are_bounded_without_hiding_other_exposures(
    monkeypatch: pytest.MonkeyPatch, k: int
) -> None:
    identifiers = tuple(UUID(int=value) for value in range(1, 6))
    profile = UUID(int=20)
    descriptor = IndexDescriptor(3, "cosine")
    name = descriptor.concrete_index_name("test", profile, UUID(int=21))
    candidate = SimpleNamespace(
        index_builds=(
            SimpleNamespace(
                vector_dimension=3,
                indexing_profile_id=profile,
                mapping_version=1,
                index_name=name,
                index_uuid="physical-uuid",
                index_build_id=UUID(int=21),
                projection_id=UUID(int=22),
                asset_version_id=UUID(int=23),
                active_at_snapshot=True,
            ),
        ),
        component_snapshot=None,
        execution_snapshot={},
        is_system=True,
        retrieval_k=k,
    )
    sources = tuple(
        SimpleNamespace(
            chunk=SimpleNamespace(
                evidence_units=tuple(SimpleNamespace(id=identifier) for identifier in group)
            )
        )
        for group in (identifiers[:3], (identifiers[2], *identifiers[3:]))
    )
    # A repeated ID must not consume a rank. Evidence after top-k stays observable
    # through actual answer/related surfaces, including permission leak checks.
    answer = SimpleNamespace(evidence=SimpleNamespace(id=identifiers[-1]), highlights=())
    selection = SimpleNamespace(answer=answer, conflicts=(), status=AnswerStatus.SUPPORTED)
    selector = SimpleNamespace(select=lambda **kwargs: selection)
    monkeypatch.setattr(tasks, "EvidenceSelector", lambda embedding: selector)
    resolver = SimpleNamespace(resolve=lambda **kwargs: sources)
    monkeypatch.setattr(tasks, "FrozenSourceResolver", lambda snapshot: resolver)
    monkeypatch.setattr(tasks, "require_concrete_frozen_indices", AsyncMock())
    retrieval = SimpleNamespace(search=AsyncMock(return_value=()))
    monkeypatch.setattr(tasks, "HybridRetrievalService", lambda **kwargs: retrieval)
    monkeypatch.setattr(tasks, "ElasticsearchSparseRetriever", lambda client: object())
    monkeypatch.setattr(tasks, "ElasticsearchDenseRetriever", lambda client: object())
    search = object.__new__(tasks.ProductionEvaluationSearch)
    search.settings = SimpleNamespace(elasticsearch_index_prefix="test")
    search.elasticsearch = object()
    monkeypatch.setattr(
        search,
        "_resolve_configuration",
        lambda *args: SimpleNamespace(
            indexing_profile_id=profile,
            embedding=object(),
            retrieval_profile=object(),
            answer_policy=object(),
            answer_policy_version_id=UUID(int=24),
            query_max_tokens=100,
        ),
    )
    monkeypatch.setattr(
        search,
        "_resolve_scope",
        lambda *args: SimpleNamespace(
            workspace_ids=(UUID(int=25),),
            folder_ids=(),
        ),
    )
    case = SimpleNamespace(
        query="independent test query",
        permission_scenario=SimpleNamespace(
            workspace_ids=(UUID(int=25),),
        ),
    )

    observed = await search.execute(actor_id=UUID(int=26), candidate=candidate, case=case)

    assert observed.stable.retrieved_evidence_ids == identifiers[:k]
    payload = _observation_json(observed)
    assert len(payload["retrieved_ranked"]) <= k
    assert observed.stable.answer_evidence_ids == (identifiers[-1],)
    assert set(observed.stable.related_evidence_ids) == set(identifiers[:-1])
    assert (
        count_access_leaks(
            observed.exposures,
            authorized_source_ids=frozenset(identifiers[:-1]),
            forbidden_source_ids=frozenset((identifiers[-1],)),
        )
        > 0
    )
    if k < len(identifiers):
        assert (
            reciprocal_rank(observed.stable.retrieved_evidence_ids, frozenset((identifiers[-1],)))
            == 0.0
        )
