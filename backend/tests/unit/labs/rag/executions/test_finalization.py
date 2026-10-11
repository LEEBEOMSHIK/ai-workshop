from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.labs.rag.executions.domain import STAGES, ExecutionOutcome
from ai_workshop.labs.rag.executions.models import ExecutionRecord
from ai_workshop.labs.rag.executions.repository import finish_execution


def record() -> ExecutionRecord:
    return ExecutionRecord(
        id=uuid4(),
        actor_id=uuid4(),
        turn_id=uuid4(),
        status="running",
        complete=False,
        stages={stage: {"state": "completed"} for stage in STAGES},
    )


@pytest.mark.parametrize("gap", ["missing", "running", "unrecorded", "malformed"])
async def test_finalization_does_not_overwrite_missing_observation(gap: str) -> None:
    row = record()
    if gap == "missing":
        del row.stages["retrieval"]
    elif gap == "malformed":
        row.stages["retrieval"] = None
    else:
        row.stages["retrieval"] = {"state": gap}
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = row

    await finish_execution(
        session, row.id, ExecutionOutcome(state="failed", error_code="generation_failed")
    )

    assert row.status == "failed"
    assert row.error_code == "generation_failed"
    assert row.ended_at is not None
    assert row.complete is False


@pytest.mark.parametrize("reported_complete", [False, True])
async def test_failed_execution_can_have_complete_observations(reported_complete: bool) -> None:
    row = record()
    row.stages["generation"] = {"state": "failed", "reason": "generation_failed"}
    row.stages["citation_validation"] = {"state": "skipped"}
    row.stages["persistence"] = {"state": "skipped"}
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = row

    await finish_execution(
        session,
        row.id,
        ExecutionOutcome(
            state="failed", error_code="generation_failed", complete=reported_complete
        ),
    )

    assert row.complete is reported_complete
    assert row.stages["generation"]["state"] == "failed"


async def test_terminal_result_is_not_replaced_by_a_late_finish() -> None:
    row = record()
    row.status = "failed"
    row.error_code = "citation_validation_failed"
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = row

    await finish_execution(session, row.id, ExecutionOutcome(state="completed"))

    assert row.status == "failed"
    assert row.error_code == "citation_validation_failed"
