from collections.abc import AsyncGenerator
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from ai_workshop.labs.rag.executions.read_repository import (
    MonitoringEntry,
    SqlAlchemyMonitoringRepository,
)


@pytest.mark.parametrize("found", [False, True])
async def test_find_closes_query_iterator_before_returning(found: bool) -> None:
    closed = False
    entry = Mock(spec=MonitoringEntry)

    class Repository(SqlAlchemyMonitoringRepository):
        async def _entries(
            self, actor_id: UUID, id: UUID | None = None, *, legacy: bool = False
        ) -> AsyncGenerator[MonitoringEntry]:
            nonlocal closed
            try:
                if found:
                    yield entry
            finally:
                closed = True

    repository = Repository(async_sessionmaker())
    result = await repository.find(uuid4(), uuid4())

    assert result is (entry if found else None)
    assert closed is True
