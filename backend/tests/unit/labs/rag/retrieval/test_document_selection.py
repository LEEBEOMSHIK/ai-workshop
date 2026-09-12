from uuid import uuid4

import pytest
from pydantic import ValidationError

from ai_workshop.labs.rag.domains.schemas import DomainSearchRequest
from ai_workshop.labs.rag.retrieval.selection import normalize_document_ids
from ai_workshop.labs.rag.search.schemas import SearchRequest
from ai_workshop.shared.errors import AppError


@pytest.mark.parametrize("request_type", [SearchRequest, DomainSearchRequest])
@pytest.mark.parametrize("invalid", [None, []])
def test_explicit_empty_document_selection_is_rejected(request_type, invalid) -> None:
    base = {
        "query": "합성 질문",
        "workspace_ids": [uuid4()],
        (
            "configuration_id"
            if request_type is SearchRequest
            else "connection_version_id"
        ): uuid4(),
    }

    with pytest.raises(ValidationError):
        request_type(**base, document_ids=invalid)


@pytest.mark.parametrize("request_type", [SearchRequest, DomainSearchRequest])
def test_omitted_document_selection_preserves_unrestricted_scope(request_type) -> None:
    base = {
        "query": "합성 질문",
        "workspace_ids": [uuid4()],
        (
            "configuration_id"
            if request_type is SearchRequest
            else "connection_version_id"
        ): uuid4(),
    }

    request = request_type(**base)

    assert request.document_ids is None


@pytest.mark.parametrize("request_type", [SearchRequest, DomainSearchRequest])
def test_non_empty_document_selection_is_accepted(request_type) -> None:
    document_id = uuid4()
    base = {
        "query": "합성 질문",
        "workspace_ids": [uuid4()],
        "document_ids": [document_id],
        (
            "configuration_id"
            if request_type is SearchRequest
            else "connection_version_id"
        ): uuid4(),
    }

    request = request_type(**base)

    assert request.document_ids == [document_id]


def test_document_selection_limit_counts_unique_documents() -> None:
    first, second = uuid4(), uuid4()

    assert normalize_document_ids(
        [second, first, second],
        max_count=2,
    ) == tuple(sorted((first, second), key=str))

    with pytest.raises(AppError) as caught:
        normalize_document_ids([first, second], max_count=1)

    assert (caught.value.code, caught.value.status_code) == (
        "document_selection_limit_exceeded",
        422,
    )


def test_raw_duplicate_document_selection_is_bounded() -> None:
    document_id = uuid4()

    with pytest.raises(AppError) as caught:
        normalize_document_ids([document_id] * 11, max_count=1)

    assert (caught.value.code, caught.value.status_code) == (
        "document_selection_limit_exceeded",
        422,
    )
