import importlib

import pytest

from ai_workshop.labs.rag.indexing.tracked_elasticsearch import IndexPreparationFailed
from ai_workshop.labs.rag.indexing.tracking_contracts import IndexTrackingError
from ai_workshop.labs.rag.ingestion.domain import RagIngestionBusy, RagIngestionError


def test_shared_policy_exists() -> None:
    assert importlib.util.find_spec("ai_workshop.labs.rag.ingestion.error_policy") is not None


@pytest.mark.parametrize(
    "error,expected",
    [
        (RagIngestionBusy(), ("artifact_attempt_busy", False)),
        (RagIngestionError("parse_failed", "PRIVATE", retryable=False), ("parse_failed", False)),
        (IndexTrackingError("rag_index_attempt_busy"), ("rag_index_attempt_busy", False)),
        (
            IndexPreparationFailed("rag_index_writer_unconfirmed", writer_confirmed_ended=False),
            ("rag_index_writer_unconfirmed", False),
        ),
        (
            IndexPreparationFailed("rag_index_observation_failed", writer_confirmed_ended=True),
            ("rag_index_observation_failed", True),
        ),
        (OSError("PRIVATE"), ("parser_unavailable", True)),
        (RuntimeError("PRIVATE"), ("rag_ingestion_failed", False)),
    ],
)
def test_normal_worker_classification_is_preserved(
    error: Exception,
    expected: tuple[str, bool],
) -> None:
    shared = importlib.import_module("ai_workshop.labs.rag.ingestion.error_policy")
    worker = importlib.import_module("ai_workshop.worker")
    assert shared.classify_ingestion_error(error) == expected
    assert worker._rag_error(error) == expected
