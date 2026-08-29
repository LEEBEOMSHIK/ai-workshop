from asyncio import run
from os import environ
from typing import Annotated
from uuid import UUID

from celery import Celery  # type: ignore[import-untyped]
from fastapi import Depends

from ai_workshop.config import Settings, get_settings
from ai_workshop.platform.assets.tasks import AssetTaskError, create_asset_verification_workflow
from ai_workshop.shared.model_registry import load_models

ASSET_VERIFICATION_TASK = "ai_workshop.assets.verify_stored"

load_models()


def create_celery(settings: Settings | None = None) -> Celery:
    broker_url = (
        settings.redis_url
        if settings
        else environ.get("AI_WORKSHOP_REDIS_URL", "redis://127.0.0.1:6379/0")
    )
    environment = (
        settings.environment if settings else environ.get("AI_WORKSHOP_ENVIRONMENT", "local")
    )
    application = Celery(
        "ai_workshop",
        broker=broker_url,
        backend=None,
    )
    application.conf.update(
        accept_content=["json"],
        enable_utc=True,
        result_serializer="json",
        task_always_eager=environment == "test",
        task_eager_propagates=True,
        task_serializer="json",
        timezone="UTC",
    )

    @application.task(  # type: ignore[untyped-decorator]
        name=ASSET_VERIFICATION_TASK,
        ignore_result=True,
    )
    def verify_asset(job_id: str) -> None:
        try:
            run(create_asset_verification_workflow(settings or get_settings()).run(UUID(job_id)))
        except AssetTaskError as exc:
            raise RuntimeError(exc.code) from exc

    return application


celery_app = create_celery()


class CeleryJobDispatcher:
    def __init__(self, settings: Settings) -> None:
        self.application = create_celery(settings)

    def verify_asset(self, job_id: UUID) -> None:
        self.application.tasks[ASSET_VERIFICATION_TASK].delay(str(job_id))


def get_job_dispatcher(
    settings: Annotated[Settings, Depends(get_settings)],
) -> CeleryJobDispatcher:
    return CeleryJobDispatcher(settings)
