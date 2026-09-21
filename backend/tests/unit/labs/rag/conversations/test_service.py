import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.conversations.domain import reserve_turn
from ai_workshop.labs.rag.conversations.schemas import ConversationTurnCreate
from ai_workshop.labs.rag.conversations.service import ConversationService
from ai_workshop.labs.rag.domains.schemas import DomainSearchResponse
from ai_workshop.labs.rag.generation.codex_admin_api import CodexInputApprovalRequest
from ai_workshop.shared.errors import AppError


class MemoryRepository:
    def __init__(self):
        self.items = {}
        self.domain = uuid4()
        self.lock = asyncio.Lock()

    async def domain_id(self, slug):
        return self.domain

    async def create(self, item):
        self.items[item.id] = deepcopy(item)

    async def list(self, owner_id, domain_id):
        return [
            deepcopy(item)
            for item in self.items.values()
            if item.owner_id == owner_id and item.domain_id == domain_id and not item.deleted_at
        ]

    async def record_termination(self, owner_id, domain_id, id, turn_id):
        async with self.lock:
            item = self.items.get(id)
            if (
                item
                and item.owner_id == owner_id
                and item.domain_id == domain_id
                and item.deleted_at
            ):
                for turn in item.turns:
                    if turn.id == turn_id:
                        turn.execution_terminated = True

    @asynccontextmanager
    async def locked(self, owner_id, domain_id, id):
        async with self.lock:
            item = self.items.get(id)
            if (
                item is None
                or item.owner_id != owner_id
                or item.domain_id != domain_id
                or item.deleted_at
            ):
                raise AppError("not_found", "Not found", 404)
            copy = deepcopy(item)
            yield copy
            self.items[id] = deepcopy(copy)


def response():
    return DomainSearchResponse.model_validate(
        {
            "status": "insufficient_evidence",
            "answer": None,
            "conflict_state": "none",
            "conflicts": [],
            "warnings": [],
            "related_sources": [],
            "configuration_version": {
                "configuration_id": str(uuid4()),
                "version_id": str(uuid4()),
                "version": 1,
            },
            "experimental": False,
            "resolved_query": "Question?",
            "selected_scope": None,
            "generation": {
                "status": "answered",
                "text": "Synthetic answer",
                "citations": [],
                "reason_codes": [],
                "turn_id": str(uuid4()),
                "validation_token": "token",
                "execution": None,
            },
            "domain_context": {
                "domain_id": str(uuid4()),
                "connection_version_id": str(uuid4()),
                "workspace_ids": [str(uuid4())],
                "folder_ids": [],
            },
        }
    )


@pytest.fixture
def setup():
    repo = MemoryRepository()
    access = SimpleNamespace(
        identity=AsyncMock(return_value="identity"), visible=AsyncMock(return_value=True)
    )
    domains = SimpleNamespace(detail_for_actor=AsyncMock(), resolve_search=AsyncMock())
    executor = SimpleNamespace(execute=AsyncMock(return_value=response()))
    service = ConversationService(repo, access, domains, executor)
    incoming = ConversationTurnCreate(
        request_id=uuid4(),
        expected_revision=1,
        query="Question?",
        connection_version_id=uuid4(),
        workspace_ids=[uuid4()],
    )
    return service, repo, access, executor, uuid4(), incoming


@pytest.mark.asyncio
async def test_owned_crud_and_foreign_owner_denial(setup):
    service, repo, _, _, actor, _ = setup
    created = await service.create("domain", actor, None)
    assert created.title.startswith("새 대화")
    assert len(await service.list_for_actor("domain", actor)) == 1
    stranger = uuid4()
    assert await service.list_for_actor("domain", stranger) == []
    for method, args in (
        (service.detail, ()),
        (service.rename, ("Title", 1)),
        (service.delete, (1,)),
        (service.cancel, (uuid4(),)),
    ):
        with pytest.raises(AppError) as exc:
            await method("domain", stranger, created.id, *args)
        assert exc.value.status_code == 404
    renamed = await service.rename("domain", actor, created.id, "Chosen title", 1)
    assert renamed.revision == 2
    await service.delete("domain", actor, created.id, 2)
    assert await service.list_for_actor("domain", actor) == []
    assert repo.items[created.id].deleted_at


@pytest.mark.asyncio
async def test_replay_saved_history_and_redaction_dependency_closure(setup):
    service, repo, access, executor, actor, incoming = setup
    created = await service.create("domain", actor, None)
    first = await service.submit("domain", actor, created.id, incoming)
    replay = await service.submit("domain", actor, created.id, incoming)
    assert replay == first and executor.execute.await_count == 1
    next_request = incoming.model_copy(
        update={"request_id": uuid4(), "expected_revision": first.revision}
    )
    second = await service.submit("domain", actor, created.id, next_request)
    history = executor.execute.call_args.kwargs["request"].history
    assert [item.role for item in history] == ["user", "assistant"]
    assert repo.items[created.id].turns[1].dependencies == [first.turns[0].id]
    access.visible.side_effect = lambda actor, turn, **kw: turn.id != first.turns[0].id
    hidden = await service.detail("domain", actor, created.id)
    assert all(
        turn.redacted and not turn.query and not turn.response and not turn.request_scope
        for turn in hidden.turns
    )
    third_request = next_request.model_copy(
        update={"request_id": uuid4(), "expected_revision": second.revision}
    )
    await service.submit("domain", actor, created.id, third_request)
    assert executor.execute.call_args.kwargs["request"].history == []


@pytest.mark.asyncio
async def test_cancel_and_late_completion_cannot_resurrect(setup):
    service, repo, _, executor, actor, incoming = setup
    created = await service.create("domain", actor, None)
    started, release = asyncio.Event(), asyncio.Event()

    async def execute(**kwargs):
        started.set()
        await release.wait()
        return response()

    executor.execute.side_effect = execute
    pending = asyncio.create_task(service.submit("domain", actor, created.id, incoming))
    await started.wait()
    running = await service.detail("domain", actor, created.id)
    assert running.turns[0].status == "running"
    replay = await service.submit("domain", actor, created.id, incoming)
    assert replay.turns[0].status == "running" and executor.execute.await_count == 1
    cancelled = await service.cancel("domain", actor, created.id, incoming.request_id)
    assert cancelled.turns[0].status == "cancelled" and not cancelled.turns[0].execution_terminated
    release.set()
    finished = await pending
    assert finished.turns[0].status == "cancelled" and finished.turns[0].response is None
    assert finished.turns[0].execution_terminated


@pytest.mark.asyncio
async def test_delete_while_running_never_restores_bodies(setup):
    service, repo, _, executor, actor, incoming = setup
    created = await service.create("domain", actor, None)
    started, release = asyncio.Event(), asyncio.Event()

    async def execute(**kwargs):
        started.set()
        await release.wait()
        return response()

    executor.execute.side_effect = execute
    pending = asyncio.create_task(service.submit("domain", actor, created.id, incoming))
    await started.wait()
    running = await service.detail("domain", actor, created.id)
    await service.delete("domain", actor, created.id, running.revision)
    release.set()
    with pytest.raises(AppError):
        await pending
    saved = repo.items[created.id]
    assert saved.deleted_at and saved.turns[0].query == "" and saved.turns[0].response is None
    assert saved.turns[0].execution_terminated


@pytest.mark.asyncio
async def test_failed_and_stale_turns_are_persisted_without_automatic_retry(setup):
    service, repo, _, executor, actor, incoming = setup
    created = await service.create("domain", actor, None)
    executor.execute.side_effect = RuntimeError("Private provider details")
    failed = await service.submit("domain", actor, created.id, incoming)
    assert failed.turns[0].error_code == "conversation_execution_failed"
    assert failed.turns[0].status == "failed"
    stale = incoming.model_copy(
        update={"request_id": uuid4(), "expected_revision": failed.revision}
    )
    reserve_turn(repo.items[created.id], stale, "identity", datetime.now(UTC) - timedelta(hours=1))
    restored = await service.detail("domain", actor, created.id)
    assert restored.turns[-1].status == "interrupted"
    await service.submit("domain", actor, created.id, stale)
    assert executor.execute.await_count == 1


@pytest.mark.asyncio
async def test_new_consent_does_not_authorize_old_queries_or_dependent_answers(setup):
    service, repo, access, executor, actor, incoming = setup
    created = await service.create("domain", actor, None)
    first = await service.submit("domain", actor, created.id, incoming)
    approved = incoming.model_copy(
        update={
            "request_id": uuid4(),
            "expected_revision": first.revision,
            "codex_input_approval": CodexInputApprovalRequest(
                classification="synthetic", consented=True, disclosure_version="test-v1"
            ),
        }
    )
    second = await service.submit("domain", actor, created.id, approved)
    assert executor.execute.call_args.kwargs["request"].history == []
    # A historical derived answer cannot launder an ancestor without separate consent.
    repo.items[created.id].turns[1].dependencies = [first.turns[0].id]
    third = approved.model_copy(
        update={"request_id": uuid4(), "expected_revision": second.revision}
    )
    await service.submit("domain", actor, created.id, third)
    assert executor.execute.call_args.kwargs["request"].history == []


@pytest.mark.asyncio
async def test_changed_scope_and_insufficient_answer_never_enter_history(setup):
    service, _, access, executor, actor, incoming = setup
    created = await service.create("domain", actor, None)
    insufficient = response()
    insufficient.generation.status = "insufficient_evidence"
    insufficient.generation.text = None
    executor.execute.return_value = insufficient
    first = await service.submit("domain", actor, created.id, incoming)
    second_request = incoming.model_copy(
        update={"request_id": uuid4(), "expected_revision": first.revision}
    )
    executor.execute.return_value = response()
    second = await service.submit("domain", actor, created.id, second_request)
    assert executor.execute.call_args.kwargs["request"].history == []
    access.identity.return_value = "new-index-build"
    third = await service.submit(
        "domain",
        actor,
        created.id,
        incoming.model_copy(update={"request_id": uuid4(), "expected_revision": second.revision}),
    )
    assert third.turns[-1].segment == 2
    assert executor.execute.call_args.kwargs["request"].history == []


@pytest.mark.asyncio
async def test_cancel_before_execution_prevents_provider_call(setup):
    service, _, access, executor, actor, incoming = setup
    created = await service.create("domain", actor, None)
    entered, release = asyncio.Event(), asyncio.Event()
    original = service._history

    async def history(*args):
        entered.set()
        await release.wait()
        return await original(*args)

    service._history = history
    pending = asyncio.create_task(service.submit("domain", actor, created.id, incoming))
    await entered.wait()
    await service.cancel("domain", actor, created.id, incoming.request_id)
    release.set()
    finished = await pending
    assert executor.execute.await_count == 0
    assert finished.turns[0].status == "cancelled" and finished.turns[0].execution_terminated
