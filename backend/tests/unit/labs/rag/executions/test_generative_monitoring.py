from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.evaluation import generative_monitoring as module
from ai_workshop.shared.errors import AppError


def setup_reader(monkeypatch, groups):
    now = datetime.now(UTC)
    rows, views = [], {}
    for count in groups:
        run_id = uuid4()
        attempts = []
        for _ in range(count):
            execution_id, attempt_id = uuid4(), uuid4()
            rows.append(
                (
                    SimpleNamespace(
                        id=execution_id,
                        evaluation_attempt_id=attempt_id,
                        created_at=now,
                        ended_at=now + timedelta(seconds=2),
                        status="completed",
                        complete=True,
                    ),
                    run_id,
                )
            )
            attempts.append(
                SimpleNamespace(
                    id=attempt_id,
                    execution_id=execution_id,
                    query="Synthetic question",
                    configuration_version_id=uuid4(),
                    error_code=None,
                    observation=SimpleNamespace(generation_status="answered", failure_stage=None),
                    metrics=SimpleNamespace(correctness="passed"),
                    sources=[
                        SimpleNamespace(document_id="one"),
                        SimpleNamespace(document_id="one"),
                    ],
                )
            )
        views[run_id] = SimpleNamespace(attempts=attempts)
    session = AsyncMock()
    result = MagicMock()
    result.all.return_value = rows
    session.execute.return_value = result
    scalars = MagicMock()
    scalars.all.return_value = [r.id for r, _ in rows]
    session.scalars.return_value = scalars
    factory = MagicMock()
    factory.return_value.__aenter__.return_value = session
    reader = module.GenerativeMonitoringReader(factory)
    detail = AsyncMock(side_effect=AssertionError("List must not construct detail or usage"))
    monkeypatch.setattr(reader, "detail", detail)

    async def read(session, actor, run_id):
        return views[run_id]

    read_mock = AsyncMock(side_effect=read)
    monkeypatch.setattr(module, "run_detail", read_mock)
    return reader, views, read_mock, detail


async def test_summaries_read_each_run_once_and_do_not_fetch_details(monkeypatch):
    reader, views, read, detail = setup_reader(monkeypatch, [3, 2])
    result = await reader.summaries(uuid4())
    assert len(result) == 5
    assert read.await_count == 2
    assert {call.args[2] for call in read.await_args_list} == set(views)
    assert all(r.document_count == 1 and r.duration_ms == 2000 for r in result)
    assert all(r.quality_status == "passed" and r.answer_status == "answered" for r in result)
    detail.assert_not_awaited()


async def test_revoked_run_is_skipped_and_rechecked_on_next_request(monkeypatch):
    reader, views, read, _ = setup_reader(monkeypatch, [2])
    actor = uuid4()
    assert len(await reader.summaries(actor)) == 2
    read.side_effect = AppError("not_found", "Unavailable", 404)
    assert await reader.summaries(actor) == []
    assert read.await_count == 2
    assert all(call.args[1] == actor for call in read.await_args_list)


async def test_missing_or_reassigned_execution_is_not_exposed(monkeypatch):
    reader, views, _, _ = setup_reader(monkeypatch, [2])
    view = next(iter(views.values()))
    view.attempts[0].execution_id = None
    view.attempts.pop()
    assert await reader.summaries(uuid4()) == []


async def test_unexpected_authorization_error_is_not_hidden(monkeypatch):
    reader, _, read, _ = setup_reader(monkeypatch, [1])
    read.side_effect = AppError("database_unavailable", "Unavailable", 503)
    with pytest.raises(AppError, match="Unavailable"):
        await reader.summaries(uuid4())

async def test_one_revoked_run_does_not_hide_other_authorized_run(monkeypatch):
    reader, views, read, _ = setup_reader(monkeypatch, [2, 1])
    revoked = next(iter(views))

    async def current_view(session, actor, run_id):
        if run_id == revoked:
            raise AppError("not_found", "Unavailable", 404)
        return views[run_id]

    read.side_effect = current_view
    rows = await reader.summaries(uuid4())
    assert len(rows) == 1
    assert read.await_count == 2


async def test_unfinished_execution_retains_missing_observation(monkeypatch):
    reader, views, _, _ = setup_reader(monkeypatch, [1])
    item = next(iter(views.values())).attempts[0]
    item.observation = None
    item.metrics = None
    item.sources = []
    row = (await reader.summaries(uuid4()))[0]
    assert row.answer_status is None
    assert row.failed_stage is None
    assert row.quality_status == "unreviewed"
    assert row.document_count == 0
