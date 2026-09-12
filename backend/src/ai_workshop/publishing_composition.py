from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends

from ai_workshop.config import Settings, get_settings
from ai_workshop.platform.publishing.delivery import (
    LocalPublicationDelivery,
    ManualPublicationDelivery,
)
from ai_workshop.platform.publishing.public_store import SqlitePublicStudyWriter
from ai_workshop.platform.publishing.repository import SqlAlchemyPublishingRepository
from ai_workshop.platform.publishing.service import PublicationDelivery, PublishingService
from ai_workshop.shared.db import create_engine, create_session_factory


async def get_publishing_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[PublishingService]:
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    delivery: PublicationDelivery
    if settings.publishing_delivery_mode == "local":
        delivery = LocalPublicationDelivery(
            SqlitePublicStudyWriter(settings.publishing_public_store_path)
        )
    else:
        delivery = ManualPublicationDelivery()
    try:
        yield PublishingService(
            SqlAlchemyPublishingRepository(sessions),
            delivery,
            approved_personas=settings.publishing_approved_public_personas,
            limits=settings.publishing_limits,
        )
    finally:
        await engine.dispose()
