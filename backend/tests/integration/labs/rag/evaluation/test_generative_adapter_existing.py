"""Read-only validation of the adapter against the original saved evaluation inputs."""

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker

import ai_workshop.main  # noqa: F401
from ai_workshop.config import get_settings
from ai_workshop.labs.rag.documents.models import RagIndexBuildRecord
from ai_workshop.labs.rag.evaluation.domain import load_evaluation_dataset
from ai_workshop.labs.rag.evaluation.generative import _normalized
from ai_workshop.labs.rag.evaluation.generative_access import FrozenEvaluationAccess
from ai_workshop.labs.rag.evaluation.generative_adapter import FrozenGenerativeAdapter
from ai_workshop.labs.rag.evaluation.generative_models import GenerativeRunRecord
from ai_workshop.labs.rag.evaluation.generative_workflow import candidate_input
from ai_workshop.labs.rag.evaluation.models import (
    EvaluationDatasetRecord,
    EvaluationRunConfigurationRecord,
    EvaluationRunRecord,
)
from ai_workshop.labs.rag.evaluation.tasks import ProductionEvaluationSearch
from ai_workshop.labs.rag.search.api import get_search_configuration_resolver
from ai_workshop.shared.db import create_engine


@pytest.mark.asyncio
async def test_original_frozen_adapter_uses_exact_profile_sources_and_history():
    settings = get_settings()
    engine = create_engine(settings)
    frozen = ProductionEvaluationSearch(settings)
    try:
        async with async_sessionmaker(engine)() as session:
            candidate = await session.scalar(
                select(EvaluationRunConfigurationRecord)
                .where(
                    EvaluationRunConfigurationRecord.generation_profile_id.is_not(None),
                )
                .order_by(EvaluationRunConfigurationRecord.created_at.desc())
                .limit(1)
            )
            assert candidate is not None
            old = await session.get(EvaluationRunRecord, candidate.run_id)
            record = await session.get(EvaluationDatasetRecord, old.dataset_snapshot_id)
            dataset = load_evaluation_dataset(record.fixture_bytes)
            case = dataset.cases[0]
            snapshot = {
                **old.execution_snapshot,
                "retrieval_k": 7,
                "case_histories": {
                    str(case.id): [{"role": "user", "content": "Synthetic context."}]
                },
            }
            run = GenerativeRunRecord(snapshot=snapshot)
            adapter = FrozenGenerativeAdapter(
                frozen,
                get_search_configuration_resolver(session, settings),
                FrozenEvaluationAccess(session),
            )
            prepared = await adapter.prepare(
                old.owner_id, candidate_input(run, candidate.configuration_version_id), case
            )
            assert (
                prepared.configuration.generation_profile.profile_id
                == candidate.generation_profile_id
            )
            assert prepared.request.top_k == 7
            assert prepared.request.history[0].content == "Synthetic context."
            assert prepared.resolved_scope.active_only is False
            assert prepared.resolved_scope.authorized_documents
            await prepared.frozen_access(prepared.resolved_scope.authorized_documents)
            build_ids = [
                item.index_build_id for item in prepared.resolved_scope.authorized_documents
            ]
            original = (
                await session.execute(
                    select(RagIndexBuildRecord.id, RagIndexBuildRecord.is_active).where(
                        RagIndexBuildRecord.id.in_(build_ids),
                    )
                )
            ).all()
            savepoint = await session.begin_nested()
            try:
                await session.execute(
                    update(RagIndexBuildRecord)
                    .where(RagIndexBuildRecord.id.in_(build_ids))
                    .values(is_active=False)
                )
                await prepared.frozen_access(prepared.resolved_scope.authorized_documents)
            finally:
                await savepoint.rollback()
            assert (
                await session.execute(
                    select(RagIndexBuildRecord.id, RagIndexBuildRecord.is_active).where(
                        RagIndexBuildRecord.id.in_(build_ids),
                    )
                )
            ).all() == original
            for value in ("  Approved\tresult\n", "Straße V", "\vVv\f", "ＡＢＣ", "한글　문맥"):
                actual = await session.scalar(
                    text("SELECT rag_normalize_proposition(:value)"), {"value": value}
                )
                assert actual == _normalized(value)
    finally:
        await frozen.close()
        await engine.dispose()
