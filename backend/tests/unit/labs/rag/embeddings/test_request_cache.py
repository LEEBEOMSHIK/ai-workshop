from unittest.mock import Mock

import pytest

from ai_workshop.labs.rag.embeddings.request_cache import RequestScopedEmbedding


def test_query_cache_is_request_local_and_returns_copies():
    delegate = Mock(dimension=2)
    delegate.encode_query.return_value = [1.0, 0.0]
    cached = RequestScopedEmbedding(delegate)
    cached.encode_query("question")[0] = 99
    assert cached.encode_query("question") == [1.0, 0.0]
    assert delegate.encode_query.call_count == 1
    assert RequestScopedEmbedding(delegate).encode_query("question") == [1.0, 0.0]
    assert delegate.encode_query.call_count == 2


def test_failed_query_is_not_cached():
    delegate = Mock(dimension=2)
    delegate.encode_query.side_effect = [RuntimeError("unavailable"), [1.0, 0.0]]
    cached = RequestScopedEmbedding(delegate)
    with pytest.raises(RuntimeError):
        cached.encode_query("question")
    assert cached.encode_query("question") == [1.0, 0.0]
