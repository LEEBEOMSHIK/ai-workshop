from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from ai_workshop.labs.rag.evaluation.domain import EvaluationRunStatus
from ai_workshop.labs.rag.evaluation.service import (
    EvaluationApplicationService,
    EvaluationRunView,
)
from ai_workshop.learning_composition import (
    EvaluationReferenceHandler,
    LearningRecordReferenceHandler,
    LearningReferenceResolver,
    ServiceReferenceDefinition,
    ServiceReferenceHandler,
)
from ai_workshop.platform.learning.domain import LearningRecord
from ai_workshop.platform.learning.references import ReferenceStatus
from ai_workshop.platform.learning.schemas import LearningDraft, ReferenceKey

from .test_service import MemoryLearningRepository


class EvaluationLookupRepository:
    def __init__(self, run: EvaluationRunView | None) -> None:
        self.run = run

    async def detail_visible(
        self, run_id: UUID, actor_id: UUID
    ) -> EvaluationRunView | None:
        if self.run is None or self.run.id != run_id or self.run.owner_id != actor_id:
            return None
        return self.run


def evaluation_run(owner_id: UUID) -> EvaluationRunView:
    return EvaluationRunView(
        id=uuid4(),
        owner_id=owner_id,
        created_at=datetime(2019, 3, 4, 5, 6, 7, tzinfo=UTC),
        dataset_snapshot_id=uuid4(),
        evaluation_policy_version_id=None,
        status=EvaluationRunStatus.COMPLETED,
        fixture_sha256="a" * 64,
        document_snapshot_sha256="b" * 64,
        query_set_sha256="c" * 64,
        execution_snapshot_sha256="d" * 64,
        runtime_environment={"private": "must not become a label"},
        worker_runtime_environment=None,
        metric_definition_version=1,
        retrieval_k=10,
        repetition_count=2,
        failure="private failure",
        candidates=(),
    )


@pytest.mark.asyncio
async def test_evaluation_handler_uses_actual_application_service_permission_path() -> None:
    owner_id = uuid4()
    run = evaluation_run(owner_id)
    application_repository = EvaluationLookupRepository(run)
    evaluation_service = EvaluationApplicationService(
        application_repository  # type: ignore[arg-type]
    )
    resolver = LearningReferenceResolver(
        {
            "rag.evaluation": EvaluationReferenceHandler(evaluation_service),
        }
    )
    key = ReferenceKey(kind="rag.evaluation", target=str(run.id))

    visible = await resolver.resolve(owner_id, key)
    denied = await resolver.resolve(uuid4(), key)
    missing = await resolver.resolve(owner_id, key.model_copy(update={"target": str(uuid4())}))

    assert visible.status is ReferenceStatus.AVAILABLE
    assert visible.label == "RAG evaluation · completed"
    assert visible.href is None
    assert "private" not in visible.label
    assert denied.status is ReferenceStatus.UNAVAILABLE
    assert denied.key is None
    assert missing.status is ReferenceStatus.UNAVAILABLE


@pytest.mark.asyncio
async def test_allowlist_rejects_unknown_raw_and_malformed_reference_targets() -> None:
    resolver = LearningReferenceResolver(
        {
            "service": ServiceReferenceHandler(
                (
                    ServiceReferenceDefinition(
                        key="rag.search",
                        label="RAG search",
                        href="/workshop/rag/search",
                    ),
                )
            )
        }
    )
    actor_id = uuid4()

    available = await resolver.resolve(
        actor_id, ReferenceKey(kind="service", target="rag.search")
    )
    assert available.status is ReferenceStatus.AVAILABLE
    assert available.href == "/workshop/rag/search"

    for key in (
        ReferenceKey(kind="unknown", target="anything"),
        ReferenceKey(kind="service", target="https://private.invalid"),
        ReferenceKey(kind="service", target="C:\\private\\file"),
        ReferenceKey(kind="service", target="select * from users"),
        ReferenceKey(kind="service", target="rag.search", version="1"),
        ReferenceKey(kind="rag.evaluation", target="not-a-uuid"),
        ReferenceKey(kind="learning.record", target=str(uuid4()), version="0"),
    ):
        assert (await resolver.resolve(actor_id, key)).status is ReferenceStatus.UNAVAILABLE


@pytest.mark.asyncio
async def test_circular_record_references_resolve_only_metadata_without_recursion() -> None:
    actor_id = uuid4()
    a = LearningRecord.create(
        owner_id=actor_id,
        draft=LearningDraft(title="A", body="A private body", kind="note"),
    )
    b = LearningRecord.create(
        owner_id=actor_id,
        draft=LearningDraft(
            title="B",
            body="B private body",
            kind="note",
            references=(ReferenceKey(kind="learning.record", target=str(a.id)),),
        ),
    )
    repository = MemoryLearningRepository(a, b)
    handler = LearningRecordReferenceHandler(repository)
    resolver = LearningReferenceResolver({"learning.record": handler})

    view = await resolver.resolve(
        actor_id, ReferenceKey(kind="learning.record", target=str(b.id))
    )

    assert view.label == "B"
    assert view.href == f"/workshop/learning/{b.id}"
    assert "private body" not in repr(view)
