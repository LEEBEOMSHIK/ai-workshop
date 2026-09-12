from __future__ import annotations

from fastapi import FastAPI

from ai_workshop.platform.publishing.http import NoStoreMiddleware
from ai_workshop.platform.publishing.public_api import get_public_reader, router
from ai_workshop.platform.publishing.public_store import SqlitePublicStudyReader
from ai_workshop.platform.publishing.settings import PublicSettings
from ai_workshop.shared.errors import COMMON_ERROR_RESPONSES, register_error_handlers
from ai_workshop.shared.request_context import CorrelationIdMiddleware


def create_public_app(
    settings: PublicSettings | None = None,
    reader: SqlitePublicStudyReader | None = None,
) -> FastAPI:
    application = FastAPI(
        title="AI Workshop Public Studies",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        responses=COMMON_ERROR_RESPONSES,
    )
    application.add_middleware(NoStoreMiddleware)
    application.add_middleware(CorrelationIdMiddleware)
    register_error_handlers(application)
    application.include_router(router)
    selected_reader = reader
    if selected_reader is None and settings is not None:
        selected_reader = SqlitePublicStudyReader(settings.store_path)
    if selected_reader is not None:
        application.dependency_overrides[get_public_reader] = lambda: selected_reader
    return application


app = create_public_app()
