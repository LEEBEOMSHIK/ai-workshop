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


def test_document_vectors_reused_across_selection_and_diagnostics_with_copies():
    delegate = Mock(dimension=2)
    vectors = {"first": [1.0, 0.0], "second": [0.0, 1.0]}
    delegate.encode_documents.side_effect = lambda texts: [vectors[text] for text in texts]
    cached = RequestScopedEmbedding(delegate)

    selected = cached.encode_documents(["first", "second", "first"])
    selected[0][0] = 99
    assert selected[2] == [1.0, 0.0]
    assert cached.encode_documents(["second", "first"]) == [[0.0, 1.0], [1.0, 0.0]]
    delegate.encode_documents.assert_called_once_with(["first", "second"])
    assert RequestScopedEmbedding(delegate).encode_documents(["first"]) == [[1.0, 0.0]]
    assert delegate.encode_documents.call_count == 2


def test_document_cache_encodes_only_new_text_and_keeps_query_namespace_separate():
    delegate = Mock(dimension=2)
    delegate.encode_documents.side_effect = [[[1.0, 0.0]], [[0.0, 1.0]]]
    delegate.encode_query.return_value = [-1.0, 0.0]
    cached = RequestScopedEmbedding(delegate)
    cached.encode_documents(["first"])
    assert cached.encode_documents(["second", "first"]) == [[0.0, 1.0], [1.0, 0.0]]
    delegate.encode_documents.assert_called_with(["second"])
    assert cached.encode_query("first") == [-1.0, 0.0]


@pytest.mark.parametrize("failed", [RuntimeError("unavailable"), [[1.0, 0.0]]])
def test_failed_or_incomplete_document_batch_is_not_cached(failed):
    delegate = Mock(dimension=2)
    delegate.encode_documents.side_effect = [failed, [[1.0, 0.0], [0.0, 1.0]]]
    cached = RequestScopedEmbedding(delegate)
    with pytest.raises((RuntimeError, ValueError)):
        cached.encode_documents(["first", "second"])
    assert cached.encode_documents(["first", "second"]) == [[1.0, 0.0], [0.0, 1.0]]
    first_call, second_call = delegate.encode_documents.call_args_list
    assert first_call == second_call


def test_empty_document_batch_does_not_load_model():
    delegate = Mock(dimension=2)
    assert RequestScopedEmbedding(delegate).encode_documents([]) == []
    delegate.encode_documents.assert_not_called()
