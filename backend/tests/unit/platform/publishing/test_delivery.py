from __future__ import annotations

import threading

import pytest

from ai_workshop.platform.publishing.delivery import LocalPublicationDelivery
from ai_workshop.platform.publishing.domain import PublicationAction, PublicationCommand
from ai_workshop.platform.publishing.package import StudyContent, StudySnapshot, snapshot_digest
from ai_workshop.platform.publishing.public_store import PublicationReceipt


def command() -> PublicationCommand:
    snapshot = StudySnapshot(
        revision=1,
        content=StudyContent(
            slug="example-study",
            title="Example",
            summary="Summary.",
            topic_keys=("rag",),
            body="Body.",
            verification="Verified.",
            limitations="Synthetic only.",
        ),
    )
    return PublicationCommand(
        slug="example-study",
        sequence=1,
        request_id="publish-one",
        action=PublicationAction.PUBLISH,
        snapshot=snapshot,
        digest=snapshot_digest(snapshot),
    )


class ThreadRecordingWriter:
    def __init__(self) -> None:
        self.thread_ids: list[int] = []

    def initialize(self) -> None:
        self.thread_ids.append(threading.get_ident())

    def apply(self, publication: PublicationCommand) -> PublicationReceipt:
        self.thread_ids.append(threading.get_ident())
        return PublicationReceipt(
            slug=publication.slug,
            sequence=publication.sequence,
            request_id=publication.request_id,
            action=publication.action,
        )


@pytest.mark.asyncio
async def test_local_delivery_runs_blocking_sqlite_work_off_the_event_loop() -> None:
    event_loop_thread = threading.get_ident()
    writer = ThreadRecordingWriter()

    receipt = await LocalPublicationDelivery(writer).deliver(command())

    assert receipt.request_id == "publish-one"
    assert len(writer.thread_ids) == 2
    assert all(thread_id != event_loop_thread for thread_id in writer.thread_ids)
