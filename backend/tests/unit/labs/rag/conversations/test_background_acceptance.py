"""Acceptance is inside the existing terminal persistence and authority boundary."""

from tests.unit.labs.rag.conversations.test_service import seed_conversation, setup  # noqa: F401


async def test_acceptance_is_persisted_before_execution_and_replay_never_calls_again(
    setup,  # noqa: F811
):
    service, repo, _, executor, actor, incoming = setup
    created = await seed_conversation(service, "domain", actor)
    accepted = []

    def receive(view):
        accepted.append(view)
        assert repo.items[view.id].turns[0].status == "running"
        assert executor.execute.await_count == 0

    result = await service.submit("domain", actor, created.id, incoming, on_accepted=receive)
    assert len(accepted) == 1 and accepted[0].turns[0].status == "running"
    assert result.turns[0].status == "completed"
    await service.submit("domain", actor, created.id, incoming, on_accepted=receive)
    assert len(accepted) == 1 and executor.execute.await_count == 1


async def test_acceptance_failure_cannot_leave_running_reservation(setup):  # noqa: F811
    service, repo, _, executor, actor, incoming = setup
    created = await seed_conversation(service, "domain", actor)

    def fail(view):
        raise RuntimeError("private callback failure")

    result = await service.submit("domain", actor, created.id, incoming, on_accepted=fail)
    assert result.turns[0].status == "failed"
    assert result.turns[0].execution_terminated
    assert repo.items[created.id].turns[0].status == "failed"
    assert executor.execute.await_count == 0
    assert "private" not in result.model_dump_json()


async def test_first_question_acceptance_preserves_start_ledger_replay(setup):  # noqa: F811
    from ai_workshop.labs.rag.conversations.schemas import ConversationStart
    from tests.unit.labs.rag.conversations.start_support import attach_memory_starts

    service, repo, _, executor, actor, incoming = setup
    attach_memory_starts(repo)
    first = ConversationStart.model_validate(incoming.model_dump(
        exclude={"expected_revision"}, exclude_none=True,
    ))
    accepted = []

    def receive(view):
        assert repo.items[view.id].turns[0].request_id == first.request_id
        assert executor.execute.await_count == 0
        accepted.append(view)

    result = await service.start("domain", actor, first, on_accepted=receive)
    assert len(accepted) == 1 and accepted[0].turns[0].status == "running"
    assert result.turns[0].status == "completed"
    replay = await service.start("domain", actor, first, on_accepted=receive)
    assert replay.id == result.id and len(accepted) == 1
    assert executor.execute.await_count == 1
