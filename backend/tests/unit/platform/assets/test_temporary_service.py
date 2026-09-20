from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ai_workshop.platform.assets.provenance_contracts import SourceIdentity
from ai_workshop.platform.assets.temporary_contracts import (
    TemporaryBinding,
    TemporaryClaim,
    TemporaryContext,
    TemporaryOwnershipError,
)
from ai_workshop.platform.assets.temporary_service import TemporaryWorkspaceService


class Journal:
    def __init__(self, events, fail=None):
        self.events, self.fail = events, fail

    async def reserve(self, context, purpose, binding, *, coverage):
        self.events.append("reserve")
        if self.fail == "reserve":
            raise RuntimeError("synthetic commit failure")
        return TemporaryClaim(uuid4(), context, purpose, binding, 1, coverage)

    async def transition(self, claim, *, expected_state):
        self.events.append(expected_state)
        if self.fail == expected_state:
            raise RuntimeError("synthetic commit failure")


class Workspace:
    root = Path("synthetic")

    def __init__(self, events, *, fail=False):
        self.events, self.fail = events, fail

    def create_file(self, name):
        return self.root / name

    def discard(self):
        self.events.append("discard")
        if self.fail:
            raise OSError("synthetic cleanup failure")

    def close(self):
        self.events.append("release")


class Store:
    binding = TemporaryBinding("temporary_test", uuid4())

    def __init__(self, events, *, fail=False, remains=False):
        self.events, self.fail, self.remains = events, fail, remains

    def create(self, claim):
        self.events.append("create")
        return Workspace(self.events, fail=self.fail)

    def observe(self, claim):
        self.events.append("observe")
        return self.remains


def context():
    return TemporaryContext(SourceIdentity(uuid4(), uuid4(), uuid4()))


@pytest.mark.asyncio
async def test_reservation_failure_never_creates_workspace():
    events = []
    service = TemporaryWorkspaceService(Journal(events, "reserve"), Store(events))
    with pytest.raises(TemporaryOwnershipError) as failure:
        await service.open(context(), "parsing", coverage="bounded")
    assert str(failure.value) == "storage_unavailable"
    assert events == ["reserve"]


@pytest.mark.asyncio
async def test_acknowledged_transitions_surround_cleanup_and_absence():
    events = []
    service = TemporaryWorkspaceService(Journal(events), Store(events))
    lease = await service.open(context(), "parsing", coverage="bounded")
    await lease.finish(writer_confirmed=True)
    assert events == [
        "reserve",
        "create",
        "open",
        "closed",
        "discard",
        "observe",
        "cleaning",
        "release",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["open", "closed"])
async def test_commit_failure_before_cleanup_does_not_delete(state):
    events = []
    service = TemporaryWorkspaceService(Journal(events, state), Store(events))
    lease = await service.open(context(), "parsing", coverage="bounded")
    with pytest.raises(TemporaryOwnershipError) as failure:
        await lease.finish(writer_confirmed=True)
    assert str(failure.value) == "cleanup_failed"
    assert "discard" not in events
    assert events[-1] == "release"


@pytest.mark.asyncio
@pytest.mark.parametrize("remains", [False, True])
async def test_failed_or_incomplete_cleanup_never_records_cleaned(remains):
    events = []
    service = TemporaryWorkspaceService(
        Journal(events), Store(events, fail=not remains, remains=remains)
    )
    lease = await service.open(context(), "parsing", coverage="bounded")
    with pytest.raises((OSError, TemporaryOwnershipError)):
        await lease.finish(writer_confirmed=True)
    assert "cleaning" not in events
    assert events[-1] == "release"


@pytest.mark.asyncio
async def test_unknown_writer_releases_pins_without_close_or_delete():
    events = []
    service = TemporaryWorkspaceService(Journal(events), Store(events))
    lease = await service.open(context(), "parsing", coverage="runtime_unverified")
    await lease.finish(writer_confirmed=False)
    assert events == ["reserve", "create", "release"]
    with pytest.raises(TemporaryOwnershipError):
        await lease.finish(writer_confirmed=True)


def test_missing_configuration_fails_safely_without_constructing_storage():
    from ai_workshop.platform.assets.temporary_factory import create_temporary_service
    from ai_workshop.shared.errors import AppError

    settings = SimpleNamespace(
        temporary_store_root=None, temporary_store_id=None, temporary_store_binding_id=None
    )
    with pytest.raises(AppError) as failure:
        create_temporary_service(settings, None)
    assert failure.value.code == "temporary_storage_unavailable"
