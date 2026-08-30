import pytest
from elastic_transport import (
    ApiError,
    ApiResponseMeta,
    ConnectionTimeout,
    HttpHeaders,
    NodeConfig,
)
from elastic_transport import (
    ConnectionError as ElasticsearchConnectionError,
)

from ai_workshop.labs.rag.indexing.service import (
    ActiveAliasTargetMismatchError,
    AliasActivationNotAcknowledgedError,
)
from ai_workshop.labs.rag.ingestion.stages import _classify_activation_error


def _api_error(status: int) -> ApiError:
    return ApiError(
        "synthetic Elasticsearch response",
        ApiResponseMeta(
            status=status,
            http_version="1.1",
            headers=HttpHeaders(),
            duration=0.0,
            node=NodeConfig("http", "localhost", 9200),
        ),
        {},
    )


@pytest.mark.parametrize(
    "error",
    [
        AliasActivationNotAcknowledgedError("not acknowledged"),
        ElasticsearchConnectionError("connection lost"),
        ConnectionTimeout("timed out"),
        _api_error(429),
        _api_error(500),
        _api_error(503),
    ],
)
def test_expected_transient_activation_failures_are_retryable(error: Exception) -> None:
    classified = _classify_activation_error(error)

    assert classified.code == "index_activation_failed"
    assert classified.retryable is True


@pytest.mark.parametrize(
    "error",
    [
        ActiveAliasTargetMismatchError("wrong target"),
        _api_error(400),
        _api_error(404),
    ],
)
def test_deterministic_activation_failures_are_terminal(error: Exception) -> None:
    classified = _classify_activation_error(error)

    assert classified.code == "index_activation_rejected"
    assert classified.retryable is False


def test_unexpected_generic_value_error_is_raised_unchanged() -> None:
    error = ValueError("programming bug in search-index port")

    with pytest.raises(ValueError) as exc_info:
        _classify_activation_error(error)

    assert exc_info.value is error
