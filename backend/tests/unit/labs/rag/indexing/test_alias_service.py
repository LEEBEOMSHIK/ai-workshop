import asyncio
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.indexing.alias_service import run_alias_operation
from ai_workshop.labs.rag.indexing.tracking_contracts import IndexBinding, IndexTrackingError


class Journal:
    def __init__(self):
        self.open = False
        self.closed = False

    async def reserve(self, *args):
        if self.open:
            raise IndexTrackingError("rag_index_attempt_busy")
        self.open = True
        return uuid4()

    async def finish(self, operation_id):
        self.open, self.closed = False, True


@pytest.mark.parametrize(
    "mode", ["ok", "timeout", "cancel", "unacknowledged", "mismatch", "commit"]
)
async def test_alias_reservation_and_confirmed_end(mode):
    journal = Journal()
    if mode == "commit":

        async def broken_commit(operation_id):
            raise RuntimeError("synthetic-secret")

        journal.finish = broken_commit
    calls = 0
    target = "test-00000000-0000-0000-0000-000000000001"

    async def cluster():
        return "cluster"

    async def mutate():
        nonlocal calls
        assert journal.open
        calls += 1
        if mode == "timeout":
            raise TimeoutError("synthetic-secret")
        if mode == "cancel":
            raise asyncio.CancelledError()
        return mode != "unacknowledged"

    async def observe():
        return () if mode == "mismatch" else (target,)

    async def run():
        await run_alias_operation(
            journal,
            IndexBinding("rag", "cluster"),
            "test-active",
            uuid4(),
            uuid4(),
            (target,),
            cluster,
            mutate,
            observe,
        )

    if mode == "ok":
        await run()
        assert journal.closed and not journal.open
    else:
        error = asyncio.CancelledError if mode == "cancel" else IndexTrackingError
        with pytest.raises(error) as caught:
            await run()
        assert "synthetic-secret" not in str(caught.value)
        assert journal.open and not journal.closed
        with pytest.raises(IndexTrackingError, match="attempt_busy"):
            await run()
        assert calls == 1


async def test_wrong_cluster_never_reserves_or_writes():
    journal = Journal()

    async def cluster():
        return "different"

    async def forbidden():
        pytest.fail("Must not call ES mutation or observation")

    with pytest.raises(IndexTrackingError, match="binding_mismatch"):
        await run_alias_operation(
            journal,
            IndexBinding("rag", "cluster"),
            "test-active",
            uuid4(),
            uuid4(),
            (),
            cluster,
            forbidden,
            forbidden,
        )
    assert not journal.open
