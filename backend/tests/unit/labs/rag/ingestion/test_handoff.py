from uuid import UUID, uuid4

import pytest

from ai_workshop.labs.rag.ingestion.domain import EnsureIndexedCommand


@pytest.mark.asyncio
async def test_partial_multi_profile_handoff_converges_idempotently() -> None:
    from ai_workshop.labs.rag.ingestion.handoff import RagAssetHandoffReconciler

    asset_version_id = uuid4()
    requested_by = uuid4()
    profiles = (uuid4(), uuid4(), uuid4())
    commands = tuple(
        EnsureIndexedCommand(asset_version_id, profile_id, requested_by)
        for profile_id in profiles
    )

    class Source:
        def __init__(self) -> None:
            self.created: set[UUID] = set()

        async def pending(self, *, limit: int) -> tuple[EnsureIndexedCommand, ...]:
            return tuple(
                command
                for command in commands
                if command.indexing_profile_id not in self.created
            )[:limit]

    class Creator:
        def __init__(self, source: Source) -> None:
            self.source = source
            self.failed_once = False
            self.calls: list[UUID] = []

        async def ensure_indexed(self, command: EnsureIndexedCommand) -> UUID:
            self.calls.append(command.indexing_profile_id)
            if command.indexing_profile_id == profiles[1] and not self.failed_once:
                self.failed_once = True
                raise OSError("synthetic commit loss")
            self.source.created.add(command.indexing_profile_id)
            return uuid4()

    source = Source()
    creator = Creator(source)
    reconciler = RagAssetHandoffReconciler(source, creator)

    partial = await reconciler.run_once()
    recovered = await reconciler.run_once()
    stable = await reconciler.run_once()

    assert (partial.claimed, partial.created, partial.failed) == (3, 2, 1)
    assert (recovered.claimed, recovered.created, recovered.failed) == (1, 1, 0)
    assert (stable.claimed, stable.created, stable.failed) == (0, 0, 0)
    assert source.created == set(profiles)
    assert creator.calls == [profiles[0], profiles[1], profiles[2], profiles[1]]
