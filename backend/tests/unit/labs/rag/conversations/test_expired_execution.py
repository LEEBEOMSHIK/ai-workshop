"""Lease recovery versus executor ownership, using only synthetic in-memory state."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.generation.execution import track_local_http_attempt
from ai_workshop.shared.errors import AppError
from tests.unit.labs.rag.conversations.test_service import response, seed_conversation, setup
from tests.unit.labs.rag.executions.test_observer import Recorder


def stored_state(detail):
    # This in-memory recorder has no persisted execution reader. Compare the
    # conversation contract separately from that transient observation flag.
    return detail.model_dump(exclude={"turns": {"__all__": {"observation_complete"}}})


@pytest.mark.parametrize("trigger", ["detail", "submit"])
@pytest.mark.parametrize("remote_pending", [False, True])
async def test_expiration_blocks_new_execution_through_join_and_persists_termination(
    trigger, remote_pending,
):
    service, repo, _, executor, actor, incoming = setup.__wrapped__()
    created = await seed_conversation(service, "domain", actor)
    started, cleanup_started, release, joined = (asyncio.Event() for _ in range(4))
    recorder = Recorder()
    service.recorder = recorder

    async def execute(**kwargs):
        if executor.execute.await_count > 1:
            return response()
        started.set()
        try:
            if remote_pending:
                await track_local_http_attempt(asyncio.Event().wait())
            else:
                await asyncio.Event().wait()
        finally:
            cleanup_started.set()
            await release.wait()
            joined.set()

    executor.execute.side_effect = execute
    pending = asyncio.create_task(service.submit("domain", actor, created.id, incoming))

    async def assert_blocked():
        current = await service.detail("domain", actor, created.id)
        request = incoming.model_copy(
            update={"request_id": uuid4(), "expected_revision": current.revision}
        )
        with pytest.raises(AppError) as error:
            await service.submit("domain", actor, created.id, request)
        assert error.value.code == "conversation_busy"
        assert executor.execute.await_count == 1
        return current

    try:
        await asyncio.wait_for(started.wait(), 2)
        repo.items[created.id].turns[0].updated_at = datetime.now(UTC) - timedelta(minutes=16)
        if trigger == "submit":
            request = incoming.model_copy(
                update={"request_id": uuid4(), "expected_revision": repo.items[created.id].revision}
            )
            with pytest.raises(AppError) as error:
                await service.submit("domain", actor, created.id, request)
            assert error.value.code == "conversation_revision_conflict"
            # Recovery must commit even when reservation rolls back with 409.
            assert repo.items[created.id].turns[0].status == "interrupted"
        current = await assert_blocked()
        turn = current.turns[0]
        assert turn.status == "interrupted"
        assert turn.error_code == "conversation_termination_unconfirmed"
        assert not turn.execution_terminated
        replay = await service.submit("domain", actor, created.id, incoming)
        assert replay == current and executor.execute.await_count == 1
        await asyncio.wait_for(cleanup_started.wait(), 2)
        assert not joined.is_set()
        await assert_blocked()
        # Repeated transport cancellation cannot skip executor cleanup or persistence.
        pending.cancel()
        await asyncio.sleep(0)
        pending.cancel()
        await asyncio.sleep(0)
        assert not pending.done()
        await assert_blocked()
        release.set()
        final = await asyncio.wait_for(pending, 2)
        assert joined.is_set()
        assert stored_state(final) == stored_state(
            await service.detail("domain", actor, created.id)
        )
        assert stored_state(final) == stored_state(
            await service.submit("domain", actor, created.id, incoming)
        )
        saved = final.turns[0]
        assert saved.status == "interrupted" and saved.response is None
        assert saved.execution_terminated is not remote_pending
        assert saved.error_code == (
            "provider_termination_unconfirmed" if remote_pending
            else "conversation_execution_interrupted"
        )
        assert recorder.outcome.state == "interrupted"
        assert recorder.outcome.error_code == saved.error_code
        assert recorder.outcome.answer_status is None
        if remote_pending:
            await assert_blocked()
        else:
            next_request = incoming.model_copy(
                update={"request_id": uuid4(), "expected_revision": final.revision}
            )
            result = await service.submit("domain", actor, created.id, next_request)
            assert result.turns[-1].status == "completed"
            assert executor.execute.await_count == 2
    finally:
        release.set()
        if not pending.done():
            pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)


async def test_late_answer_after_expiration_is_not_saved_returned_or_observed_as_answered():
    service, repo, _, executor, actor, incoming = setup.__wrapped__()
    created = await seed_conversation(service, "domain", actor)
    recorder = Recorder()
    service.recorder = recorder
    reached, release = asyncio.Event(), asyncio.Event()

    async def final_authority(*args):
        reached.set()
        await release.wait()

    service.final_authority = final_authority
    pending = asyncio.create_task(service.submit("domain", actor, created.id, incoming))
    try:
        await asyncio.wait_for(reached.wait(), 2)
        assert executor.execute.await_count == 1
        repo.items[created.id].turns[0].updated_at = datetime.now(UTC) - timedelta(minutes=16)
        expired = await service.detail("domain", actor, created.id)
        assert expired.turns[0].status == "interrupted"
        release.set()
        final = await asyncio.wait_for(pending, 2)
        assert final.turns[0].status == "interrupted"
        assert final.turns[0].execution_terminated
        assert final.turns[0].error_code == "conversation_execution_interrupted"
        assert final.turns[0].response is None
        assert recorder.outcome.state == "interrupted"
        assert recorder.outcome.answer_status is None
        assert stored_state(final) == stored_state(
            await service.detail("domain", actor, created.id)
        )
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)


async def test_expiration_before_executor_start_still_requires_owner_finalization():
    service, repo, _, executor, actor, incoming = setup.__wrapped__()
    created = await seed_conversation(service, "domain", actor)
    reached, release = asyncio.Event(), asyncio.Event()
    original_history = service._history

    async def history(*args):
        reached.set()
        await release.wait()
        return await original_history(*args)

    service._history = history
    pending = asyncio.create_task(service.submit("domain", actor, created.id, incoming))
    try:
        await asyncio.wait_for(reached.wait(), 2)
        repo.items[created.id].turns[0].updated_at = datetime.now(UTC) - timedelta(minutes=16)
        current = await service.detail("domain", actor, created.id)
        assert current.turns[0].error_code == "conversation_termination_unconfirmed"
        new_request = incoming.model_copy(
            update={"request_id": uuid4(), "expected_revision": current.revision}
        )
        with pytest.raises(AppError) as error:
            await service.submit("domain", actor, created.id, new_request)
        assert error.value.code == "conversation_busy"
        release.set()
        final = await asyncio.wait_for(pending, 2)
        executor.execute.assert_not_awaited()
        assert final.turns[0].execution_terminated
        assert final.turns[0].error_code == "conversation_execution_interrupted"
        assert final.turns[0].status == "interrupted"
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)
