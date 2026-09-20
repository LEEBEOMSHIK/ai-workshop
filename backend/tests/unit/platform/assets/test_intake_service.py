from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from ai_workshop.platform.assets.intake_contracts import UploadIntakeClaim
from ai_workshop.platform.assets.intake_service import UploadIntakeLease
from ai_workshop.platform.assets.provenance_contracts import SourceIdentity
from ai_workshop.platform.assets.temporary_contracts import TemporaryBinding


def claim():
    return UploadIntakeClaim(
        uuid4(),
        SourceIdentity(uuid4(), uuid4(), uuid4()),
        uuid4(),
        True,
        TemporaryBinding("intake_test", uuid4()),
    )


class Journal:
    def __init__(self, events, fail=None):
        self.events, self.fail = events, fail

    async def transition(self, current, *, expected_state):
        self.events.append(expected_state)
        if self.fail == expected_state:
            raise RuntimeError("private synthetic failure")
        return replace(
            current,
            state={"open": "closed", "closed": "cleaning", "cleaning": "cleaned"}[expected_state],
            revision=current.revision + 1,
        )


class Workspace:
    root = Path("synthetic")

    def __init__(self, events):
        self.events = events

    def discard(self):
        self.events.append("discard")

    def close(self):
        self.events.append("release")


class Store:
    def __init__(self, events):
        self.events = events

    def observe(self, current):
        self.events.append("observe")
        return False


@pytest.mark.asyncio
async def test_intake_cleanup_uses_acknowledged_revisions_and_exact_order():
    events = []
    lease = UploadIntakeLease(claim(), Workspace(events), Journal(events), Store(events))
    await lease.finish()
    assert events == ["open", "closed", "discard", "observe", "cleaning", "release"]
    assert lease.claim.state == "cleaned"
    assert lease.claim.revision == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["open", "closed"])
async def test_failed_cleanup_commit_never_deletes_or_overrides_upload_outcome(failure, caplog):
    events = []
    lease = UploadIntakeLease(claim(), Workspace(events), Journal(events, failure), Store(events))
    await lease.finish()
    assert "discard" not in events
    assert events[-1] == "release"
    assert "private synthetic" not in caplog.text
    assert "http_intake_cleanup_incomplete" in caplog.text


@pytest.mark.asyncio
async def test_uncertain_source_commit_preserves_intake_even_after_body_writer_ended():
    events = []
    lease = UploadIntakeLease(claim(), Workspace(events), Journal(events), Store(events))
    lease.mark_uncertain()
    await lease.finish()
    assert events == ["release"]
    assert lease.claim.state == "open"


@pytest.mark.asyncio
async def test_uncertain_payload_close_preserves_allocation(monkeypatch):
    from ai_workshop.platform.assets.intake_service import _payload_file

    events = []
    lease = UploadIntakeLease(claim(), Workspace(events), Journal(events), Store(events))

    class Handle:
        def close(self):
            raise OSError("synthetic private path")

    monkeypatch.setattr(Path, "open", lambda *args, **kwargs: Handle())
    with pytest.raises(OSError), _payload_file(Path("synthetic"), "wb", lease):
        pass
    await lease.finish()
    assert events == ["release"]


@pytest.mark.asyncio
async def test_remaining_file_prevents_cleaned_acknowledgement(caplog):
    events = []

    class PresentStore(Store):
        def observe(self, current):
            return True

    lease = UploadIntakeLease(claim(), Workspace(events), Journal(events), PresentStore(events))
    await lease.finish()
    assert lease.claim.state == "cleaning"
    assert events == ["open", "closed", "discard", "release"]
    assert "http_intake_cleanup_incomplete" in caplog.text
    await lease.finish()
    assert events == ["open", "closed", "discard", "release"]
