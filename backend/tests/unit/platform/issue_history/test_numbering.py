from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from ai_workshop.platform.issue_history.models import IssueIdentifier
from ai_workshop.platform.issue_history.repository import IssueRepository
from ai_workshop.shared.errors import AppError


async def test_allocator_skips_reserved_import_and_existing_legacy_keys():
    session = MagicMock()
    session.scalar = AsyncMock(side_effect=[1, 2, 3])
    session.get = AsyncMock(
        side_effect=[IssueIdentifier(key="ISSUE-00002", issue_id=uuid4()), None]
    )
    repository = IssueRepository(session)
    assert await repository.allocate_key({"ISSUE-00001"}) == "ISSUE-00003"
    assert session.scalar.await_count == 3


async def test_allocator_requires_migrated_counter():
    session = MagicMock()
    session.scalar = AsyncMock(return_value=None)
    with pytest.raises(AppError) as caught:
        await IssueRepository(session).allocate_key()
    assert caught.value.status_code == 503


async def test_detail_resolves_current_and_previous_keys():
    identity = uuid4()
    session = MagicMock()
    session.get = AsyncMock(
        side_effect=[
            IssueIdentifier(key="ISSUE-00001", issue_id=identity),
            IssueIdentifier(key="RAG-0001", issue_id=identity),
            None,
        ]
    )
    repository = IssueRepository(session)
    assert await repository.resolve_issue_id("ISSUE-00001") == identity
    assert await repository.resolve_issue_id("RAG-0001") == identity
    assert await repository.resolve_issue_id("missing") is None
    assert await repository.resolve_issue_id(identity) == identity
