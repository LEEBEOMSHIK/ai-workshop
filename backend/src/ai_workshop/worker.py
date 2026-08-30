from asyncio import run
from collections.abc import Callable
from dataclasses import dataclass
from os import environ
from typing import Annotated, Protocol
from uuid import UUID

from celery import Celery, Task  # type: ignore[import-untyped]
from fastapi import Depends

from ai_workshop.config import Settings, get_settings
from ai_workshop.labs.rag.ingestion.domain import EnsureIndexedCommand, RagIngestionError
from ai_workshop.labs.rag.ingestion.repository import SqlAlchemyRagIngestionCommandRepository
from ai_workshop.labs.rag.ingestion.service import RagIngestionService, RagIngestionWorkflow
from ai_workshop.labs.rag.ingestion.tasks import create_rag_ingestion_workflow
from ai_workshop.labs.rag.parsing.contracts import ParsingError
from ai_workshop.platform.assets.tasks import AssetTaskError, create_asset_verification_workflow
from ai_workshop.shared.db import create_engine, create_session_factory
from ai_workshop.shared.model_registry import load_models

ASSET_VERIFICATION_TASK = "ai_workshop.assets.verify_stored"
RAG_INGESTION_TASK = "ai_workshop.rag.ensure_indexed"

load_models()


@dataclass(frozen=True, slots=True)
class VerifiedAssetSubscription:
    indexing_profile_id: UUID
    requested_by: UUID


class VerifiedAssetSubscriptionPort(Protocol):
    async def for_asset(
        self, asset_version_id: UUID
    ) -> tuple[VerifiedAssetSubscription, ...]: ...


class NoVerifiedAssetSubscriptions:
    async def for_asset(
        self, asset_version_id: UUID
    ) -> tuple[VerifiedAssetSubscription, ...]:
        return ()


def create_celery(
    settings: Settings | None = None,
    *,
    rag_workflow_factory: Callable[[Settings], RagIngestionWorkflow] = (
        create_rag_ingestion_workflow
    ),
    rag_subscriptions: VerifiedAssetSubscriptionPort | None = None,
) -> Celery:
    broker_url = (
        settings.redis_url
        if settings
        else environ.get("AI_WORKSHOP_REDIS_URL", "redis://127.0.0.1:6379/0")
    )
    environment = (
        settings.environment if settings else environ.get("AI_WORKSHOP_ENVIRONMENT", "local")
    )
    subscriptions = rag_subscriptions or NoVerifiedAssetSubscriptions()
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
        shared=False,
    )
    def verify_asset(job_id: str) -> None:
        try:
            resolved_settings = settings or get_settings()
            asset_version_id = run(
                create_asset_verification_workflow(resolved_settings).run(UUID(job_id))
            )
            for subscription in run(subscriptions.for_asset(asset_version_id)):
                rag_job_id = run(
                    _ensure_rag_job(
                        resolved_settings,
                        EnsureIndexedCommand(
                            asset_version_id=asset_version_id,
                            indexing_profile_id=subscription.indexing_profile_id,
                            requested_by=subscription.requested_by,
                        ),
                    )
                )
                application.tasks[RAG_INGESTION_TASK].delay(str(rag_job_id))
        except AssetTaskError as exc:
            raise RuntimeError(exc.code) from exc

    @application.task(  # type: ignore[untyped-decorator]
        bind=True,
        name=RAG_INGESTION_TASK,
        ignore_result=True,
        max_retries=1,
        shared=False,
    )
    def ensure_indexed(task: Task, job_id: str) -> None:
        resolved_settings = settings or get_settings()
        workflow = rag_workflow_factory(resolved_settings)
        try:
            run(workflow.run(UUID(job_id)))
        except Exception as exc:
            code, retryable = _rag_error(exc)
            retries = int(task.request.retries)
            max_retries = int(task.max_retries)
            if retryable and retries < max_retries:
                raise task.retry(exc=exc, countdown=0) from exc
            run(
                workflow.fail(
                    UUID(job_id),
                    error_code=code,
                    error_message="The RAG ingestion stage failed.",
                )
            )
            raise RuntimeError(code) from exc

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


async def _ensure_rag_job(settings: Settings, command: EnsureIndexedCommand) -> UUID:
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    try:
        async with sessions.begin() as session:
            return await RagIngestionService(
                SqlAlchemyRagIngestionCommandRepository(session)
            ).ensure_indexed(command)
    finally:
        await engine.dispose()


def _rag_error(exc: Exception) -> tuple[str, bool]:
    if isinstance(exc, RagIngestionError):
        return exc.code, exc.retryable
    if isinstance(exc, ParsingError):
        return exc.code, False
    if isinstance(exc, OSError):
        return "parser_unavailable", True
    return "rag_ingestion_failed", False
