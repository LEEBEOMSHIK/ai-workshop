"""Independent real-service ownership and final-authority checks; no external I/O."""

import asyncio
from contextlib import asynccontextmanager
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.conversations.background import ConversationBackground
from ai_workshop.labs.rag.conversations.schemas import ConversationStart
from ai_workshop.labs.rag.conversations.service import ConversationService
from tests.unit.labs.rag.conversations.start_support import attach_memory_starts
from tests.unit.labs.rag.conversations.test_service import MemoryRepository, response


@pytest.mark.parametrize("revoke", [False, True])
async def test_detached_actual_service_replay_and_current_authority(revoke):
    release, completed = Event(), Event()
    state = {}
    actor = uuid4()
    incoming = ConversationStart(
        request_id=uuid4(), query="Synthetic independent question?",
        connection_version_id=uuid4(), workspace_ids=[uuid4()],
    )

    @asynccontextmanager
    async def factory(current_actor):
        assert current_actor == actor
        if not state:
            repo = MemoryRepository()
            attach_memory_starts(repo)
            result = response()
            access = SimpleNamespace(
                identity=AsyncMock(return_value="synthetic-scope"),
                visible=AsyncMock(return_value=True),
            )

            async def execute(**kwargs):
                state["calls"] += 1
                while not release.is_set():
                    await asyncio.sleep(0.001)
                if revoke:
                    access.visible.return_value = False
                return result

            service = ConversationService(
                repo, access,
                SimpleNamespace(detail_for_actor=AsyncMock(), resolve_search=AsyncMock()),
                SimpleNamespace(execute=execute, preflight=AsyncMock()),
                final_authority=AsyncMock(),
            )
            state.update(service=service, calls=0, result=result)
        try:
            yield state["service"]
        finally:
            if release.is_set():
                completed.set()

    runtime = ConversationBackground(factory)
    try:
        accepted = await runtime.start("demo", actor, incoming)
        assert accepted.turns[0].status == "running"
        # A duplicate request during execution only observes the existing reservation.
        replay = await runtime.start("demo", actor, incoming)
        assert replay.id == accepted.id and len(replay.turns) == 1
        assert not completed.is_set()
        release.set()
        assert await asyncio.wait_for(asyncio.to_thread(completed.wait, 5), 6)
        final = await runtime.start("demo", actor, incoming)
        assert state["calls"] == 1
        assert final.id == accepted.id
        assert final.turns[0].execution_terminated
        if revoke:
            assert final.turns[0].status == "failed"
            assert final.turns[0].response is None
        else:
            assert final.turns[0].status == "completed"
            assert final.turns[0].response.generation.text == "Synthetic answer"
            assert final.turns[0].response.generation.citations == []
    finally:
        release.set()
        await runtime.aclose()
