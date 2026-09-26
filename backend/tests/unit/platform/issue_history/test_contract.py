from uuid import uuid4

import pytest
from pydantic import ValidationError

from ai_workshop.platform.issue_history.schemas import DocumentCreate, IssueCreate


def test_document_utf8_byte_limit():
    with pytest.raises(ValidationError):
        DocumentCreate(request_id=uuid4(), title="Document", content="한" * 200000)


def test_issue_rejects_invalid_status():
    with pytest.raises(ValidationError):
        IssueCreate(
            request_id=uuid4(), issue_key="TEST-1", category_id=uuid4(), title="Test", status="done"
        )


def test_document_surrogate_is_validation_error():
    with pytest.raises(ValidationError):
        DocumentCreate(request_id=uuid4(), title="Document", content="\ud800")
