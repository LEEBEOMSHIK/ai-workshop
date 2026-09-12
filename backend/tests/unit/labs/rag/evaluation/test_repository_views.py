from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.sql import Select

from ai_workshop.labs.rag.evaluation.domain import EvaluationRunStatus, load_evaluation_dataset
from ai_workshop.labs.rag.evaluation.models import (
    EvaluationDatasetRecord,
    EvaluationRunConfigurationRecord,
    EvaluationRunRecord,
)
from ai_workshop.labs.rag.evaluation.repository import (
    SqlAlchemyEvaluationApplicationRepository,
)
from ai_workshop.labs.rag.evaluation.schemas import EvaluationRunResponse
from ai_workshop.platform.workspaces.models import WorkspaceRecord
from tests.unit.labs.rag.evaluation.test_dataset_fixture import FIXTURE

OWNER_ID = UUID("10000000-0000-0000-0000-000000000001")
OTHER_OWNER_ID = UUID("10000000-0000-0000-0000-000000000002")
RUN_ID = UUID("20000000-0000-0000-0000-000000000001")
OTHER_RUN_ID = UUID("20000000-0000-0000-0000-000000000002")
HISTORICAL_CREATED_AT = datetime(2018, 2, 3, 4, 5, 6, 789000, tzinfo=UTC)
NEWER_CREATED_AT = datetime(2020, 2, 3, 4, 5, 6, 789000, tzinfo=UTC)


def evaluation_record(*, run_id: UUID, owner_id: UUID, created_at: datetime) -> EvaluationRunRecord:
    return EvaluationRunRecord(
        id=run_id,
        owner_id=owner_id,
        created_at=created_at,
        updated_at=created_at,
        dataset_snapshot_id=UUID("30000000-0000-0000-0000-000000000001"),
        evaluation_policy_version_id=None,
        status=EvaluationRunStatus.COMPLETED.value,
        fixture_sha256="1" * 64,
        document_snapshot_sha256="2" * 64,
        query_set_sha256="3" * 64,
        execution_snapshot={},
        execution_snapshot_bytes=b"{}",
        execution_snapshot_sha256="4" * 64,
        runtime_environment={"python": "3.13"},
        worker_runtime_environment=None,
        metric_definition_version=1,
        retrieval_k=10,
        repetition_count=2,
        candidate_count=1,
        failure=None,
    )


class OwnerFilteringSession:
    def __init__(self, runs: Sequence[EvaluationRunRecord], *, read_allowed: bool = True) -> None:
        self.runs = tuple(runs)
        self.read_allowed = read_allowed
        self.dataset = load_evaluation_dataset(FIXTURE.read_bytes())

    @staticmethod
    def _bound_values(statement: Select[Any]) -> set[object]:
        return set(statement.compile().params.values())

    async def scalar(
        self, statement: Select[Any]
    ) -> EvaluationRunRecord | EvaluationDatasetRecord | None:
        if statement.column_descriptions[0].get("entity") is EvaluationDatasetRecord:
            dataset = self.dataset
            return EvaluationDatasetRecord(
                id=self.runs[0].dataset_snapshot_id,
                owner_id=self.runs[0].owner_id,
                name=dataset.name,
                version=dataset.version,
                fixture_bytes=FIXTURE.read_bytes(),
                fixture_sha256=dataset.fixture_sha256,
                document_snapshot=[dict(item) for item in dataset.document_snapshot],
                document_snapshot_bytes=dataset.document_snapshot_bytes,
                document_snapshot_sha256=dataset.document_snapshot_sha256,
                query_set_bytes=dataset.query_set_bytes,
                query_set_sha256=dataset.query_set_sha256,
                case_count=len(dataset.cases),
            )
        values = self._bound_values(statement)
        run = next((item for item in self.runs if item.id in values), None)
        if run is None:
            return None
        owner_filters = {
            value
            for value in values
            if isinstance(value, UUID) and value not in {item.id for item in self.runs}
        }
        return run if not owner_filters or run.owner_id in owner_filters else None

    async def scalars(self, statement: Select[Any]) -> Sequence[Any]:
        entity = statement.column_descriptions[0].get("entity")
        if entity is WorkspaceRecord:
            return (
                tuple(
                    {
                        workspace
                        for case in self.dataset.cases
                        for workspace in case.permission_scenario.workspace_ids
                    }
                )
                if self.read_allowed
                else ()
            )
        if entity is EvaluationRunConfigurationRecord:
            return ()
        assert entity is EvaluationRunRecord
        values = self._bound_values(statement)
        owner_filters = {value for value in values if isinstance(value, UUID)}
        visible = [
            item for item in self.runs if not owner_filters or item.owner_id in owner_filters
        ]
        return tuple(sorted(visible, key=lambda item: (-item.created_at.timestamp(), item.id)))


@pytest.mark.asyncio
async def test_repository_view_preserves_historical_persisted_created_at() -> None:
    run = evaluation_record(
        run_id=RUN_ID,
        owner_id=OWNER_ID,
        created_at=HISTORICAL_CREATED_AT,
    )
    repository = SqlAlchemyEvaluationApplicationRepository(
        OwnerFilteringSession((run,))  # type: ignore[arg-type]
    )

    view = await repository._view(run)
    response = EvaluationRunResponse.from_domain(view)

    assert view.created_at == HISTORICAL_CREATED_AT
    assert response.created_at == HISTORICAL_CREATED_AT


@pytest.mark.asyncio
async def test_repository_detail_keeps_owner_filter_and_persisted_created_at() -> None:
    run = evaluation_record(
        run_id=RUN_ID,
        owner_id=OWNER_ID,
        created_at=HISTORICAL_CREATED_AT,
    )
    repository = SqlAlchemyEvaluationApplicationRepository(
        OwnerFilteringSession((run,))  # type: ignore[arg-type]
    )

    assert await repository.detail_visible(RUN_ID, OTHER_OWNER_ID) is None
    visible = await repository.detail_visible(RUN_ID, OWNER_ID)

    assert visible is not None
    assert visible.created_at == HISTORICAL_CREATED_AT


@pytest.mark.asyncio
async def test_repository_list_keeps_owner_filter_and_created_at_order() -> None:
    older = evaluation_record(
        run_id=RUN_ID,
        owner_id=OWNER_ID,
        created_at=HISTORICAL_CREATED_AT,
    )
    newer = evaluation_record(
        run_id=OTHER_RUN_ID,
        owner_id=OWNER_ID,
        created_at=NEWER_CREATED_AT,
    )
    hidden = evaluation_record(
        run_id=UUID("20000000-0000-0000-0000-000000000003"),
        owner_id=OTHER_OWNER_ID,
        created_at=datetime(2022, 2, 3, 4, 5, 6, 789000, tzinfo=UTC),
    )
    repository = SqlAlchemyEvaluationApplicationRepository(
        OwnerFilteringSession((older, hidden, newer))  # type: ignore[arg-type]
    )

    visible = await repository.list_visible(OWNER_ID, limit=20)

    assert [item.id for item in visible] == [OTHER_RUN_ID, RUN_ID]
    assert [item.created_at for item in visible] == [
        NEWER_CREATED_AT,
        HISTORICAL_CREATED_AT,
    ]


@pytest.mark.asyncio
async def test_revoked_workspace_hides_evaluation_results_even_from_run_owner() -> None:
    run = evaluation_record(run_id=RUN_ID, owner_id=OWNER_ID, created_at=HISTORICAL_CREATED_AT)
    repository = SqlAlchemyEvaluationApplicationRepository(
        OwnerFilteringSession((run,), read_allowed=False)  # type: ignore[arg-type]
    )
    assert await repository.detail_visible(RUN_ID, OWNER_ID) is None
    assert await repository.list_visible(OWNER_ID, limit=20) == ()
