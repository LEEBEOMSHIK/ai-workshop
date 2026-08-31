from asyncio import run
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from logging import getLogger
from os import environ
from typing import Annotated, Protocol
from uuid import UUID

from celery import Celery, Task  # type: ignore[import-untyped]
from fastapi import Depends
from sqlalchemy.exc import DisconnectionError, OperationalError, TimeoutError

from ai_workshop.config import Settings, get_settings
from ai_workshop.labs.rag.configurations.repository import (
    SqlAlchemyRagConfigurationRepository,
)
from ai_workshop.labs.rag.evaluation.dispatch import EvaluationDispatchReconciler
from ai_workshop.labs.rag.evaluation.repository import (
    SqlAlchemyEvaluationDispatchRepository,
)
from ai_workshop.labs.rag.evaluation.service import EvaluationWorkflow
from ai_workshop.labs.rag.evaluation.tasks import create_evaluation_workflow
from ai_workshop.labs.rag.indexing.recovery import (
    RagAliasParityResult,
    RagAliasParityRunError,
    SqlAlchemyRagAliasParityReconciler,
)
from ai_workshop.labs.rag.ingestion.dispatch import RagDispatchReconciler
from ai_workshop.labs.rag.ingestion.domain import EnsureIndexedCommand, RagIngestionError
from ai_workshop.labs.rag.ingestion.handoff import (
    RagAssetHandoffReconciler,
    RagAssetHandoffResult,
    RagAssetHandoffRunError,
)
from ai_workshop.labs.rag.ingestion.recovery import (
    SqlAlchemyInactiveRagIngestionReconciler,
)
from ai_workshop.labs.rag.ingestion.repository import (
    SqlAlchemyRagAssetHandoffFailureRepository,
    SqlAlchemyRagAssetHandoffSource,
    SqlAlchemyRagDispatchRepository,
    SqlAlchemyRagIngestionCommandRepository,
)
from ai_workshop.labs.rag.ingestion.service import RagIngestionService, RagIngestionWorkflow
from ai_workshop.labs.rag.ingestion.tasks import create_rag_ingestion_workflow
from ai_workshop.labs.rag.parsing.contracts import ParsingError
from ai_workshop.platform.assets.dispatch import (
    AssetVerificationDispatchReconciler,
    SqlAlchemyAssetVerificationDispatchRepository,
)
from ai_workshop.platform.assets.tasks import AssetTaskError, create_asset_verification_workflow
from ai_workshop.shared.db import create_engine, create_session_factory
from ai_workshop.shared.model_registry import load_models

ASSET_VERIFICATION_TASK = "ai_workshop.assets.verify_stored"
ASSET_VERIFICATION_DISPATCH_RECONCILE_TASK = (
    "ai_workshop.assets.reconcile_dispatches"
)
RAG_INGESTION_TASK = "ai_workshop.rag.ensure_indexed"
RAG_DISPATCH_RECONCILE_TASK = "ai_workshop.rag.reconcile_dispatches"
RAG_ASSET_HANDOFF_RECONCILE_TASK = "ai_workshop.rag.reconcile_asset_handoffs"
RAG_EVALUATION_TASK = "ai_workshop.rag.evaluate_configuration_run"
RAG_EVALUATION_DISPATCH_RECONCILE_TASK = (
    "ai_workshop.rag.reconcile_evaluation_dispatches"
)

load_models()
logger = getLogger(__name__)


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


class PersistentVerifiedAssetSubscriptions:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def for_asset(
        self, asset_version_id: UUID
    ) -> tuple[VerifiedAssetSubscription, ...]:
        engine = create_engine(self.settings)
        sessions = create_session_factory(engine)
        try:
            async with sessions() as session:
                subscriptions = await SqlAlchemyRagConfigurationRepository(
                    session
                ).subscriptions_for_asset(asset_version_id)
            return tuple(
                VerifiedAssetSubscription(profile_id, requested_by)
                for profile_id, requested_by in subscriptions
            )
        finally:
            await engine.dispose()


def create_celery(
    settings: Settings | None = None,
    *,
    rag_workflow_factory: Callable[[Settings], RagIngestionWorkflow] = (
        create_rag_ingestion_workflow
    ),
    rag_subscriptions: VerifiedAssetSubscriptionPort | None = None,
    evaluation_workflow_factory: Callable[[Settings], EvaluationWorkflow] = (
        create_evaluation_workflow
    ),
) -> Celery:
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
        beat_schedule={
            "reconcile-rag-ingestion-dispatches": {
                "task": RAG_DISPATCH_RECONCILE_TASK,
                "schedule": 5.0,
            },
            "reconcile-asset-verification-dispatches": {
                "task": ASSET_VERIFICATION_DISPATCH_RECONCILE_TASK,
                "schedule": 5.0,
            },
            "reconcile-rag-asset-handoffs": {
                "task": RAG_ASSET_HANDOFF_RECONCILE_TASK,
                "schedule": 5.0,
            },
            "reconcile-rag-evaluation-dispatches": {
                "task": RAG_EVALUATION_DISPATCH_RECONCILE_TASK,
                "schedule": 5.0,
            },
        },
    )

    @application.task(  # type: ignore
        bind=True,
        name=ASSET_VERIFICATION_TASK,
        ignore_result=True,
        max_retries=3,
        acks_late=True,
        reject_on_worker_lost=True,
        shared=False,
    )
    def verify_asset(task: Task, job_id: str) -> None:
        resolved_settings = settings or get_settings()
        workflow = create_asset_verification_workflow(resolved_settings)
        try:
            subscriptions = rag_subscriptions or PersistentVerifiedAssetSubscriptions(
                resolved_settings
            )
            asset_version_id = run(workflow.run(UUID(job_id)))
            seen_profiles: set[UUID] = set()
            for subscription in run(subscriptions.for_asset(asset_version_id)):
                if subscription.indexing_profile_id in seen_profiles:
                    continue
                seen_profiles.add(subscription.indexing_profile_id)
                run(
                    _ensure_rag_job(
                        resolved_settings,
                        EnsureIndexedCommand(
                            asset_version_id=asset_version_id,
                            indexing_profile_id=subscription.indexing_profile_id,
                            requested_by=subscription.requested_by,
                        ),
                    )
                )
        except Exception as exc:
            code, retryable = _asset_error(exc)
            if not isinstance(exc, AssetTaskError) and retryable:
                with suppress(OperationalError, TimeoutError, DisconnectionError):
                    run(
                        workflow.retry(
                            UUID(job_id),
                            error_code=code,
                            error_message="The asset verification task will be retried.",
                        )
                    )
            if retryable and int(task.request.retries) < int(task.max_retries):
                raise task.retry(exc=exc, countdown=0) from exc
            if retryable or not isinstance(exc, AssetTaskError):
                with suppress(OperationalError, TimeoutError, DisconnectionError):
                    run(
                        workflow.fail(
                            UUID(job_id),
                            error_code=code,
                            error_message="The asset verification task failed.",
                        )
                    )
            raise RuntimeError(code) from exc

    @application.task(  # type: ignore
        name=ASSET_VERIFICATION_DISPATCH_RECONCILE_TASK,
        ignore_result=True,
        shared=False,
    )
    def reconcile_asset_verification_dispatches() -> None:
        resolved_settings = settings or get_settings()
        run(
            _reconcile_asset_verification_dispatches(
                resolved_settings,
                application,
            )
        )

    @application.task(  # type: ignore
        name=RAG_DISPATCH_RECONCILE_TASK,
        ignore_result=True,
        shared=False,
    )
    def reconcile_dispatches() -> None:
        resolved_settings = settings or get_settings()
        run(_reconcile_rag_dispatches(resolved_settings, application))

    @application.task(  # type: ignore
        name=RAG_ASSET_HANDOFF_RECONCILE_TASK,
        ignore_result=True,
        shared=False,
    )
    def reconcile_asset_handoffs() -> None:
        resolved_settings = settings or get_settings()
        run(_reconcile_rag_asset_handoffs(resolved_settings))

    @application.task(  # type: ignore
        name=RAG_EVALUATION_DISPATCH_RECONCILE_TASK,
        ignore_result=True,
        shared=False,
    )
    def reconcile_evaluation_dispatches() -> None:
        resolved_settings = settings or get_settings()
        run(_reconcile_evaluation_dispatches(resolved_settings, application))

    @application.task(  # type: ignore
        name=RAG_EVALUATION_TASK,
        ignore_result=True,
        acks_late=True,
        reject_on_worker_lost=True,
        shared=False,
    )
    def evaluate_configuration_run(run_id: str) -> None:
        resolved_settings = settings or get_settings()
        run(evaluation_workflow_factory(resolved_settings).run(UUID(run_id)))

    @application.task(  # type: ignore
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
        self.settings = settings
        self.application = create_celery(settings)

    def verify_asset(self, job_id: UUID) -> None:
        run(
            _reconcile_asset_verification_dispatches(
                self.settings,
                self.application,
                job_id=job_id,
            )
        )


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


class CeleryRagJobSender:
    def __init__(self, application: Celery) -> None:
        self.application = application

    def send(self, job_id: UUID) -> None:
        self.application.tasks[RAG_INGESTION_TASK].delay(str(job_id))


class PersistentRagIngestionJobCreator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def ensure_indexed(self, command: EnsureIndexedCommand) -> UUID:
        return await _ensure_rag_job(self.settings, command)


class CeleryAssetVerificationJobSender:
    def __init__(self, application: Celery) -> None:
        self.application = application

    def send(self, job_id: UUID) -> None:
        self.application.tasks[ASSET_VERIFICATION_TASK].delay(str(job_id))


class CeleryEvaluationRunSender:
    def __init__(self, application: Celery) -> None:
        self.application = application

    def send(self, run_id: UUID) -> None:
        self.application.tasks[RAG_EVALUATION_TASK].delay(str(run_id))


async def _reconcile_rag_dispatches(settings: Settings, application: Celery) -> None:
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    try:
        await RagDispatchReconciler(
            SqlAlchemyRagDispatchRepository(sessions),
            CeleryRagJobSender(application),
        ).run_once()
    finally:
        await engine.dispose()


async def _reconcile_rag_asset_handoffs(settings: Settings) -> None:
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    try:
        await SqlAlchemyInactiveRagIngestionReconciler(sessions).run_once()
        alias_result = await SqlAlchemyRagAliasParityReconciler(settings).run_once()
        handoff_result: RagAssetHandoffResult | None = None
        handoff_run_error: RagAssetHandoffRunError | None = None
        async with sessions() as session:
            try:
                handoff_result = await RagAssetHandoffReconciler(
                    SqlAlchemyRagAssetHandoffSource(session),
                    PersistentRagIngestionJobCreator(settings),
                    SqlAlchemyRagAssetHandoffFailureRepository(sessions),
                ).run_once()
            except RagAssetHandoffRunError as exc:
                handoff_run_error = exc

        alias_run_error: RagAliasParityRunError | None = None
        try:
            _raise_on_alias_parity_failures(alias_result)
        except RagAliasParityRunError as exc:
            alias_run_error = exc

        handoff_failure_error: RagAssetHandoffRunError | None = None
        if handoff_result is not None:
            try:
                _raise_on_handoff_failures(handoff_result)
            except RagAssetHandoffRunError as exc:
                handoff_failure_error = exc
        if handoff_run_error is not None:
            _log_handoff_run_error(handoff_run_error)
            raise handoff_run_error
        if handoff_failure_error is not None:
            raise handoff_failure_error
        if alias_run_error is not None:
            raise alias_run_error
    finally:
        await engine.dispose()


def _log_handoff_run_error(exc: RagAssetHandoffRunError) -> None:
    identities = ",".join(
        f"{identity.asset_version_id}:{identity.indexing_profile_id}"
        for identity in exc.identities
    )
    logger.error(
        "rag_asset_handoff_reconcile_unexpected_failure "
        "claimed=%d created=%d failed=%d cause_type=%s identities=%s",
        exc.result.claimed,
        exc.result.created,
        exc.result.failed,
        type(exc.__cause__).__name__,
        identities or "none",
    )


def _raise_on_handoff_failures(result: RagAssetHandoffResult) -> None:
    if not result.failed:
        return
    logger.error(
        "rag_asset_handoff_reconcile_failed claimed=%d created=%d failed=%d",
        result.claimed,
        result.created,
        result.failed,
    )
    raise RagAssetHandoffRunError(result)


def _raise_on_alias_parity_failures(result: RagAliasParityResult) -> None:
    if not result.failed:
        return
    failures = ",".join(
        f"{failure.profile_id}:{failure.error_code}:{str(failure.retryable).lower()}"
        for failure in result.failures
    )
    logger.error(
        "rag_alias_parity_reconcile_failed "
        "claimed=%d reconciled=%d failed=%d profiles=%s",
        result.claimed,
        result.reconciled,
        result.failed,
        failures or "none",
    )
    raise RagAliasParityRunError(result)


async def _reconcile_asset_verification_dispatches(
    settings: Settings,
    application: Celery,
    *,
    job_id: UUID | None = None,
) -> None:
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    try:
        await AssetVerificationDispatchReconciler(
            SqlAlchemyAssetVerificationDispatchRepository(sessions),
            CeleryAssetVerificationJobSender(application),
        ).run_once(job_id=job_id)
    finally:
        await engine.dispose()


async def _reconcile_evaluation_dispatches(
    settings: Settings, application: Celery
) -> None:
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    try:
        await EvaluationDispatchReconciler(
            SqlAlchemyEvaluationDispatchRepository(sessions),
            CeleryEvaluationRunSender(application),
        ).run_once()
    finally:
        await engine.dispose()


def _rag_error(exc: Exception) -> tuple[str, bool]:
    if isinstance(exc, RagIngestionError):
        return exc.code, exc.retryable
    if isinstance(exc, ParsingError):
        return exc.code, False
    if isinstance(exc, (OperationalError, TimeoutError, DisconnectionError)):
        return "database_transient", True
    if isinstance(exc, OSError):
        return "parser_unavailable", True
    return "rag_ingestion_failed", False


def _asset_error(exc: Exception) -> tuple[str, bool]:
    if isinstance(exc, AssetTaskError):
        return exc.code, exc.retryable
    if isinstance(exc, (OperationalError, TimeoutError, DisconnectionError)):
        return "database_transient", True
    if isinstance(exc, OSError):
        return "object_unavailable", True
    return "asset_verification_failed", False
