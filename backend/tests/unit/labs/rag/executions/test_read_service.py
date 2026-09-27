from datetime import UTC, datetime
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.conversations.domain import Turn
from ai_workshop.labs.rag.executions.read_repository import MonitoringEntry
from ai_workshop.labs.rag.executions.schemas import ExecutionSearchRequest
from ai_workshop.labs.rag.executions.service import ExecutionReadService
from ai_workshop.shared.errors import AppError


class Repository:
    def __init__(self, rows):
        self.rows = rows

    async def usage(self, actor, execution):
        return []

    async def entries(self, actor):
        for row in self.rows:
            if row.owner_id == actor:
                yield row

    async def find(self, actor, id, *, legacy=False):
        return next((r for r in self.rows if r.owner_id == actor and r.turn.id == id), None)


class Access:
    async def visible(self, actor, turn, *, external=False):
        return turn.query != "hidden"


def entry(actor, query="synthetic question", dependencies=()):
    now = datetime.now(UTC)
    turn = Turn(
        uuid4(),
        uuid4(),
        1,
        "completed",
        query,
        {},
        "",
        "",
        1,
        now,
        now,
        {"generation": {"status": "insufficient_evidence", "validation_token": "SECRET"}},
        dependencies=list(dependencies),
    )
    return MonitoringEntry(actor, uuid4(), uuid4(), "test-domain", turn, None)


@pytest.mark.asyncio
async def test_owner_and_current_dependencies_before_paging():
    actor = uuid4()
    hidden = entry(actor, "hidden")
    dependent = entry(actor, dependencies=[hidden.turn.id])
    visible = entry(actor)
    service = ExecutionReadService(
        Repository([hidden, dependent, entry(uuid4()), visible]), Access()
    )
    result = await service.search(actor, ExecutionSearchRequest(limit=1))
    assert result.total == 1
    assert result.items[0].id == visible.turn.id
    assert result.duration_missing == 1
    assert result.median_ms is None


@pytest.mark.asyncio
async def test_hidden_query_does_not_change_aggregate():
    actor = uuid4()
    service = ExecutionReadService(Repository([entry(actor, "hidden")]), Access())
    assert (await service.search(actor, ExecutionSearchRequest(query="hidden"))).total == 0


@pytest.mark.asyncio
async def test_legacy_has_no_invented_stage_and_excludes_token():
    actor = uuid4()
    row = entry(actor)
    service = ExecutionReadService(Repository([row]), Access())
    result = await service.legacy(actor, row.turn.id)
    assert all(stage.state == "unrecorded" for stage in result.stages)
    assert "SECRET" not in result.model_dump_json()
    assert result.quality_status == "unreviewed"
    with pytest.raises(AppError):
        await service.legacy(uuid4(), row.turn.id)


@pytest.mark.asyncio
async def test_equal_timestamps_cursor_no_duplicates():
    actor = uuid4()
    rows = [entry(actor) for _ in range(3)]
    for row in rows:
        row.turn.created_at = rows[0].turn.created_at
    service = ExecutionReadService(Repository(rows), Access())
    first = await service.search(actor, ExecutionSearchRequest(limit=2))
    second = await service.search(actor, ExecutionSearchRequest(limit=2, cursor=first.next_cursor))
    assert len({r.id for r in first.items + second.items}) == 3
    assert first.total == second.total == 3


@pytest.mark.asyncio
async def test_deletion_during_authorization_excludes_question_and_aggregate():
    actor = uuid4()
    row = entry(actor)
    repository = Repository([row])

    class DeletingAccess(Access):
        async def visible(self, actor, turn, **kwargs):
            repository.rows.clear()
            return True

    result = await ExecutionReadService(repository, DeletingAccess()).search(
        actor, ExecutionSearchRequest()
    )
    assert result.total == 0
    assert not result.items


@pytest.mark.asyncio
async def test_detail_revalidates_dependency_revoked_after_enumeration():
    actor = uuid4()
    parent = entry(actor)
    child = entry(actor, dependencies=[parent.turn.id])
    child.conversation_id = parent.conversation_id

    class RevokingAccess(Access):
        revoked = False

        async def visible(self, actor, turn, **kwargs):
            return not (self.revoked and turn.id == parent.turn.id)

    access = RevokingAccess()

    class RevokingRepository(Repository):
        async def find(self, actor, id, *, legacy=False):
            access.revoked = True
            return await super().find(actor, id, legacy=legacy)

    service = ExecutionReadService(RevokingRepository([parent, child]), access)
    with pytest.raises(AppError) as caught:
        await service.legacy(actor, child.turn.id)
    assert caught.value.status_code == 404
