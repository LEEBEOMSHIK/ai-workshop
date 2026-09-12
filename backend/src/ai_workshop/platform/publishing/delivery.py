from __future__ import annotations

import asyncio
from typing import Protocol

from ai_workshop.platform.publishing.domain import PublicationCommand
from ai_workshop.platform.publishing.public_store import PublicationReceipt


class PublicStudyWriter(Protocol):
    def initialize(self) -> None: ...

    def apply(self, command: PublicationCommand) -> PublicationReceipt: ...


class LocalPublicationDelivery:
    def __init__(self, writer: PublicStudyWriter) -> None:
        self._writer = writer

    async def deliver(self, command: PublicationCommand) -> PublicationReceipt:
        await asyncio.to_thread(self._writer.initialize)
        return await asyncio.to_thread(self._writer.apply, command)


class ManualPublicationDelivery:
    async def deliver(self, command: PublicationCommand) -> None:
        del command
        return None
