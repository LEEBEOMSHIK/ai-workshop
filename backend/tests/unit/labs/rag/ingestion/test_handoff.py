from uuid import UUID, uuid4

import pytest

from ai_workshop.labs.rag.ingestion.domain import EnsureIndexedCommand, RagIngestionError


class RecordingFailures:
    def __init__(self) -> None:
        self.recorded: list[tuple[UUID, str, str, str]] = []
        self.resolved: list[UUID] = []

    async def record(
        self,
        command: EnsureIndexedCommand,
        *,
        error_class: str,
        error_code: str,
        safe_message: str,
    ) -> None:
        self.recorded.append(
            (command.indexing_profile_id, error_class, error_code, safe_message)
        )

    async def resolve(self, command: EnsureIndexedCommand) -> None:
        self.resolved.append(command.indexing_profile_id)


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
    failures = RecordingFailures()
    reconciler = RagAssetHandoffReconciler(source, creator, failures)

    partial = await reconciler.run_once()
    recovered = await reconciler.run_once()
    stable = await reconciler.run_once()

    assert (partial.claimed, partial.created, partial.failed) == (3, 2, 1)
    assert (recovered.claimed, recovered.created, recovered.failed) == (1, 1, 0)
    assert (stable.claimed, stable.created, stable.failed) == (0, 0, 0)
    assert source.created == set(profiles)
    assert creator.calls == [profiles[0], profiles[1], profiles[2], profiles[1]]
    assert failures.recorded[0][1:3] == ("transient", "handoff_operational_failure")
    assert set(failures.resolved) == set(profiles)


@pytest.mark.asyncio
async def test_expected_failures_are_classified_without_exposing_raw_messages() -> None:
    from ai_workshop.labs.rag.ingestion.handoff import RagAssetHandoffReconciler

    requested_by = uuid4()
    commands = tuple(
        EnsureIndexedCommand(uuid4(), uuid4(), requested_by) for _ in range(4)
    )

    class Source:
        async def pending(self, *, limit: int) -> tuple[EnsureIndexedCommand, ...]:
            return commands[:limit]

    class Creator:
        async def ensure_indexed(self, command: EnsureIndexedCommand) -> UUID:
            position = commands.index(command)
            if position == 0:
                raise RagIngestionError(
                    "database_transient",
                    "postgresql://secret@example.test/private",
                    retryable=True,
                )
            if position == 1:
                raise RagIngestionError(
                    "indexing_profile_missing",
                    "private profile detail",
                    retryable=False,
                )
            if position == 2:
                raise RagIngestionError(
                    "index_source_inactive",
                    "private document title",
                    retryable=False,
                )
            return uuid4()

    failures = RecordingFailures()
    result = await RagAssetHandoffReconciler(Source(), Creator(), failures).run_once()

    assert (result.claimed, result.created, result.failed) == (4, 1, 3)
    assert [item[1:3] for item in failures.recorded] == [
        ("transient", "database_transient"),
        ("permanent", "indexing_profile_missing"),
        ("obsolete", "index_source_inactive"),
    ]
    assert all("secret" not in item[3] and "private" not in item[3] for item in failures.recorded)
    assert failures.resolved == [commands[3].indexing_profile_id]


@pytest.mark.asyncio
async def test_programming_error_is_signaled_after_remaining_commands_run() -> None:
    from ai_workshop.labs.rag.ingestion.handoff import (
        RagAssetHandoffReconciler,
        RagAssetHandoffRunError,
    )

    requested_by = uuid4()
    commands = tuple(
        EnsureIndexedCommand(uuid4(), uuid4(), requested_by) for _ in range(2)
    )

    class Source:
        async def pending(self, *, limit: int) -> tuple[EnsureIndexedCommand, ...]:
            return commands[:limit]

    class Creator:
        def __init__(self) -> None:
            self.calls: list[UUID] = []

        async def ensure_indexed(self, command: EnsureIndexedCommand) -> UUID:
            self.calls.append(command.indexing_profile_id)
            if command == commands[0]:
                raise ValueError("synthetic programming error")
            return uuid4()

    creator = Creator()
    failures = RecordingFailures()
    with pytest.raises(RagAssetHandoffRunError) as exc_info:
        await RagAssetHandoffReconciler(Source(), creator, failures).run_once()

    assert creator.calls == [item.indexing_profile_id for item in commands]
    assert failures.recorded == []
    assert failures.resolved == [commands[1].indexing_profile_id]
    assert exc_info.value.result.failed == 1
    assert isinstance(exc_info.value.__cause__, ValueError)
