"""Shared classification only; callers retain their distinct retry/ownership policy."""

from sqlalchemy.exc import DisconnectionError, OperationalError, TimeoutError

from ai_workshop.labs.rag.indexing.tracked_elasticsearch import IndexPreparationFailed
from ai_workshop.labs.rag.indexing.tracking_contracts import IndexTrackingError
from ai_workshop.labs.rag.ingestion.domain import RagIngestionError
from ai_workshop.labs.rag.ocr.contracts import OcrRuntimeError
from ai_workshop.labs.rag.parsing.contracts import ParsingError


def classify_ingestion_error(exc: Exception) -> tuple[str, bool]:
    if isinstance(exc, IndexPreparationFailed):
        return exc.code, (exc.writer_confirmed_ended and exc.code == "rag_index_observation_failed")
    if isinstance(exc, IndexTrackingError):
        return exc.code, False
    if isinstance(exc, RagIngestionError):
        return exc.code, exc.retryable
    if isinstance(exc, (ParsingError, OcrRuntimeError)):
        return exc.code, False
    if isinstance(exc, (OperationalError, TimeoutError, DisconnectionError)):
        return "database_transient", True
    if isinstance(exc, OSError):
        return "parser_unavailable", True
    return "rag_ingestion_failed", False
