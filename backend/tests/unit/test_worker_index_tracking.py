from uuid import UUID, uuid4

import pytest

from ai_workshop.config import Settings
from ai_workshop.labs.rag.indexing.tracked_elasticsearch import IndexPreparationFailed
from ai_workshop.labs.rag.indexing.tracking_contracts import IndexTrackingError
from ai_workshop.labs.rag.ingestion.domain import RagIngestionError
from ai_workshop.worker import RAG_INGESTION_TASK, _rag_error, create_celery


@pytest.mark.parametrize("code", ["rag_index_attempt_busy", "rag_index_writer_unconfirmed"])
@pytest.mark.parametrize("typed", [False, True])
def test_index_unconfirmed_delivery_never_fails_owner_or_retries(code: str, typed: bool) -> None:
    class Workflow:
        runs = 0
        failures = 0

        async def run(self, job_id: UUID) -> UUID:
            self.runs += 1
            if typed:
                raise IndexTrackingError(code)
            raise RagIngestionError(code, "synthetic-private-value", retryable=False)

        async def fail(self, job_id: UUID, *, error_code: str, error_message: str) -> None:
            self.failures += 1

    workflow = Workflow()
    app = create_celery(
        Settings(_env_file=None, environment="test", secret_key="x" * 32),
        rag_workflow_factory=lambda _: workflow,  # type: ignore[arg-type,return-value]
    )
    task = app.tasks[RAG_INGESTION_TASK]
    if code == "rag_index_attempt_busy":
        task.delay(str(uuid4()))
    else:
        with pytest.raises(RuntimeError, match=code) as captured:
            task.delay(str(uuid4()))
        assert captured.value.__context__ is None
        assert captured.value.__cause__ is None
        assert "synthetic-private-value" not in str(captured.value)
    assert workflow.runs == 1
    assert workflow.failures == 0


def test_only_confirmed_closed_observation_failure_is_retryable() -> None:
    assert _rag_error(
        IndexPreparationFailed(
            "rag_index_observation_failed",
            writer_confirmed_ended=True,
        )
    ) == ("rag_index_observation_failed", True)
    assert _rag_error(
        IndexPreparationFailed(
            "rag_index_writer_unconfirmed",
            writer_confirmed_ended=False,
        )
    ) == ("rag_index_writer_unconfirmed", False)
    assert _rag_error(
        IndexPreparationFailed(
            "rag_index_identity_conflict",
            writer_confirmed_ended=True,
        )
    ) == ("rag_index_identity_conflict", False)
